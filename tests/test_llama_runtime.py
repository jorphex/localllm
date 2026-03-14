import tempfile
import unittest

from pathlib import Path
from unittest.mock import Mock, patch

import llama_runtime


class LlamaRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        temp_path = Path(self.tempdir.name)
        self.bin_path = temp_path / "llama-server"
        self.bin_path.write_text("", encoding="utf-8")
        self.main_model = temp_path / "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
        self.main_model.write_text("", encoding="utf-8")
        self.mmproj = temp_path / "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"
        self.mmproj.write_text("", encoding="utf-8")
        self.embedding_model = temp_path / "Qwen3-Embedding-0.6B-Q8_0.gguf"
        self.embedding_model.write_text("", encoding="utf-8")
        self.router_model = temp_path / "Qwen3.5-2B-Q4_K_M.lmstudio.gguf"
        self.router_model.write_text("", encoding="utf-8")
        self.base_config = {
            "local_model_backend": "llama_cpp",
            "llama_cpp_manage_processes": True,
            "llama_server_bin": str(self.bin_path),
            "llama_cpp_model_dir": self.tempdir.name,
            "llama_cpp_base_url": "http://127.0.0.1:8091",
            "llama_cpp_embedding_base_url": "http://127.0.0.1:8092",
            "llama_cpp_router_base_url": "http://127.0.0.1:8093",
            "llama_cpp_mmproj_name": self.mmproj.name,
            "llama_cpp_threads": 12,
            "llama_cpp_context": 8192,
            "llama_cpp_embedding_threads": 12,
            "llama_cpp_embedding_context": 8192,
            "llama_cpp_embedding_ubatch": 8192,
            "llama_cpp_router_threads": 12,
            "llama_cpp_router_context": 4096,
            "llama_cpp_sleep_idle_seconds": 300,
            "main_model_name": self.main_model.name,
            "embedding_model_name": self.embedding_model.name,
            "router_model_name": self.router_model.name,
        }

    def test_build_main_server_command_includes_model_mmproj_and_sleep(self):
        command = llama_runtime.build_main_server_command(self.base_config)

        self.assertEqual(command[0], str(self.bin_path))
        self.assertIn(str(self.main_model), command)
        self.assertIn(str(self.mmproj), command)
        self.assertIn("--sleep-idle-seconds", command)
        self.assertIn("300", command)
        self.assertEqual(command[-2:], ["--sleep-idle-seconds", "300"])

    def test_build_embedding_server_command_includes_embedding_flags(self):
        command = llama_runtime.build_embedding_server_command(self.base_config)

        self.assertEqual(command[0], str(self.bin_path))
        self.assertIn(str(self.embedding_model), command)
        self.assertIn("--embedding", command)
        self.assertIn("--pooling", command)
        self.assertIn("last", command)
        self.assertIn("-ub", command)
        self.assertIn("8192", command)

    def test_build_router_server_command_includes_router_model(self):
        command = llama_runtime.build_router_server_command(self.base_config)

        self.assertEqual(command[0], str(self.bin_path))
        self.assertIn(str(self.router_model), command)
        self.assertIn("--port", command)
        self.assertIn("8093", command)
        self.assertNotIn(str(self.mmproj), command)

    def test_build_server_commands_include_optional_gpu_args(self):
        config = {
            **self.base_config,
            "llama_cpp_device": "Vulkan0",
            "llama_cpp_gpu_layers": "auto",
            "llama_cpp_fit": True,
        }

        main_command = llama_runtime.build_main_server_command(config)
        embedding_command = llama_runtime.build_embedding_server_command(config)
        router_command = llama_runtime.build_router_server_command(config)

        for command in (main_command, embedding_command, router_command):
            self.assertIn("--device", command)
            self.assertIn("Vulkan0", command)
            self.assertIn("--gpu-layers", command)
            self.assertIn("auto", command)
            self.assertEqual(command[-2:], ["--sleep-idle-seconds", "300"])
            self.assertIn("--fit", command)
            self.assertIn("on", command)

    def test_managed_runtime_reuses_existing_healthy_servers(self):
        runtime = llama_runtime.ManagedLlamaCppRuntime(self.base_config, Mock())

        with patch("llama_runtime.subprocess.Popen") as popen_mock:
            with patch.object(runtime, "_is_healthy", return_value=True):
                runtime.start()

        popen_mock.assert_not_called()

    def test_managed_runtime_spawns_and_stops_owned_processes(self):
        runtime = llama_runtime.ManagedLlamaCppRuntime(self.base_config, Mock())
        for index, managed in enumerate(runtime.processes):
            managed.log_path = str(Path(self.tempdir.name) / f"{managed.name}-{index}.log")

        process_main = Mock()
        process_main.poll.return_value = None
        process_embed = Mock()
        process_embed.poll.return_value = None
        process_router = Mock()
        process_router.poll.return_value = None

        with patch.object(runtime, "_is_healthy", return_value=False):
            with patch(
                "llama_runtime.subprocess.Popen",
                side_effect=[process_main, process_embed, process_router],
            ) as popen_mock:
                with patch("llama_runtime._wait_for_health", return_value=None):
                    runtime.start()

        popen_calls = popen_mock.call_args_list
        self.assertEqual(Path(popen_calls[0].kwargs["env"]["LD_LIBRARY_PATH"].split(":")[0]), Path(self.tempdir.name))
        self.assertTrue(runtime.processes[0].spawned)
        self.assertTrue(runtime.processes[1].spawned)
        self.assertTrue(runtime.processes[2].spawned)

        runtime.stop()

        process_main.send_signal.assert_called_once()
        process_main.wait.assert_called_once()
        process_embed.send_signal.assert_called_once()
        process_embed.wait.assert_called_once()
        process_router.send_signal.assert_called_once()
        process_router.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
