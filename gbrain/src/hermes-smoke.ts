import { randomUUID } from "node:crypto";

import { HermesWorker, createHermesJob, createOptimizationSuggestions } from "./hermes-runtime.js";
import { createDefaultHermesModelPolicy } from "./model-adapter.js";
import type { RunContract } from "./hermes-types.js";

function createSmokeRunContract(): RunContract {
  return {
    runId: randomUUID(),
    tenantId: "tenant-smoke",
    trigger: "manual_smoke",
    intent: "deep_research",
    runtimeTarget: "hermes",
    agentRole: "deep_research_agent",
    complexity: "deep",
    riskLevel: "medium",
    dataScope: {
      symbols: ["AAPL", "NVDA"],
    },
    memoryScope: {
      tenantId: "tenant-smoke",
      allowedMemoryTypes: [
        "preference",
        "lesson",
        "confirmed_rule",
        "research_summary",
        "session_summary",
        "broker_fact_ref",
        "task_summary",
      ],
      forbiddenMemoryTypes: ["other_tenant_memory", "unverified_research"],
    },
    modelPolicy: createDefaultHermesModelPolicy(30 * 60 * 1000),
    toolPolicy: {
      policyVersion: "v1",
      policyHash: "smoke-policy",
      allowedTools: ["research_artifacts.write", "market.quote.read"],
      forbiddenTools: ["broker.trade.place_order", "portfolio_positions.direct_update"],
    },
    createdAt: new Date().toISOString(),
  };
}

async function main(): Promise<void> {
  const worker = new HermesWorker();
  const job = createHermesJob({
    tenantId: "tenant-smoke",
    objective: "Smoke deep research",
    jobType: "deep_research",
    complexity: "deep",
  });
  const runContract = createSmokeRunContract();
  const result = await worker.run({
    job,
    runContract,
    userMessage: "生成一份 NVDA 深研 smoke report",
    contextInput: {
      businessFacts: [
        {
          refId: "quote-1",
          title: "Quote snapshot",
          summary: "NVDA quote fresh within 30 seconds.",
          priority: 10,
        },
      ],
      memoryResults: [
        {
          refId: "pref-1",
          title: "User preference",
          summary: "User prefers conservative entries and wants explicit risk summaries.",
          priority: 8,
        },
      ],
      sourceRefs: [
        {
          refId: "quote-1",
          refType: "business_fact",
          title: "Quote snapshot",
          summary: "NVDA quote fresh within 30 seconds.",
          trustLevel: "high",
        },
      ],
    },
    memoryWriteRequests: [
      {
        tenantId: "tenant-smoke",
        sourceJobId: job.id,
        title: "Risk summary preference",
        content: "Always include downside and discipline sections in deep reports.",
        kind: "preference",
        sourceLineage: [
          {
            refId: "chat-1",
            refType: "user_message",
            title: "user-request",
            summary: "User requested detailed risk summary.",
          },
        ],
      },
    ],
    optimizationSuggestions: createOptimizationSuggestions(job.id, "tenant-smoke"),
  });

  console.log(
    JSON.stringify(
      {
        ok: true,
        jobId: result.jobId,
        timeoutMs: result.timeoutMs,
        stages: result.stages.map((stage) => stage.stage),
        artifacts: result.writeEnvelope.artifacts.map((artifact) => ({
          artifactId: artifact.artifactId,
          artifactType: artifact.artifactType,
          storageUri: artifact.storageUri,
        })),
        memoryCandidates: result.writeEnvelope.memoryCandidates.length,
        pendingConfirmations: result.writeEnvelope.pendingConfirmations.length,
        optimizationProposals: result.writeEnvelope.optimizationProposals.length,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error("[hermes-smoke] failed", error);
  process.exit(1);
});
