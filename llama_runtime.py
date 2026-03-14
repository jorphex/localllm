from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx


LOCAL_HOSTS = {"127.0.0.1", "localhost"}
DEFAULT_LOCALLLM_SHARE = "~/.local/share/localllm/llama.cpp/bin/llama-server"
DEFAULT_OPENWENDY_SHARE = "~/.local/share/openwendy/llama.cpp/bin/llama-server"
DEFAULT_LOCALLLM_MODEL_DIR = "~/.cache/localllm/gguf"
DEFAULT_OPENWENDY_MODEL_DIR = "~/.cache/openwendy/gguf"


def _parse_local_endpoint(base_url: str) -> tuple[str, int]:
    parsed = urlparse(base_url)
    host = parsed.hostname
    port = parsed.port
    if parsed.scheme not in {"http", "https"} or not host or not port:
        raise ValueError(f"Invalid llama.cpp base URL: {base_url}")
    if host not in LOCAL_HOSTS:
        raise ValueError(f"Managed llama.cpp servers require a local host, got: {base_url}")
    return host, port


def _resolve_existing_path(path_value: str | None) -> str | None:
    if not path_value:
        return None
    expanded = os.path.abspath(os.path.expanduser(path_value))
    if os.path.isfile(expanded):
        return expanded
    return None


def _resolve_existing_dir(path_value: str | None) -> str | None:
    if not path_value:
        return None
    expanded = os.path.abspath(os.path.expanduser(path_value))
    if os.path.isdir(expanded):
        return expanded
    return None


def resolve_llama_server_bin(config_data: dict) -> str:
    configured_value = config_data.get("llama_server_bin")
    if configured_value:
        configured = _resolve_existing_path(configured_value)
        if configured:
            return configured
        expanded = os.path.abspath(os.path.expanduser(str(configured_value)))
        raise FileNotFoundError(f"Configured llama-server binary does not exist: {expanded}")

    repo_candidate = os.path.join(
        os.path.dirname(__file__),
        "tools",
        "llama.cpp",
        "bin",
        "llama-server",
    )
    if os.path.isfile(repo_candidate):
        return repo_candidate

    for candidate in (DEFAULT_LOCALLLM_SHARE, DEFAULT_OPENWENDY_SHARE):
        resolved = _resolve_existing_path(candidate)
        if resolved:
            return resolved

    on_path = shutil.which("llama-server")
    if on_path:
        return on_path

    raise FileNotFoundError(
        "Could not find llama-server. Set `llama_server_bin`, place it under "
        "`tools/llama.cpp/bin/llama-server`, install it under "
        "`~/.local/share/localllm/llama.cpp/bin/llama-server` or "
        "`~/.local/share/openwendy/llama.cpp/bin/llama-server`, or make it available on PATH."
    )


def resolve_model_path(config_data: dict, model_name: str) -> str:
    if os.path.isabs(model_name) and os.path.isfile(model_name):
        return model_name
    search_dirs = []
    configured_dir_value = config_data.get("llama_cpp_model_dir")
    if configured_dir_value:
        search_dirs.append(os.path.abspath(os.path.expanduser(str(configured_dir_value))))
    else:
        for candidate_dir in (DEFAULT_LOCALLLM_MODEL_DIR, DEFAULT_OPENWENDY_MODEL_DIR):
            resolved_dir = _resolve_existing_dir(candidate_dir)
            if resolved_dir and resolved_dir not in search_dirs:
                search_dirs.append(resolved_dir)
        if not search_dirs:
            search_dirs.append(os.path.abspath(os.path.expanduser(DEFAULT_LOCALLLM_MODEL_DIR)))

    for model_dir in search_dirs:
        candidate = os.path.join(model_dir, model_name)
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        f"Could not find GGUF model file: {model_name} in {', '.join(search_dirs)}"
    )


def _build_sleep_args(config_data: dict) -> list[str]:
    value = config_data.get("llama_cpp_sleep_idle_seconds")
    if value in (None, "", False):
        return []
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return []
    if seconds < 0:
        return []
    return ["--sleep-idle-seconds", str(seconds)]


def _build_gpu_args(config_data: dict) -> list[str]:
    args: list[str] = []
    device = str(config_data.get("llama_cpp_device") or "").strip()
    if device:
        args.extend(["--device", device])

    gpu_layers = config_data.get("llama_cpp_gpu_layers")
    if gpu_layers not in (None, "", False):
        normalized = str(gpu_layers).strip().lower()
        if normalized in {"auto", "all"}:
            args.extend(["--gpu-layers", normalized])
        else:
            try:
                parsed = int(gpu_layers)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None and parsed >= 0:
                args.extend(["--gpu-layers", str(parsed)])

    if bool(config_data.get("llama_cpp_fit")):
        args.extend(["--fit", "on"])
    return args


def build_main_server_command(config_data: dict) -> list[str]:
    host, port = _parse_local_endpoint(config_data["llama_cpp_base_url"])
    command = [
        resolve_llama_server_bin(config_data),
        "-m",
        resolve_model_path(config_data, config_data["main_model_name"]),
        "--host",
        host,
        "--port",
        str(port),
        "-t",
        str(int(config_data.get("llama_cpp_threads") or 12)),
        "-c",
        str(int(config_data.get("llama_cpp_context") or 8192)),
    ]
    mmproj_name = config_data.get("llama_cpp_mmproj_name")
    if mmproj_name:
        command.extend(["-mm", resolve_model_path(config_data, mmproj_name)])
    command.extend(_build_gpu_args(config_data))
    command.extend(_build_sleep_args(config_data))
    return command


