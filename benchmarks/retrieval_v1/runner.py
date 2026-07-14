from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.gpu_safety import GpuSafetyError, GpuSafetyGuard
from benchmarks.retrieval_v1 import SCHEMA_VERSION
from benchmarks.tuning_v1.runner import file_hash, memory_state


ROOT = Path(__file__).resolve().parents[2]
LLAMA_SERVER = Path.home() / ".local/src/llama.cpp/build-vulkan-r9700/bin/llama-server"
EMBED_MODEL = ROOT / "models/embedding/Qwen3-Embedding-4B-Q4_K_M.gguf"
RERANK_MODEL = ROOT / "models/embedding/Qwen3-Reranker-4B-Q4_K_M.gguf"
RESULTS_ROOT = ROOT / "benchmarks/retrieval-v1-results"
MANAGED_SERVICES = (
    "localllm-main.service",
    "localllm-embedding.service",
    "localllm-reranker.service",
    "localllm-tts.service",
)

EMBED_PROFILES: tuple[dict[str, Any], ...] = (
    {"id": "embed-current", "slots": 1, "threads": 8, "threads_batch": 4, "batch": 128, "ubatch": 128},
    {"id": "embed-n4-t8", "slots": 4, "threads": 8, "threads_batch": 8, "batch": 512, "ubatch": 512},
    {"id": "embed-n8-t12", "slots": 8, "threads": 12, "threads_batch": 12, "batch": 1024, "ubatch": 1024},
    {"id": "embed-n12-t12", "slots": 12, "threads": 12, "threads_batch": 12, "batch": 1536, "ubatch": 1536},
)

RERANK_PROFILES: tuple[dict[str, Any], ...] = (
    {"id": "rerank-current", "slots": 1, "threads": 8, "threads_batch": 4, "batch": 512, "ubatch": 512, "fa": "on"},
    {"id": "rerank-b128", "slots": 1, "threads": 8, "threads_batch": 4, "batch": 128, "ubatch": 128, "fa": "on"},
    {"id": "rerank-b256", "slots": 1, "threads": 8, "threads_batch": 4, "batch": 256, "ubatch": 256, "fa": "on"},
    {"id": "rerank-b1024", "slots": 1, "threads": 8, "threads_batch": 4, "batch": 1024, "ubatch": 1024, "fa": "on"},
    {"id": "rerank-tb8", "slots": 1, "threads": 8, "threads_batch": 8, "batch": 512, "ubatch": 512, "fa": "on"},
    {"id": "rerank-t12", "slots": 1, "threads": 12, "threads_batch": 12, "batch": 512, "ubatch": 512, "fa": "on"},
    {"id": "rerank-fa-off", "slots": 1, "threads": 8, "threads_batch": 4, "batch": 512, "ubatch": 512, "fa": "off"},
)


