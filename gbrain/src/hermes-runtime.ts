import { randomUUID } from "node:crypto";

import type {
  ArtifactDraft,
  ArtifactRegistryRecord,
  HermesComplexity,
  HermesJob,
  HermesJobRunInput,
  HermesJobRunResult,
  HermesStage,
  HermesWritableEnvelope,
  OptimizationSuggestion,
} from "./hermes-types.js";
import { ArtifactRegistryWriterClient } from "./hermes-artifact-registry.js";
import { ContextPackBuilder } from "./hermes-context-pack.js";
import { MemoryWriteGate } from "./hermes-memory-gate.js";
import { WeeklyOptimizationConfirmationProposalGenerator } from "./hermes-optimization.js";
import { buildDefaultModelAdapter, createDefaultHermesModelPolicy, type ModelAdapter, type ModelResponse } from "./model-adapter.js";

function nowIso(): string {
  return new Date().toISOString();
}

function stageRecord(stage: HermesStage): { stage: HermesStage; at: string } {
  return { stage, at: nowIso() };
}

function resolveTimeoutMs(complexity: HermesComplexity): number {
  return complexity === "deep" ? 30 * 60 * 1000 : 5 * 60 * 1000;
}

function buildArtifactDraft(
  input: HermesJobRunInput,
  content: string,
  artifactType: ArtifactDraft["artifactType"],
  modelResponse: ModelResponse,
): ArtifactDraft {
  const sourceRunId = input.job.sourceRunId ?? input.runContract.runId ?? input.job.id;

  return {
    tenantId: input.runContract.tenantId,
    artifactType,
    ownerRunId: sourceRunId,
    ownerAgent: "hermes",
    modelId: modelResponse.model,
    sourceRefs: input.contextInput.sourceRefs ?? [],
    title: input.artifactTitle ?? `${input.job.jobType}-${input.job.id}`,
    content,
    metadata: {
      tenant_id: input.runContract.tenantId,
      artifact_type: artifactType,
      objective: input.job.objective,
      job_id: input.job.id,
      source_run_id: sourceRunId,
      model_id: modelResponse.model,
      model_provider: modelResponse.provider,
      lineage: input.contextInput.sourceRefs ?? [],
      source_refs: input.contextInput.sourceRefs ?? [],
      run_contract_id: input.runContract.runId,
      tool_policy_hash: input.runContract.toolPolicy.policyHash,
      context_pack_scope: input.runContract.memoryScope.allowedMemoryTypes,
    },
    retentionClass: "standard",
  };
}

function combinePendingConfirmations(
  memoryConfirmations: HermesWritableEnvelope["pendingConfirmations"],
  optimizationConfirmations: HermesWritableEnvelope["pendingConfirmations"],
) {
  return [...memoryConfirmations, ...optimizationConfirmations];
}

function assertWritableEnvelope(envelope: HermesWritableEnvelope): void {
  const forbidden = ["facts", "positions", "tradeEvents", "portfolioPositions"];
  for (const key of Object.keys(envelope)) {
    if (forbidden.includes(key)) {
      throw new Error(`Hermes writable envelope contains forbidden key: ${key}`);
    }
  }
}

export class HermesWorker {
  constructor(
    private readonly modelAdapter: ModelAdapter = buildDefaultModelAdapter(),
    private readonly contextPackBuilder = new ContextPackBuilder(),
    private readonly memoryWriteGate = new MemoryWriteGate(),
    private readonly artifactRegistry = new ArtifactRegistryWriterClient(),
    private readonly weeklyOptimizer = new WeeklyOptimizationConfirmationProposalGenerator(),
  ) {}

