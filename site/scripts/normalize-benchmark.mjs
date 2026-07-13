#!/usr/bin/env node

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";

const defaultSource = resolve(
  "../benchmarks/summaries/barrage_v2/qwen36-four-model-release-20260712T185403Z/summary.json",
);
const source = resolve(process.argv[2] || defaultSource);
const destination = resolve(process.argv[3] || "data/barrage-v2.json");
const raw = JSON.parse(await readFile(source, "utf8"));
const publishedEnvironment = raw.candidates[0]?.environment || {};
const serverMatch = publishedEnvironment.server_version?.match(/version:\s*(\d+)\s+\(([^)]+)\)/);
const driverMatch = publishedEnvironment.gpu?.driver?.match(/Driver version:\s*([^\n]+)/);

const labels = {
  "qwen27-huihui": ["Qwen 3.6 27B", "Huihui", "27B dense"],
  "qwen27-unsloth": ["Qwen 3.6 27B", "Unsloth", "27B dense"],
  "qwen35-huihui": ["Qwen 3.6 35B A3B", "Huihui", "35B MoE · 3B active"],
  "qwen35-unsloth": ["Qwen 3.6 35B A3B", "Unsloth", "35B MoE · 3B active"],
};

const stat = (value) => ({
  median: value?.median ?? null,
  mean: value?.mean ?? null,
  p95: value?.p95 ?? null,
  min: value?.min ?? null,
  max: value?.max ?? null,
  stdev: value?.stdev ?? null,
  count: value?.count ?? 0,
});

const result = {
  schemaVersion: "site-benchmark-v1",
  source: {
    schemaVersion: raw.schema_version,
    label: raw.label,
    digest: raw.digest,
    file: basename(source),
  },
  interpretation: {
    title: "Barrage V2 · four-model release run",
    releaseMeaning:
      "A failed release gate means the model missed at least one strict requirement; it does not mean the run crashed.",
    finding:
      "All four models completed performance, cache, tool, concurrency, and vision checks. Sandbox acceptance prevented release qualification for every candidate.",
    separation:
      "Performance, tools, sandbox, concurrency, vision, and bespoke agent-harness evaluations are separate evidence families. No composite score is calculated.",
  },
  testStack: {
    hardware: {
      gpu: "AMD AI Pro R9700",
      gpuMemoryGb: 32,
      cpu: null,
      systemMemoryGb: null,
      source: "BENCHMARK_RESULTS.md",
    },
    runtime: {
      name: "llama.cpp",
      build: serverMatch?.[1] || null,
      commit: serverMatch?.[2] || null,
      backend: publishedEnvironment.runtime_backend || null,
      gpuProbe: publishedEnvironment.gpu?.backend || null,
      gpuDriver: driverMatch?.[1]?.trim() || null,
      platform: publishedEnvironment.platform || null,
      compiler: publishedEnvironment.server_version?.match(/built with ([^\n]+)/)?.[1] || null,
      source: "summary.json",
    },
  },
  models: raw.candidates.map((candidate) => {
    const performance = candidate.performance?.summary || {};
    const [name, build, family] = labels[candidate.model] || [candidate.model, "Unknown", "Unknown"];
    return {
      id: candidate.model,
      name,
      build,
      family,
      quant: candidate.environment.model.path.match(/Q\d+_[A-Z0-9_]+/)?.[0] || "unknown",
      generatedAt: candidate.generated_at,
      status: candidate.status,
      modelSizeGb: Number((candidate.environment.model.size_bytes / 1e9).toFixed(1)),
      profile: candidate.profile,
      evaluation: candidate.evaluation,
      release: {
        requested: candidate.release_gate.requested,
        eligible: candidate.release_gate.eligible,
        passed: candidate.release_gate.passed,
        checks: candidate.release_gate.checks.map(({ check, passed }) => ({ check, passed })),
      },
      performance: {
        status: candidate.performance.status,
        directGeneration: stat(performance.direct_tg?.predicted_per_second),
        agentGeneration: stat(performance.agent_stream?.predicted_per_second),
        agentTtft: stat(performance.agent_stream?.ttft_seconds),
        referenceAgent: stat(performance.reference_agent_loop?.agent_predicted_per_second),
        coldPrompt: stat(performance.cold_pp_short?.prompt_per_second),
        contextRecall: ["8k", "32k", "64k", "120k"].map((context) => ({
          context,
          promptTokens: stat(performance[`context_recall_${context}`]?.agent_prompt_n).median,
          promptPerSecond: stat(performance[`context_recall_${context}`]?.prompt_per_second),
          reliability: performance[`context_recall_${context}`]?.reliability,
        })),
        warmAppend: ["8k", "32k"].map((context) => ({
          context,
          cacheTokens: stat(performance[`warm_append_${context}`]?.cache_n).median,
          promptPerSecond: stat(performance[`warm_append_${context}`]?.prompt_per_second),
          reliability: performance[`warm_append_${context}`]?.reliability,
        })),
      },
      tools: {
        status: candidate.tool_contract.status,
        passed: candidate.tool_contract.passed,
        total: candidate.tool_contract.total,
        splits: candidate.tool_contract.splits,
        tasks: candidate.tool_contract.reliability,
      },
      sandbox: {
        status: candidate.sandbox.status,
        passed: candidate.sandbox.passed,
        total: candidate.sandbox.total,
        splits: candidate.sandbox.splits,
        tasks: candidate.sandbox.reliability,
      },
      concurrency: candidate.concurrency,
      vision: candidate.vision,
      notes:
        candidate.model === "qwen35-huihui"
          ? ["One malformed tool call was retained as an HTTP 500 in the run evidence."]
          : [],
    };
  }),
};

await mkdir(dirname(destination), { recursive: true });
await writeFile(destination, `${JSON.stringify(result, null, 2)}\n`);
console.log(`Normalized ${result.models.length} models from ${source} to ${destination}`);