def build_embedding_server_command(config_data: dict) -> list[str]:
    host, port = _parse_local_endpoint(config_data["llama_cpp_embedding_base_url"])
    command = [
        resolve_llama_server_bin(config_data),
        "-m",
        resolve_model_path(config_data, config_data["embedding_model_name"]),
        "--embedding",
        "--pooling",
        "last",
        "--host",
        host,
        "--port",
        str(port),
        "-t",
        str(int(config_data.get("llama_cpp_embedding_threads") or config_data.get("llama_cpp_threads") or 12)),
        "-c",
        str(int(config_data.get("llama_cpp_embedding_context") or 8192)),
        "-ub",
        str(int(config_data.get("llama_cpp_embedding_ubatch") or 8192)),
    ]
    command.extend(_build_gpu_args(config_data))
    command.extend(_build_sleep_args(config_data))
    return command


def build_router_server_command(config_data: dict) -> list[str]:
    router_model_name = str(config_data.get("router_model_name") or "").strip()
    if not router_model_name:
        raise ValueError("Router server command requested without `router_model_name` configured.")
    host, port = _parse_local_endpoint(config_data["llama_cpp_router_base_url"])
    command = [
        resolve_llama_server_bin(config_data),
        "-m",
        resolve_model_path(config_data, router_model_name),
        "--host",
        host,
        "--port",
        str(port),
        "-t",
        str(int(config_data.get("llama_cpp_router_threads") or config_data.get("llama_cpp_threads") or 12)),
        "-c",
        str(int(config_data.get("llama_cpp_router_context") or 4096)),
    ]
    command.extend(_build_gpu_args(config_data))
    command.extend(_build_sleep_args(config_data))
    return command


def _wait_for_health(base_url: str, timeout: float = 300.0) -> None:
    deadline = time.time() + timeout
    url = base_url.rstrip("/") + "/health"
    last_error = None
    with httpx.Client(timeout=5.0) as client:
        while time.time() < deadline:
            try:
                response = client.get(url)
                if response.status_code == 200:
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for llama.cpp server health at {url}: {last_error}")


@dataclass
class _ManagedProcess:
    name: str
    base_url: str
    command: list[str]
    log_path: str
    process: subprocess.Popen | None = None
    log_handle: object | None = None
    spawned: bool = False


class ManagedLlamaCppRuntime:
    def __init__(self, config_data: dict, logger) -> None:
        self.config = config_data
        self.logger = logger
        self.processes = [
            _ManagedProcess(
                name="main",
                base_url=config_data["llama_cpp_base_url"],
                command=build_main_server_command(config_data),
                log_path=os.path.abspath("localllm-main.log"),
            ),
            _ManagedProcess(
                name="embedding",
                base_url=config_data["llama_cpp_embedding_base_url"],
                command=build_embedding_server_command(config_data),
                log_path=os.path.abspath("localllm-embed.log"),
            ),
        ]
        router_model_name = str(config_data.get("router_model_name") or "").strip()
        if router_model_name:
            self.processes.append(
                _ManagedProcess(
                    name="router",
                    base_url=config_data["llama_cpp_router_base_url"],
                    command=build_router_server_command(config_data),
                    log_path=os.path.abspath("localllm-router.log"),
                )
            )

    @staticmethod
    def is_enabled(config_data: dict) -> bool:
        return (
            str(config_data.get("local_model_backend") or "").strip().lower() == "llama_cpp"
            and bool(config_data.get("llama_cpp_manage_processes"))
        )

    def start(self) -> None:
        for managed in self.processes:
            if self._is_healthy(managed.base_url):
                self.logger.info(
                    "Reusing existing llama.cpp %s server at %s",
                    managed.name,
                    managed.base_url,
                )
                continue
            self._spawn(managed)

    def stop(self) -> None:
        for managed in reversed(self.processes):
            if not managed.spawned or not managed.process:
                continue
            process = managed.process
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            if managed.log_handle:
                managed.log_handle.close()
            managed.process = None
            managed.log_handle = None
            managed.spawned = False

    def _spawn(self, managed: _ManagedProcess) -> None:
        Path(managed.log_path).parent.mkdir(parents=True, exist_ok=True)
        managed.log_handle = open(managed.log_path, "ab")
        env = os.environ.copy()
        bin_dir = os.path.dirname(os.path.abspath(managed.command[0]))
        existing_ld_library_path = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = (
            bin_dir
            if not existing_ld_library_path
            else f"{bin_dir}:{existing_ld_library_path}"
        )
        managed.process = subprocess.Popen(
            managed.command,
            stdout=managed.log_handle,
            stderr=managed.log_handle,
            env=env,
        )
        managed.spawned = True
        self.logger.info(
            "Started managed llama.cpp %s server: %s",
            managed.name,
            " ".join(managed.command),
        )
        try:
            _wait_for_health(managed.base_url)
        except Exception:
            self.stop()
            raise
        self.logger.info("Managed llama.cpp %s server is healthy at %s", managed.name, managed.base_url)

    def _is_healthy(self, base_url: str) -> bool:
        try:
            _wait_for_health(base_url, timeout=2.0)
        except Exception:  # noqa: BLE001
            return False
        return True