  async run(input: HermesJobRunInput): Promise<HermesJobRunResult> {
    const timeoutMs = resolveTimeoutMs(input.job.complexity);
    const stages = [stageRecord("queued"), stageRecord("collecting")];
    const contextPack = this.contextPackBuilder.build({
      ...input.contextInput,
      runContract: input.runContract,
      userMessage: input.userMessage,
      tokenBudget: input.contextInput.tokenBudget ?? (input.job.complexity === "deep" ? 3_200 : 1_600),
    });

    stages.push(stageRecord("analyzing"));
    const modelPolicy =
      input.runContract.modelPolicy.primary.model !== ""
        ? input.runContract.modelPolicy
        : createDefaultHermesModelPolicy(timeoutMs, input.job.complexity);

    const modelResponse = await this.modelAdapter.generate(modelPolicy, {
      objective: input.job.objective,
      systemPrompt: `Hermes worker for ${input.job.jobType}. Never write business facts directly.`,
      prompt: contextPack.renderedPrompt,
      contextPack,
    });

    stages.push(stageRecord("reviewing"));
    const artifactType = input.artifactType ?? (input.job.jobType === "options_sell_put" ? "sell_put_report" : "deep_research_report");
    const artifactContent = [
      `# ${input.artifactTitle ?? input.job.objective}`,
      "",
      `Job: ${input.job.jobType}`,
      `Complexity: ${input.job.complexity}`,
      `Model: ${modelResponse.provider}/${modelResponse.model}`,
      `Context Pack: ${contextPack.contextPackId}`,
      "",
      modelResponse.text,
    ].join("\n");
    const artifact = await this.artifactRegistry.register(buildArtifactDraft(input, artifactContent, artifactType, modelResponse));

    const memoryDecisions = this.memoryWriteGate.evaluateMany(input.runContract, input.memoryWriteRequests ?? []);
    const memoryCandidates = memoryDecisions.flatMap((decision) => (decision.candidate ? [decision.candidate] : []));
    const memoryConfirmations = memoryDecisions.flatMap((decision) =>
      decision.pendingConfirmation ? [decision.pendingConfirmation] : [],
    );

    const weeklyDigest = this.weeklyOptimizer.generate(input.optimizationSuggestions ?? []);
    let artifacts: ArtifactRegistryRecord[] = [artifact];
    if (weeklyDigest.summaryArtifactDraft) {
      artifacts = [...artifacts, await this.artifactRegistry.register(weeklyDigest.summaryArtifactDraft)];
    }

    const writeEnvelope: HermesWritableEnvelope = {
      artifacts,
      optimizationProposals: [...weeklyDigest.autoApplied, ...weeklyDigest.reviewRequired],
      pendingConfirmations: combinePendingConfirmations(memoryConfirmations, weeklyDigest.pendingConfirmations),
      memoryCandidates,
    };
    assertWritableEnvelope(writeEnvelope);
    stages.push(stageRecord("ready"));

    return {
      jobId: input.job.id,
      status: "succeeded",
      timeoutMs,
      stages,
      contextPack,
      modelResponse,
      writeEnvelope,
      weeklyOptimizationDigest: weeklyDigest,
    };
  }
}

export function createHermesJob(overrides: Partial<HermesJob> = {}): HermesJob {
  const complexity = overrides.complexity ?? "deep";
  return {
    id: overrides.id ?? randomUUID(),
    tenantId: overrides.tenantId ?? "tenant-demo",
    jobType: overrides.jobType ?? "deep_research",
    objective: overrides.objective ?? "Deep research",
    complexity,
    status: overrides.status ?? "pending",
    toolPolicy: overrides.toolPolicy ?? {
      policyVersion: "v1",
      policyHash: "stub-policy",
      allowedTools: ["research_artifacts.write", "market.quote.read"],
      forbiddenTools: ["broker.trade.place_order", "portfolio_positions.direct_update"],
    },
    modelPolicy: overrides.modelPolicy ?? createDefaultHermesModelPolicy(resolveTimeoutMs(complexity), complexity),
    createdAt: overrides.createdAt ?? nowIso(),
    sourceRunId: overrides.sourceRunId,
    channelBindingId: overrides.channelBindingId,
    openclawAccountId: overrides.openclawAccountId,
  };
}

export function createOptimizationSuggestions(jobId: string, tenantId: string): OptimizationSuggestion[] {
  return [
    {
      tenantId,
      sourceJobId: jobId,
      proposalType: "analysis_output",
      title: "Tighten risk-summary wording",
      rationale: "Daily reports can shorten boilerplate without affecting trading behavior.",
      riskLevel: "low",
    },
    {
      tenantId,
      sourceJobId: jobId,
      proposalType: "trade_execution",
      title: "Revise weekly execution checklist ordering",
      rationale: "Execution ordering changes trade behavior and must be confirmed weekly.",
      riskLevel: "high",
      requiresHumanConfirmation: true,
    },
  ];
}
