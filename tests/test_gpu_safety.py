from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmarks.gpu_safety import GpuSafetyGuard, fatal_kernel_lines
from benchmarks.tuning_v1.openwendy_ab import ARMS, RUN_ORDER, arm_env, assert_arm_argv


ROOT = Path(__file__).resolve().parents[1]
PM_GUARD = ROOT / "scripts" / "amdgpu-runtime-pm-guard.sh"
GPU_SAFETY = ROOT / "scripts" / "gpu-safety.sh"
FINALIST_RUNNER = ROOT / "benchmarks" / "run_tuning_finalist_barrage.sh"
PRESET_LOADER = ROOT / "scripts" / "load-main-preset.sh"
PRESET_DIR = ROOT / "config" / "presets"


class AmdgpuRuntimePmGuardTests(unittest.TestCase):
    def make_device(self, root: Path, *, control: str = "on", runtime_status: str = "active") -> Path:
        device = root / "bus" / "pci" / "drivers" / "amdgpu" / "0000:2f:00.0"
        (device / "power").mkdir(parents=True)
        (device / "power" / "control").write_text(control, encoding="utf-8")
        (device / "power" / "runtime_status").write_text(runtime_status, encoding="utf-8")
        return device

    def run_guard(self, root: Path, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PM_GUARD), mode],
            env={**os.environ, "AMDGPU_SYSFS_ROOT": str(root)},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_check_accepts_only_on_and_active(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self.make_device(root)
            result = self.run_guard(root, "--check")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("on/active", result.stdout)

    def test_apply_changes_auto_to_on(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            device = self.make_device(root, control="auto")
            result = self.run_guard(root, "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((device / "power" / "control").read_text(encoding="utf-8"), "on")

    def test_missing_device_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "bus" / "pci" / "drivers" / "amdgpu").mkdir(parents=True)
            result = self.run_guard(root, "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("No PCI devices", result.stderr)

    def test_auto_control_fails_check(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self.make_device(root, control="auto")
            result = self.run_guard(root, "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not pinned", result.stderr)

    def test_inactive_runtime_fails_check(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            self.make_device(root, runtime_status="suspended")
            result = self.run_guard(root, "--check")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not active", result.stderr)


class GpuSafetyPatternTests(unittest.TestCase):
    def classify(self, line: str) -> subprocess.CompletedProcess[str]:
        command = f'source "{GPU_SAFETY}"; printf "%s\\n" "$1" | gpu_safety_filter_faults'
        return subprocess.run(
            ["bash", "-c", command, "bash", line],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_fatal_driver_lines_match(self) -> None:
        lines = (
            "refcount_t: underflow; use-after-free.",
            "amdgpu: ring gfx timeout, signaled seq=1",
            "workqueue: pm_runtime_work hogged CPU for >10000us",
            "watchdog: BUG: soft lockup - CPU#5 stuck",
        )
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(self.classify(line).returncode, 0)

    def test_informational_driver_lines_do_not_match(self) -> None:
        lines = (
            "amdgpu: GECC is disabled",
            "amdgpu: SMU is resumed successfully!",
            "amdgpu: VM memory stats for proc llama-server is non-zero when fini",
        )
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(self.classify(line).returncode, 1)

    def test_python_and_shell_classifiers_agree(self) -> None:
        lines = (
            "refcount_t: underflow; use-after-free.",
            "amdgpu: ring gfx_0.0.0 timeout",
            "amdgpu: GECC is disabled",
            "amdgpu: SMU is resumed successfully!",
        )
        for line in lines:
            with self.subTest(line=line):
                shell_matches = self.classify(line).returncode == 0
                self.assertEqual(bool(fatal_kernel_lines(line)), shell_matches)

    def test_shell_monitor_kills_only_owned_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            journalctl = fake_bin / "journalctl"
            journalctl.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'kernel: refcount_t: underflow; use-after-free.'\n"
                "sleep 5\n",
                encoding="utf-8",
            )
            journalctl.chmod(0o755)
            target = subprocess.Popen(["sleep", "30"], start_new_session=True)
            unrelated = subprocess.Popen(["sleep", "30"], start_new_session=True)
            command = (
                f'source "{GPU_SAFETY}"; '
                f'gpu_safety_start_monitor cursor "{target.pid}" "{temp / "artifacts"}"; '
                "sleep 1; set +e; gpu_safety_monitor_clean; status=$?; set -e; "
                "gpu_safety_stop_monitor; exit $status"
            )
            try:
                result = subprocess.run(
                    ["bash", "-c", command],
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                target.wait(timeout=5)
                self.assertIsNone(unrelated.poll())
            finally:
                for process in (target, unrelated):
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5)

    def test_shell_monitor_ignores_informational_line(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            journalctl = fake_bin / "journalctl"
            journalctl.write_text("#!/bin/sh\nprintf '%s\\n' 'amdgpu: GECC is disabled'\nsleep 5\n", encoding="utf-8")
            journalctl.chmod(0o755)
            target = subprocess.Popen(["sleep", "30"], start_new_session=True)
            command = (
                f'source "{GPU_SAFETY}"; '
                f'gpu_safety_start_monitor cursor "{target.pid}" "{temp / "artifacts"}"; '
                "sleep 1; gpu_safety_monitor_clean; gpu_safety_stop_monitor"
            )
            try:
                result = subprocess.run(
                    ["bash", "-c", command],
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsNone(target.poll())
            finally:
                if target.poll() is None:
                    target.terminate()
                    target.wait(timeout=5)

    def test_python_monitor_invokes_service_callback_without_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            guard = GpuSafetyGuard(Path(tempdir))
            guard.cursor = "test-cursor"
            callback = mock.Mock()
            fake_journal = mock.Mock()
            fake_journal.stdout = iter(["kernel: refcount_t: underflow; use-after-free.\n"])
            fake_journal.poll.return_value = None
            fake_journal.wait.return_value = 0
            with mock.patch("benchmarks.gpu_safety.subprocess.Popen", return_value=fake_journal):
                guard.start_monitor(None, "callback", fault_callback=callback)
                guard.monitor_thread.join(timeout=2)
                guard.stop_monitor()
            callback.assert_called_once_with()


class OpenWendyAbTests(unittest.TestCase):
    ENV = (
        b"MAIN_MODEL=model.gguf\n"
        b"MAIN_THREADS=10\n"
        b"MAIN_CONTEXT=131072\n"
        b"MAIN_EXTRA_ARGS=-np 1 -tb 8 -ctk q8_0 -ctv q8_0 --spec-type draft-mtp --spec-draft-n-max 2\n"
    )

    def test_arm_env_changes_only_thread_and_mtp_shape(self) -> None:
        finalist = arm_env(self.ENV, ARMS["finalist"])
        self.assertIn(b"MAIN_THREADS=12", finalist)
        self.assertIn(b"-tb 12", finalist)
        self.assertIn(b"--spec-draft-n-max 4", finalist)
        self.assertIn(b"-ctk q8_0 -ctv q8_0", finalist)
        self.assertEqual(arm_env(self.ENV, ARMS["current"]), self.ENV)

    def test_run_order_balances_pairs_and_limits_transitions(self) -> None:
        self.assertEqual(RUN_ORDER, (("current", 1), ("finalist", 1), ("finalist", 2), ("current", 2), ("current", 3), ("finalist", 3)))
        transitions = sum(left[0] != right[0] for left, right in zip(RUN_ORDER, RUN_ORDER[1:], strict=False))
        self.assertEqual(transitions, 3)

    def test_live_argv_gate_requires_q8_and_exact_arm(self) -> None:
        argv = [
            "llama-server", "-t", "12", "-tb", "12", "-ctk", "q8_0", "-ctv", "q8_0",
            "--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
        ]
        assert_arm_argv(argv, ARMS["finalist"])
        argv[argv.index("-ctv") + 1] = "q4_0"
        with self.assertRaisesRegex(ValueError, "Q8"):
            assert_arm_argv(argv, ARMS["finalist"])


class FinalistProfileTests(unittest.TestCase):
    def dry_run(self, model_id: str) -> dict:
        result = subprocess.run(
            [str(FINALIST_RUNNER), model_id, f"/tmp/{model_id}-dry-run"],
            cwd=ROOT,
            env={**os.environ, "BARRAGE_V2_DRY_RUN": "true", "BARRAGE_V2_ORDER_SEED": "73627"},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_35b_unsloth_profile_is_exact_no_spec_q8(self) -> None:
        profile = self.dry_run("qwen35-unsloth")
        self.assertEqual(profile["context"], 163840)
        self.assertIn("Qwen3.6-35B-A3B-UD-Q6_K-unsloth.gguf", profile["candidates"][0])
        self.assertIn("-ctk q8_0 -ctv q8_0", profile["extra_args"])
        self.assertNotIn("--spec-type", profile["extra_args"])
        self.assertIn("-b 4096 -ub 2048", profile["extra_args"])

    def test_35b_huihui_profile_is_exact_mtp_n3_q8(self) -> None:
        profile = self.dry_run("qwen35-huihui")
        self.assertEqual(profile["context"], 262144)
        self.assertIn("Huihui-Qwen3.6-35B-A3B-abliterated-MTP-Q6_K.gguf", profile["candidates"][0])
        self.assertIn("-ctk q8_0 -ctv q8_0", profile["extra_args"])
        self.assertIn("--spec-type draft-mtp --spec-draft-n-max 3", profile["extra_args"])
        self.assertIn("-b 1024 -ub 512", profile["extra_args"])

    def test_retained_presets_match_validated_production_shapes(self) -> None:
        presets = {
            "27u": ("main-qwen-3.6-27b-mtp-unsloth-q6-fast-128k.env", "false", "2"),
            "27h": ("main-qwen-3.6-27b-mtp-huihui-q6-fast-128k.env", "false", "4"),
            "35u": ("main-qwen-3.6-35b-a3b-unsloth-q6-fast-160k.env", "true", None),
            "35h": ("main-qwen-3.6-35b-a3b-huihui-mtp-q6-full-256k-q8.env", "true", "3"),
        }
        for model_id, (filename, exclusive, mtp_n) in presets.items():
            with self.subTest(model_id=model_id):
                text = (PRESET_DIR / filename).read_text(encoding="utf-8")
                self.assertIn(f"MAIN_EXCLUSIVE_GPU={exclusive}", text)
                self.assertIn("MAIN_THREADS=10", text)
                self.assertIn("MAIN_CACHE_RAM=2048", text)
                self.assertIn("-tb 8", text)
                self.assertIn("--threads-http 4", text)
                self.assertIn("-ctk q8_0 -ctv q8_0", text)
                self.assertIn("--image-max-tokens 8192", text)
                if model_id.startswith("27"):
                    self.assertIn("MAIN_GPU_LAYERS=auto", text)
                    self.assertIn("MAIN_FIT=true", text)
                    self.assertIn("-b 2048 -ub 1024", text)
                elif model_id == "35h":
                    self.assertIn("MAIN_GPU_LAYERS=auto", text)
                    self.assertIn("MAIN_FIT=true", text)
                    self.assertIn("-b 1024 -ub 512", text)
                else:
                    self.assertIn("-b 4096 -ub 2048", text)
                if mtp_n is None:
                    self.assertNotIn("--spec-", text)
                    self.assertNotIn("--no-mmap", text)
                else:
                    self.assertIn(f"--spec-type draft-mtp --spec-draft-n-max {mtp_n}", text)


class PresetLoaderTests(unittest.TestCase):
    def make_fixture(self, temp: Path, *, exclusive: bool, reranker_active: bool = True) -> tuple[dict[str, str], Path, Path]:
        model_dir = temp / "models"
        preset_dir = temp / "presets"
        fake_bin = temp / "bin"
        state_dir = temp / "state"
        for path in (model_dir, preset_dir, fake_bin, state_dir):
            path.mkdir()
        for filename in ("old.gguf", "old-mmproj.gguf", "new.gguf", "new-mmproj.gguf"):
            (model_dir / filename).write_text("fixture", encoding="utf-8")
        active = temp / "active.env"
        active.write_text(
            "MAIN_MODEL=old.gguf\nMAIN_ALIAS=old\nMAIN_MMPROJ=old-mmproj.gguf\nMAIN_EXCLUSIVE_GPU=false\n",
            encoding="utf-8",
        )
        preset = preset_dir / "main-target.env"
        preset.write_text(
            "MAIN_MODEL=new.gguf\nMAIN_ALIAS=new\nMAIN_MMPROJ=new-mmproj.gguf\n"
            f"MAIN_EXCLUSIVE_GPU={'true' if exclusive else 'false'}\n",
            encoding="utf-8",
        )
        (state_dir / "localllm-main.service").write_text("active", encoding="utf-8")
        (state_dir / "localllm-reranker.service").write_text(
            "active" if reranker_active else "inactive",
            encoding="utf-8",
        )
        systemctl = fake_bin / "systemctl"
        systemctl.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "action=''\nservice=''\n"
            "for arg in \"$@\"; do\n"
            "  case \"$arg\" in is-active|start|stop|daemon-reload) action=\"$arg\" ;; *.service) service=\"$arg\" ;; esac\n"
            "done\n"
            "[[ \"$action\" == daemon-reload ]] && exit 0\n"
            "state=\"$FAKE_STATE_DIR/$service\"\n"
            "case \"$action\" in\n"
            "  is-active) value=$(cat \"$state\"); [[ \"$*\" != *--quiet* ]] && printf '%s\\n' \"$value\"; [[ \"$value\" == active ]] ;;\n"
            "  stop) printf inactive >\"$state\"; printf 'stop %s\\n' \"$service\" >>\"$FAKE_STATE_DIR/actions\" ;;\n"
            "  start)\n"
            "    if [[ \"$service\" == localllm-main.service && -f \"$FAKE_STATE_DIR/fail-main-once\" ]]; then\n"
            "      rm \"$FAKE_STATE_DIR/fail-main-once\"; exit 1\n"
            "    fi\n"
            "    printf active >\"$state\"; printf 'start %s\\n' \"$service\" >>\"$FAKE_STATE_DIR/actions\" ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        journalctl = fake_bin / "journalctl"
        journalctl.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$*\" == *'-o json'* ]]; then printf '%s\\n' '{\"__CURSOR\":\"fixture\"}'; exit 0; fi\n"
            "if [[ \"$*\" == *'--after-cursor'* ]]; then\n"
            "  count_file=\"$FAKE_STATE_DIR/journal-scans\"\n"
            "  count=0; [[ ! -f \"$count_file\" ]] || count=$(cat \"$count_file\")\n"
            "  count=$((count + 1)); printf '%s' \"$count\" >\"$count_file\"\n"
            "  if [[ -n \"${FAKE_JOURNAL_FAULT_AFTER:-}\" && \"$count\" -ge \"$FAKE_JOURNAL_FAULT_AFTER\" ]]; then\n"
            "    printf '%s\\n' 'kernel: amdgpu ring gfx timeout'\n"
            "  fi\n"
            "fi\n",
            encoding="utf-8",
        )
        curl = fake_bin / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$*\" == *'/props'* && -n \"${FAKE_PROPS_FAIL:-}\" ]]; then exit 22; fi\n"
            "if [[ \"$*\" == *'/props'* ]]; then alias=$(sed -n 's/^MAIN_ALIAS=//p' \"$FAKE_ACTIVE_FILE\"); "
            "printf '{\"model_alias\":\"%s\"}\\n' \"$alias\"; else printf '{}\\n'; fi\n",
            encoding="utf-8",
        )
        sudo = fake_bin / "sudo"
        sudo.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        inhibitor = fake_bin / "systemd-inhibit"
        inhibitor.write_text("#!/usr/bin/env bash\nexec sleep 30\n", encoding="utf-8")
        pm_guard = fake_bin / "pm-guard"
        pm_guard.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        for script in (systemctl, journalctl, curl, sudo, inhibitor, pm_guard):
            script.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "LLAMA_CPP_MODEL_DIR": str(model_dir),
            "LOCALLLM_PRESET_DIR": str(preset_dir),
            "LOCALLLM_ACTIVE_FILE": str(active),
            "FAKE_ACTIVE_FILE": str(active),
            "FAKE_STATE_DIR": str(state_dir),
            "GPU_SAFETY_PM_GUARD": str(pm_guard),
            "GPU_SAFETY_STABILIZE_SECONDS": "0",
        }
        return env, active, state_dir

    def run_loader(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PRESET_LOADER), "target"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )

    def test_exclusive_preset_stops_reranker(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            env, active, state = self.make_fixture(Path(tempdir), exclusive=True)
            result = self.run_loader(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("MAIN_ALIAS=new", active.read_text(encoding="utf-8"))
            self.assertEqual((state / "localllm-reranker.service").read_text(encoding="utf-8"), "inactive")

    def test_nonexclusive_preset_starts_reranker(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            env, _, state = self.make_fixture(Path(tempdir), exclusive=False, reranker_active=False)
            result = self.run_loader(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((state / "localllm-reranker.service").read_text(encoding="utf-8"), "active")

    def test_failed_load_restores_previous_config_and_service_state(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            env, active, state = self.make_fixture(Path(tempdir), exclusive=True)
            original = active.read_bytes()
            (state / "fail-main-once").touch()
            result = self.run_loader(env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(active.read_bytes(), original)
            self.assertEqual((state / "localllm-main.service").read_text(encoding="utf-8"), "active")
            self.assertEqual((state / "localllm-reranker.service").read_text(encoding="utf-8"), "active")

    def test_failed_props_read_restores_previous_config_and_service_state(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            env, active, state = self.make_fixture(Path(tempdir), exclusive=False, reranker_active=False)
            original = active.read_bytes()
            env["FAKE_PROPS_FAIL"] = "true"
            result = self.run_loader(env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Could not read properties", result.stderr)
            self.assertEqual(active.read_bytes(), original)
            self.assertEqual((state / "localllm-main.service").read_text(encoding="utf-8"), "active")
            self.assertEqual((state / "localllm-reranker.service").read_text(encoding="utf-8"), "inactive")

    def test_gpu_fault_stops_services_without_attempting_rollback_load(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            env, active, state = self.make_fixture(Path(tempdir), exclusive=True)
            env["FAKE_JOURNAL_FAULT_AFTER"] = "2"
            result = self.run_loader(env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("GPU safety check failed", result.stderr)
            self.assertIn("MAIN_ALIAS=new", active.read_text(encoding="utf-8"))
            self.assertEqual((state / "localllm-main.service").read_text(encoding="utf-8"), "inactive")
            self.assertEqual((state / "localllm-reranker.service").read_text(encoding="utf-8"), "inactive")


if __name__ == "__main__":
    unittest.main()
