from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from collections.abc import Callable
from typing import IO


ROOT = Path(__file__).resolve().parents[1]
PM_GUARD = ROOT / "scripts" / "amdgpu-runtime-pm-guard.sh"
FATAL_PATTERN = re.compile(
    r"refcount_t:.*underflow|use-after-free|kernel BUG|BUG:|Oops:|general protection fault|"
    r"amdgpu.*(ring\S*.*timeout|GPU reset|GPU fault|page fault|runtime (suspend|resume).*(fail|error)|device lost)|"
    r"DeviceLost|pm_runtime_work hogged|soft lockup|hard LOCKUP|watchdog: BUG|"
    r"blocked for more than \d+ seconds|hung task",
    re.IGNORECASE,
)


class GpuSafetyError(RuntimeError):
    pass


def fatal_kernel_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if FATAL_PATTERN.search(line)]


class GpuSafetyGuard:
    def __init__(self, artifact_dir: Path, *, stabilize_seconds: int = 30) -> None:
        self.artifact_dir = artifact_dir
        self.stabilize_seconds = stabilize_seconds
        self.cursor = ""
        self.inhibitor: subprocess.Popen[bytes] | None = None
        self.journal: subprocess.Popen[str] | None = None
        self.monitor_thread: threading.Thread | None = None
        self.monitor_target: int | None = None
        self.fault_callback: Callable[[], None] | None = None
        self.fault_lines: list[str] = []
        self.monitor_log: IO[str] | None = None
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)

    def assert_pm(self) -> None:
        try:
            self._run([str(PM_GUARD), "--check"])
        except (OSError, subprocess.SubprocessError) as exc:
            raise GpuSafetyError(f"AMDGPU runtime-PM guard failed: {exc}") from exc

    def capture_cursor(self) -> str:
        try:
            payload = json.loads(self._run(["journalctl", "-b", "-k", "-n", "1", "-o", "json", "--no-pager"]).stdout)
            cursor = str(payload["__CURSOR"])
        except (KeyError, json.JSONDecodeError, OSError, subprocess.SubprocessError) as exc:
            raise GpuSafetyError("could not capture a current-boot kernel journal cursor") from exc
        if not cursor:
            raise GpuSafetyError("kernel journal cursor is empty")
        self.cursor = cursor
        return cursor

    def _journal_text(self, *, after_cursor: bool) -> str:
        command = ["journalctl", "-b", "-k"]
        if after_cursor:
            if not self.cursor:
                raise GpuSafetyError("kernel journal cursor was not captured")
            command.extend(["--after-cursor", self.cursor])
        command.extend(["-o", "short-iso-precise", "--no-pager"])
        try:
            return self._run(command).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise GpuSafetyError("could not inspect the kernel journal") from exc

    def assert_clean_boot(self) -> None:
        faults = fatal_kernel_lines(self._journal_text(after_cursor=False))
        (self.artifact_dir / "preflight-kernel.log").write_text("\n".join(faults), encoding="utf-8")
        if faults:
            raise GpuSafetyError("current boot contains a fatal GPU/kernel safety pattern")

    def check(self, artifact_name: str = "kernel-scan.log") -> None:
        faults = [*self.fault_lines, *fatal_kernel_lines(self._journal_text(after_cursor=True))]
        unique_faults = list(dict.fromkeys(faults))
        (self.artifact_dir / artifact_name).write_text("\n".join(unique_faults), encoding="utf-8")
        if unique_faults:
            raise GpuSafetyError(f"new fatal GPU/kernel safety pattern detected: {unique_faults[0]}")
        self.assert_pm()

    def start(self) -> None:
        self.assert_pm()
        self.assert_clean_boot()
        self.capture_cursor()
        inhibit_command = ["systemd-inhibit"]
        if subprocess.run(["sudo", "-n", "true"], check=False, capture_output=True).returncode == 0:
            inhibit_command = ["sudo", "-n", "systemd-inhibit"]
        self.inhibitor = subprocess.Popen(
            [
                *inhibit_command,
                "--what=sleep:idle",
                "--mode=block",
                "--who=localllm-tuning",
                "--why=Guarded local LLM tuning",
                "sleep",
                "infinity",
            ],
            start_new_session=True,
        )
        time.sleep(1)
        if self.inhibitor.poll() is not None:
            raise GpuSafetyError("could not acquire the tuning sleep inhibitor")

    def start_monitor(
        self,
        target_pgid: int | None,
        name: str,
        *,
        fault_callback: Callable[[], None] | None = None,
    ) -> None:
        if self.journal is not None or self.monitor_thread is not None:
            raise GpuSafetyError("kernel journal monitor is already active")
        self.monitor_target = target_pgid
        self.fault_callback = fault_callback
        self.monitor_log = (self.artifact_dir / f"{name}-kernel-monitor.log").open("a", encoding="utf-8")
        self.journal = subprocess.Popen(
            [
                "journalctl",
                "-b",
                "-k",
                "-f",
                "--after-cursor",
                self.cursor,
                "-o",
                "short-iso-precise",
                "--no-pager",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        def monitor() -> None:
            assert self.journal is not None and self.journal.stdout is not None
            for line in self.journal.stdout:
                if not FATAL_PATTERN.search(line):
                    continue
                clean_line = line.rstrip()
                self.fault_lines.append(clean_line)
                assert self.monitor_log is not None
                self.monitor_log.write(clean_line + "\n")
                self.monitor_log.flush()
                if target_pgid is not None:
                    try:
                        os.killpg(target_pgid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                if fault_callback is not None:
                    try:
                        fault_callback()
                    except Exception:  # noqa: BLE001
                        pass
                break

        self.monitor_thread = threading.Thread(target=monitor, name="amdgpu-kernel-monitor", daemon=True)
        self.monitor_thread.start()

    def stop_monitor(self) -> None:
        if self.journal is not None:
            self.journal.terminate()
            try:
                self.journal.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.journal.kill()
                self.journal.wait(timeout=5)
        if self.monitor_thread is not None:
            self.monitor_thread.join(timeout=5)
        if self.monitor_log is not None:
            self.monitor_log.close()
        self.journal = None
        self.monitor_thread = None
        self.monitor_target = None
        self.fault_callback = None
        self.monitor_log = None

    def stabilize(self, artifact_name: str) -> None:
        time.sleep(self.stabilize_seconds)
        self.check(artifact_name)

    def close(self) -> None:
        self.stop_monitor()
        if self.inhibitor is not None:
            if self.inhibitor.poll() is None:
                os.killpg(self.inhibitor.pid, signal.SIGTERM)
            try:
                self.inhibitor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.inhibitor.pid, signal.SIGKILL)
                self.inhibitor.wait(timeout=5)
            self.inhibitor = None
