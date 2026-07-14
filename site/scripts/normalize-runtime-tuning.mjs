#!/usr/bin/env node

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const defaultSource = resolve(
  "../benchmarks/summaries/tuning_v1/qwen36-runtime-tuning-20260714/summary.json",
);
const source = resolve(process.argv[2] || defaultSource);
const destination = resolve(process.argv[3] || "data/runtime-tuning-v1.json");
const raw = JSON.parse(await readFile(source, "utf8"));

if (raw.schema_version !== "runtime-tuning-campaign-v1.0") {
  throw new Error(`Unsupported runtime tuning schema: ${raw.schema_version}`);
}

const labels = {
  "qwen27-huihui": ["Qwen 3.6 27B", "Huihui", "27B dense"],
  "qwen27-unsloth": ["Qwen 3.6 27B", "Unsloth", "27B dense"],
  "qwen35-huihui": ["Qwen 3.6 35B A3B", "Huihui", "35B MoE · 3B active"],
  "qwen35-unsloth": ["Qwen 3.6 35B A3B", "Unsloth", "35B MoE · 3B active"],
};
const order = Object.keys(labels);
const validationByModel = Object.fromEntries(raw.barrage.map((entry) => [entry.model_id, entry]));
const agentHarnessSource = Object.values(raw).find(
  (value) => value && !Array.isArray(value) && value.arms && value.decision && value.safety,
);
const percentChange = (a, b) => Number(((a / b - 1) * 100).toFixed(1));

const models = raw.models
  .map((entry) => {
    const [name, build, family] = labels[entry.model_id] || [entry.model_id, "Unknown", "Unknown"];
    const validation = validationByModel[entry.model_id];
    return {
      id: entry.model_id,
      name,
      build,
      family,
      quant: entry.profile.model.match(/Q\d+_[A-Z0-9_]+/)?.[0] || "unknown",
      profile: {
        context: entry.profile.context,
        batch: entry.profile.batch,
        ubatch: entry.profile.ubatch,
        threads: entry.profile.threads,
        threadsBatch: entry.profile.threads_batch,
        checkpoints: entry.profile.checkpoints,
        speculation: entry.profile.spec_type,
        mtpN: entry.profile.mtp_n,
      },
      metrics: {
        longPrompt: entry.metrics.cold_pp_long.prompt_per_second,
        shortPrompt: entry.metrics.cold_pp_short.prompt_per_second,
        contextRecallPrompt: entry.metrics.context_recall.prompt_per_second,
        contextRecallGeneration: entry.metrics.context_recall.predicted_per_second,
        deterministicGeneration: entry.metrics.deterministic_tg.predicted_per_second,
        sampledGeneration: entry.metrics.sampled_agent_tg.predicted_per_second,
        toolGeneration: entry.metrics.structured_tool_tg.predicted_per_second,
        warmAppendPrompt: entry.metrics.warm_append.prompt_per_second,
        warmAppendCacheTokens: entry.metrics.warm_append.cache_n,
        deterministicAcceptance: entry.metrics.deterministic_tg.speculation_acceptance,
        sampledAcceptance: entry.metrics.sampled_agent_tg.speculation_acceptance,
      },
      validation: {
        status: validation.status,
        performance: {
          rawPassed: validation.performance.raw_passed,
          derivedPassed: validation.performance.derived_passed,
          total: validation.performance.total,
          correction: validation.performance.grading_note || null,
        },
        tools: validation.tool_contract,
        vision: validation.vision,
      },
    };
  })
  .sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));

const byId = Object.fromEntries(models.map((model) => [model.id, model]));
const q27Huihui = byId["qwen27-huihui"];
const q27Unsloth = byId["qwen27-unsloth"];
const q35Huihui = byId["qwen35-huihui"];
const q35Unsloth = byId["qwen35-unsloth"];

const result = {
  schemaVersion: "site-runtime-tuning-v1",
  source: {
    schemaVersion: raw.schema_version,
    label: raw.label,
    generatedAt: raw.generated_at,
  },
  interpretation: {
    title: "Runtime tuning · retained profiles",
    warning:
      "Each model used its own retained context and runtime shape. These measurements explain deployment choices; they are not a fair-profile model ranking.",
    scope:
      "This campaign validated direct performance, cache behavior, tools, and vision. Sandbox and concurrency were not rerun.",
  },
  integrity: {
    validMeasurements: raw.direct.passed,
    attemptedMeasurements: raw.direct.trials,
    expectedStartupFailures: raw.direct.expected_failures,
    controlPassed: raw.controls.passed,
    controlTrials: raw.controls.trials,
    excludedRuns: raw.excluded.length,
    excludedReasons: ["Wrong model filename; preflight only", "Lock-interrupted startup only"],
  },
  models,
  findings: [
    {
      title: "27B Huihui favors generation",
      detail: `Against the retained 27B Unsloth shape: ${percentChange(q27Huihui.metrics.deterministicGeneration, q27Unsloth.metrics.deterministicGeneration)}% deterministic TG, ${percentChange(q27Huihui.metrics.sampledGeneration, q27Unsloth.metrics.sampledGeneration)}% sampled TG, and ${percentChange(q27Huihui.metrics.toolGeneration, q27Unsloth.metrics.toolGeneration)}% tool TG. Long PP is within 1%.`,
    },
    {
      title: "35B Unsloth is the throughput profile",
      detail: `${percentChange(q35Unsloth.metrics.longPrompt, q35Huihui.metrics.longPrompt)}% faster long PP and ${percentChange(q35Unsloth.metrics.sampledGeneration, q35Huihui.metrics.sampledGeneration)}% faster sampled TG than the retained 35B Huihui shape. It runs without MTP.`,
    },
    {
      title: "35B Huihui is the context profile",
      detail: `Retained at ${q35Huihui.profile.context.toLocaleString("en-US")} context with draft-MTP n${q35Huihui.profile.mtpN}; the largest context in this campaign.`,
    },
  ],
  agentHarness: {
    arms: agentHarnessSource.arms.map((arm) => ({
      id: arm.arm,
      label: arm.arm === "current" ? "Current" : "Finalist",
      taskPassed: arm.task_passed,
      taskTotal: arm.task_total,
      repeats: arm.repeats,
      medianElapsedSeconds: arm.median_elapsed_seconds,
    })),
    selectedShape: agentHarnessSource.decision.selected_shape,
    selectedArm: agentHarnessSource.decision.selected_arm,
    decisionReason: agentHarnessSource.decision.reason,
    finalistElapsedChangePercent: agentHarnessSource.finalist_elapsed_change_percent,
    commonFinding:
      "Both arms made every expected calculation tool call with correct arguments and output, but completed those tasks with an empty final answer.",
    safety: {
      completedRuns: agentHarnessSource.safety.completed_runs,
      restored: agentHarnessSource.safety.restored,
      safetyFault: agentHarnessSource.safety.safety_fault,
    },
  },
};

await mkdir(dirname(destination), { recursive: true });
await writeFile(destination, `${JSON.stringify(result, null, 2)}\n`);
console.log(`Normalized ${models.length} tuned profiles from ${source} to ${destination}`);