def _topic_text(topic: str, detail: str, target_chars: int = 360) -> str:
    sentence = f"{topic}: {detail}. "
    return (sentence * ((target_chars // len(sentence)) + 1))[:target_chars]


EMBED_WORKLOADS: dict[str, list[str]] = {
    "query": ["Which database and backup policy does the deployment use?"],
    "openwendy_batch8": [
        _topic_text("Database", "the deployment uses PostgreSQL with nightly encrypted backups"),
        _topic_text("Travel", "the train reservation leaves Chiang Mai on Friday morning"),
        _topic_text("Preference", "concise technical answers should lead with the operational result"),
        _topic_text("Hardware", "the workstation has an AMD R9700 GPU and a Ryzen 3900X CPU"),
        _topic_text("Project", "OpenWendy retrieves durable memories before each assistant turn"),
        _topic_text("Schedule", "the weekly review occurs every Monday at nine in the morning"),
        _topic_text("Contact", "the infrastructure escalation path uses the internal operations queue"),
        _topic_text("Testing", "benchmark runs retain aggregate evidence and discard private prompts"),
    ],
}
EMBED_WORKLOADS["backfill_batch32"] = [
    _topic_text(f"Memory {index}", f"synthetic retrieval record number {index} with stable benchmark wording")
    for index in range(32)
]

RETRIEVAL_DOCUMENTS = [
    "The production deployment stores application data in PostgreSQL. Encrypted backups run nightly and are retained for thirty days.",
    "The Chiang Mai train reservation departs on Friday morning. The ticket and platform details are saved in the travel folder.",
    "Technical answers should be concise, lead with the operational result, and separate uncertainty from established evidence.",
    "The workstation uses an AMD Radeon AI PRO R9700 GPU with a Ryzen 9 3900X processor and thirty-two gigabytes of system memory.",
    "OpenWendy retrieves durable memories before each assistant turn and combines semantic search with SQLite full-text search.",
    "The weekly project review begins every Monday at nine in the morning and includes pending work, risks, and benchmark results.",
    "Infrastructure incidents are escalated through the internal operations queue after the local service owner confirms impact.",
    "Benchmark publication retains aggregate measurements and configuration identity while excluding private prompts and responses.",
]
RETRIEVAL_QUALITY_QUERIES = (
    ("Which database is used and how are backups handled?", 0),
    ("When does the Chiang Mai train leave?", 1),
    ("What GPU and processor are installed in the workstation?", 3),
    ("How does OpenWendy find durable memories?", 4),
    ("When is the weekly project review?", 5),
    ("What evidence may be included in a published benchmark?", 7),
)
RERANK_QUERY = RETRIEVAL_QUALITY_QUERIES[0][0]
RERANK_DOCUMENTS = RETRIEVAL_DOCUMENTS
RERANK_WORKLOADS = {
    "pair2": RERANK_DOCUMENTS[:2],
    "openwendy_docs8": RERANK_DOCUMENTS,
}


def json_dump(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def request_json(url: str, body: dict[str, Any] | None = None, timeout: int = 120) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    headers = {} if body is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def wait_for_health(port: int, process: subprocess.Popen[str], timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited during startup with status {process.returncode}")
        try:
            if request_json(f"http://127.0.0.1:{port}/health", timeout=3).get("status") == "ok":
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise TimeoutError(f"server on port {port} did not become healthy")


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm)


def embedding_vectors(payload: dict[str, Any], expected: int) -> list[list[float]]:
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != expected:
        raise ValueError(f"expected {expected} embedding rows, received {len(rows) if isinstance(rows, list) else 'invalid'}")
    ordered = sorted(rows, key=lambda row: int(row.get("index", 0)))
    vectors = [row.get("embedding") for row in ordered]
    if any(not isinstance(vector, list) or len(vector) != 2560 for vector in vectors):
        raise ValueError("embedding response has an invalid vector dimension")
    result = [[float(value) for value in vector] for vector in vectors]
    if any(not math.isfinite(value) for vector in result for value in vector):
        raise ValueError("embedding response contains a non-finite value")
    return result


def reranker_scores(payload: dict[str, Any], expected: int) -> tuple[list[int], list[float]]:
    rows = payload.get("results")
    if not isinstance(rows, list) or len(rows) != expected:
        raise ValueError(f"expected {expected} reranker rows, received {len(rows) if isinstance(rows, list) else 'invalid'}")
    indices = [int(row["index"]) for row in rows]
    scores = [float(row["relevance_score"]) for row in rows]
    if sorted(indices) != list(range(expected)) or any(not math.isfinite(score) for score in scores):
        raise ValueError("reranker response is incomplete or contains a non-finite score")
    return indices, scores


def validate_props(payload: dict[str, Any], profile: dict[str, Any]) -> None:
    settings = payload.get("default_generation_settings")
    context = settings.get("n_ctx") if isinstance(settings, dict) else None
    if context != 2048:
        raise ValueError(f"expected 2048 context per slot, received {context!r}")
    if payload.get("total_slots") != profile["slots"]:
        raise ValueError(f"expected {profile['slots']} slots, received {payload.get('total_slots')!r}")


def embedding_command(profile: dict[str, Any], port: int) -> list[str]:
    total_context = int(profile["slots"]) * 2048
    return [
        str(LLAMA_SERVER), "-m", str(EMBED_MODEL), "--embedding", "--pooling", "last",
        "--host", "127.0.0.1", "--port", str(port), "-t", str(profile["threads"]),
        "-c", str(total_context), "-ub", str(profile["ubatch"]), "--device", "none", "--gpu-layers", "0",
        "-np", str(profile["slots"]), "-b", str(profile["batch"]), "-tb", str(profile["threads_batch"]),
        "-cram", "0", "--no-warmup", "-fa", "off", "--threads-http", "2",
    ]


def reranker_command(profile: dict[str, Any], port: int) -> list[str]:
    total_context = int(profile["slots"]) * 2048
    return [
        str(LLAMA_SERVER), "-m", str(RERANK_MODEL), "--embedding", "--pooling", "rank", "--reranking",
        "--host", "127.0.0.1", "--port", str(port), "--alias", "qwen3-reranker-4b-q4",
        "-t", str(profile["threads"]), "-c", str(total_context), "-ub", str(profile["ubatch"]),
        "--device", "Vulkan0", "--gpu-layers", "auto", "--fit", "on", "-np", str(profile["slots"]),
        "-b", str(profile["batch"]), "-tb", str(profile["threads_batch"]), "-cram", "0",
        "--no-warmup", "-fa", str(profile["fa"]), "--threads-http", "2",
    ]


class RetrievalTuningRunner:
    def __init__(
        self,
        output: Path,
        *,
        repeats: int,
        cooldown: int,
        restore: bool = True,
        phase: str = "all",
    ) -> None:
        self.output = output
        self.repeats = repeats
        self.cooldown = cooldown
        self.restore = restore
        self.phase = phase
        self.guard = GpuSafetyGuard(output / "safety", stabilize_seconds=cooldown)
        self.process: subprocess.Popen[str] | None = None
        self.log_handle: Any = None
        self.process_gpu = False
        self.process_profile_id = ""
        self.embedding_baseline: dict[str, list[list[float]]] = {}
        self.reranker_baseline_order: dict[str, list[int]] = {}
        self.reranker_quality_baseline: dict[str, float | int] | None = None
        self.safety_fault = False
        fixture_manifest = {
            "embedding_workloads": EMBED_WORKLOADS,
            "retrieval_documents": RETRIEVAL_DOCUMENTS,
            "retrieval_quality_queries": RETRIEVAL_QUALITY_QUERIES,
        }
        self.results: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "started_utc": datetime.now(UTC).isoformat(),
            "context_per_slot": 2048,
            "placement": {"embedding": "CPU/RAM", "reranker": "Vulkan0/VRAM"},
            "fixtures": fixture_manifest,
            "fixture_sha256": hashlib.sha256(
                json.dumps(fixture_manifest, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "embedding": [],
            "reranker": [],
        }

    def stop_managed_stack(self) -> None:
        subprocess.run([str(ROOT / "scripts/stop-stack.sh")], check=True, timeout=90)
        active = [
            service
            for service in MANAGED_SERVICES
            if subprocess.run(
                ["systemctl", "--user", "is-active", "--quiet", service], check=False, timeout=10
            ).returncode == 0
        ]
        if active:
            raise RuntimeError(f"managed services remained active: {active}")
        proc = subprocess.run(["pgrep", "-a", "llama-server"], check=False, capture_output=True, text=True)
        if proc.stdout.strip():
            raise RuntimeError(f"competing llama-server processes remain:\n{proc.stdout.strip()}")

    @staticmethod
    def stop_managed_stack_quietly() -> None:
        subprocess.run(
            ["systemctl", "--user", "stop", *MANAGED_SERVICES],
            check=False,
            capture_output=True,
            timeout=90,
        )

    def guarded_initial_unload(self) -> None:
        self.guard.start_monitor(None, "initial-unload", fault_callback=self.stop_managed_stack_quietly)
        try:
            self.stop_managed_stack()
        finally:
            self.guard.stop_monitor()
        self.guard.stabilize("initial-unload-post-transition-kernel.log")

    def guarded_restore(self) -> None:
        self.guard.start_monitor(None, "managed-restore", fault_callback=self.stop_managed_stack_quietly)
        try:
            subprocess.run([str(ROOT / "scripts/start-stack.sh")], check=True, timeout=300)
        except BaseException:
            self.stop_managed_stack_quietly()
            raise
        finally:
            self.guard.stop_monitor()
        self.guard.stabilize("managed-restore-post-transition-kernel.log")

    def start_server(self, command: list[str], profile_id: str, port: int, *, gpu: bool) -> None:
        log_path = self.output / f"{profile_id}.server.log"
        self.log_handle = log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            command,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self.process_gpu = gpu
        self.process_profile_id = profile_id
        if gpu:
            self.guard.start_monitor(self.process.pid, profile_id)
        try:
            wait_for_health(port, self.process)
        except Exception:
            self.stop_server(gpu=gpu, profile_id=profile_id)
            raise

    def stop_server(self, *, gpu: bool, profile_id: str) -> None:
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=10)
        self.process = None
        self.process_gpu = False
        self.process_profile_id = ""
        if self.log_handle is not None:
            self.log_handle.close()
            self.log_handle = None
        if gpu:
            self.guard.stop_monitor()
            self.guard.stabilize(f"{profile_id}-post-transition-kernel.log")

    def run_embedding_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(profile["id"])
        command = embedding_command(profile, 18092)
        row: dict[str, Any] = {"profile": profile, "argv": command, "workloads": {}, "status": "failed"}
        self.start_server(command, profile_id, 18092, gpu=False)
        try:
            row["props"] = request_json("http://127.0.0.1:18092/props")
            validate_props(row["props"], profile)
            row["resources_loaded"] = memory_state()
            all_valid = True
            for name, inputs in EMBED_WORKLOADS.items():
                body = {"model": "local", "input": inputs}
                request_json("http://127.0.0.1:18092/v1/embeddings", body)
                times: list[float] = []
                vectors: list[list[float]] = []
                workload_repeats = 3 if name == "backfill_batch32" else self.repeats
                for _ in range(workload_repeats):
                    started = time.perf_counter()
                    payload = request_json("http://127.0.0.1:18092/v1/embeddings", body)
                    times.append(time.perf_counter() - started)
                    vectors = embedding_vectors(payload, len(inputs))
                baseline = self.embedding_baseline.get(name)
                similarities = [cosine(a, b) for a, b in zip(vectors, baseline, strict=True)] if baseline else [1.0]
                valid = min(similarities) >= 0.995
                all_valid = all_valid and valid
                row["workloads"][name] = {
                    "items": len(inputs),
                    "input_chars": sum(len(value) for value in inputs),
                    "times_seconds": times,
                    "median_seconds": statistics.median(times),
                    "items_per_second": len(inputs) / statistics.median(times),
                    "min_baseline_cosine": min(similarities),
                    "valid": valid,
                    "vector_digest": hashlib.sha256(
                        json.dumps(vectors, separators=(",", ":")).encode()
                    ).hexdigest(),
                }
                if baseline is None:
                    self.embedding_baseline[name] = vectors
            documents_payload = request_json(
                "http://127.0.0.1:18092/v1/embeddings", {"model": "local", "input": RETRIEVAL_DOCUMENTS}
            )
            document_vectors = embedding_vectors(documents_payload, len(RETRIEVAL_DOCUMENTS))
            quality_cases = []
            for query, expected_index in RETRIEVAL_QUALITY_QUERIES:
                query_payload = request_json(
                    "http://127.0.0.1:18092/v1/embeddings", {"model": "local", "input": [query]}
                )
                query_vector = embedding_vectors(query_payload, 1)[0]
                scores = [cosine(query_vector, vector) for vector in document_vectors]
                order = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
                quality_cases.append(
                    {"expected_index": expected_index, "top_index": order[0], "top3": order[:3], "passed": order[0] == expected_index}
                )
            semantic_quality_pass = all(case["passed"] for case in quality_cases)
            row["semantic_quality"] = quality_cases
            row["semantic_quality_pass"] = semantic_quality_pass
            row["status"] = "passed" if all_valid and semantic_quality_pass else "failed"
            return row
        finally:
            self.stop_server(gpu=False, profile_id=profile_id)

    def run_reranker_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(profile["id"])
        command = reranker_command(profile, 18093)
        row: dict[str, Any] = {"profile": profile, "argv": command, "workloads": {}, "status": "failed"}
        self.start_server(command, profile_id, 18093, gpu=True)
        try:
            row["props"] = request_json("http://127.0.0.1:18093/props")
            validate_props(row["props"], profile)
            row["resources_loaded"] = memory_state()
            all_valid = True
            for name, documents in RERANK_WORKLOADS.items():
                body = {
                    "model": "qwen3-reranker-4b-q4",
                    "query": RERANK_QUERY,
                    "documents": documents,
                    "top_n": len(documents),
                }
                request_json("http://127.0.0.1:18093/v1/rerank", body)
                times: list[float] = []
                order: list[int] = []
                scores: list[float] = []
                for _ in range(self.repeats):
                    started = time.perf_counter()
                    payload = request_json("http://127.0.0.1:18093/v1/rerank", body)
                    times.append(time.perf_counter() - started)
                    order, scores = reranker_scores(payload, len(documents))
                baseline_order = self.reranker_baseline_order.get(name)
                valid = True
                all_valid = all_valid and valid
                row["workloads"][name] = {
                    "documents": len(documents),
                    "document_chars": sum(len(value) for value in documents),
                    "times_seconds": times,
                    "median_seconds": statistics.median(times),
                    "documents_per_second": len(documents) / statistics.median(times),
                    "order": order,
                    "scores": scores,
                    "valid": valid,
                }
                if baseline_order is None:
                    self.reranker_baseline_order[name] = order
            quality_cases = []
            for query, expected_index in RETRIEVAL_QUALITY_QUERIES:
                payload = request_json(
                    "http://127.0.0.1:18093/v1/rerank",
                    {
                        "model": "qwen3-reranker-4b-q4",
                        "query": query,
                        "documents": RETRIEVAL_DOCUMENTS,
                        "top_n": len(RETRIEVAL_DOCUMENTS),
                    },
                )
                order, _ = reranker_scores(payload, len(RETRIEVAL_DOCUMENTS))
                expected_rank = order.index(expected_index) + 1
                quality_cases.append(
                    {
                        "expected_index": expected_index,
                        "expected_rank": expected_rank,
                        "top_index": order[0],
                        "top3": order[:3],
                        "passed": order[0] == expected_index,
                    }
                )
            top1_count = sum(case["passed"] for case in quality_cases)
            mean_reciprocal_rank = statistics.mean(1.0 / case["expected_rank"] for case in quality_cases)
            quality_metrics = {"top1_count": top1_count, "mean_reciprocal_rank": mean_reciprocal_rank}
            if self.reranker_quality_baseline is None:
                self.reranker_quality_baseline = quality_metrics
            semantic_quality_pass = (
                top1_count >= int(self.reranker_quality_baseline["top1_count"])
                and mean_reciprocal_rank + 1e-9
                >= float(self.reranker_quality_baseline["mean_reciprocal_rank"])
            )
            row["semantic_quality"] = quality_cases
            row["semantic_quality_metrics"] = quality_metrics
            row["semantic_quality_pass"] = semantic_quality_pass
            row["status"] = "passed" if all_valid and semantic_quality_pass else "failed"
            return row
        finally:
            self.stop_server(gpu=True, profile_id=profile_id)

    @staticmethod
    def winner(rows: list[dict[str, Any]], workload: str) -> dict[str, Any]:
        passing = [row for row in rows if row.get("status") == "passed"]
        if not passing:
            raise RuntimeError(f"no passing profiles for {workload}")
        return min(passing, key=lambda row: row["workloads"][workload]["median_seconds"])

    @staticmethod
    def embedding_winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
        passing = [row for row in rows if row.get("status") == "passed"]
        if not passing:
            raise RuntimeError("no passing embedding profiles")
        fastest_primary = min(row["workloads"]["openwendy_batch8"]["median_seconds"] for row in passing)
        near_fastest = [
            row
            for row in passing
            if row["workloads"]["openwendy_batch8"]["median_seconds"] <= fastest_primary * 1.05
        ]
        return min(
            near_fastest,
            key=lambda row: (
                row["workloads"]["backfill_batch32"]["median_seconds"],
                row["profile"]["slots"],
            ),
        )

    @staticmethod
    def reranker_winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
        passing = [row for row in rows if row.get("status") == "passed"]
        if not passing:
            raise RuntimeError("no passing reranker profiles")
        baseline_vram = int(rows[0]["resources_loaded"]["vram_used_mib"])
        co_resident = [
            row
            for row in passing
            if int(row["resources_loaded"]["vram_used_mib"]) <= baseline_vram + 512
        ]
        if not co_resident:
            raise RuntimeError("no correctness-passing reranker profile meets the 512 MiB VRAM-growth limit")
        return min(co_resident, key=lambda row: row["workloads"]["openwendy_docs8"]["median_seconds"])

    @staticmethod
    def validated_selection(
        current: dict[str, Any],
        finalist: dict[str, Any],
        workload: str,
        *,
        minimum_speedup: float = 1.03,
    ) -> str:
        if current.get("status") != "passed" or finalist.get("status") != "passed":
            return str(current["profile"]["id"])
        current_median = float(current["workloads"][workload]["median_seconds"])
        finalist_median = float(finalist["workloads"][workload]["median_seconds"])
        if current_median / finalist_median < minimum_speedup:
            return str(current["profile"]["id"])
        return str(finalist["profile"]["id"])

    def run(self) -> dict[str, Any]:
        self.output.mkdir(parents=True, exist_ok=True)
        existing = [path for path in self.output.rglob("*") if path != self.output / "safety"]
        if existing:
            raise FileExistsError(f"output directory already contains run artifacts: {self.output}")
        self.guard.start()
        try:
            self.guarded_initial_unload()
            self.results["preflight_resources"] = memory_state()
            self.results["runtime"] = {
                "llama_server": str(LLAMA_SERVER),
                "llama_server_sha256": file_hash(LLAMA_SERVER),
                "embedding_model_sha256": file_hash(EMBED_MODEL),
                "reranker_model_sha256": file_hash(RERANK_MODEL),
            }
            if self.phase in {"all", "embedding"}:
                for profile in EMBED_PROFILES:
                    row = self.run_embedding_profile(profile)
                    self.results["embedding"].append(row)
                    json_dump(self.output / "results.json", self.results)
            if self.phase in {"all", "reranker"}:
                for profile in RERANK_PROFILES:
                    row = self.run_reranker_profile(profile)
                    self.results["reranker"].append(row)
                    json_dump(self.output / "results.json", self.results)
            self.results["validation"] = {"embedding": [], "reranker": []}
            self.results["winners"] = {}
            if self.results["embedding"]:
                fastest_embedding = self.winner(self.results["embedding"], "openwendy_batch8")
                embed_winner = self.embedding_winner(self.results["embedding"])
                self.results["validation"]["embedding"] = [
                    self.run_embedding_profile(dict(EMBED_PROFILES[0], id="embed-validation-current")),
                    self.run_embedding_profile(dict(embed_winner["profile"], id="embed-validation-finalist")),
                ]
                selected = self.validated_selection(
                    *self.results["validation"]["embedding"], "openwendy_batch8"
                )
                self.results["winners"].update(
                    embedding=(
                        EMBED_PROFILES[0]["id"]
                        if selected == "embed-validation-current"
                        else embed_winner["profile"]["id"]
                    ),
                    fastest_embedding=fastest_embedding["profile"]["id"],
                )
            if self.results["reranker"]:
                fastest_reranker = self.winner(self.results["reranker"], "openwendy_docs8")
                rerank_winner = self.reranker_winner(self.results["reranker"])
                self.results["validation"]["reranker"] = [
                    self.run_reranker_profile(dict(RERANK_PROFILES[0], id="rerank-validation-current")),
                    self.run_reranker_profile(dict(rerank_winner["profile"], id="rerank-validation-finalist")),
                ]
                selected = self.validated_selection(
                    *self.results["validation"]["reranker"], "openwendy_docs8"
                )
                self.results["winners"].update(
                    reranker=(
                        RERANK_PROFILES[0]["id"]
                        if selected == "rerank-validation-current"
                        else rerank_winner["profile"]["id"]
                    ),
                    fastest_reranker=fastest_reranker["profile"]["id"],
                )
            self.results["finished_utc"] = datetime.now(UTC).isoformat()
            self.results["final_resources"] = memory_state()
            self.guard.check("final-kernel-scan.log")
            json_dump(self.output / "results.json", self.results)
            return self.results
        except GpuSafetyError:
            self.safety_fault = True
            self.results["status"] = "aborted_safety_fault"
            self.results["finished_utc"] = datetime.now(UTC).isoformat()
            json_dump(self.output / "results.json", self.results)
            raise
        except BaseException as exc:
            self.results["status"] = "aborted_error"
            self.results["error_type"] = type(exc).__name__
            self.results["finished_utc"] = datetime.now(UTC).isoformat()
            json_dump(self.output / "results.json", self.results)
            raise
        finally:
            if self.process is not None:
                self.stop_server(gpu=self.process_gpu, profile_id=self.process_profile_id or "emergency-cleanup")
            try:
                if self.restore and not self.safety_fault:
                    try:
                        self.guarded_restore()
                    except GpuSafetyError:
                        self.safety_fault = True
                        self.stop_managed_stack_quietly()
                        raise
            finally:
                self.guard.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune the isolated embedding and reranker runtimes")
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS_ROOT / f"retrieval-runtime-{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cooldown", type=int, default=30)
    parser.add_argument("--no-restore", action="store_true")
    parser.add_argument("--phase", choices=("all", "embedding", "reranker"), default="all")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dry_run:
        print(json.dumps({"embedding": EMBED_PROFILES, "reranker": RERANK_PROFILES}, indent=2))
        return 0
    runner = RetrievalTuningRunner(
        args.output.resolve(),
        repeats=max(3, args.repeats),
        cooldown=max(30, args.cooldown),
        restore=not args.no_restore,
        phase=args.phase,
    )
    result = runner.run()
    print(json.dumps(result["winners"], indent=2))
    print(f"Results: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
