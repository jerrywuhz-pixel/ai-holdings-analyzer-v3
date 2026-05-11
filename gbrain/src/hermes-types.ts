import type { ModelResponse } from "./model-adapter.js";

export type HermesRuntimeTarget = "openclaw_side" | "hermes" | "domain_worker";
export type HermesJobType =
  | "deep_research"
  | "equity_analysis"
  | "options_sell_put"
  | "portfolio_review"
  | "memory_curate"
  | "ops_diagnostic";
export type HermesComplexity = "quick" | "standard" | "deep" | "background";
export type HermesStage = "queued" | "collecting" | "analyzing" | "reviewing" | "ready" | "failed";
export type HermesJobStatus = "pending" | "running" | "waiting_tool" | "succeeded" | "failed" | "cancelled";
export type ModelProviderId = "minimax" | "openai" | "fallback-template";
export type MemoryKind =
  | "preference"
  | "lesson"
  | "confirmed_rule"
  | "research_summary"
  | "session_summary"
  | "broker_fact_ref"
  | "task_summary";
export type MemoryWriteDisposition = "memory_candidate" | "pending_confirmation" | "proposal" | "rejected";
export type OptimizationKind =
  | "prompt"
  | "playbook"
  | "tool_usage"
  | "analysis_output"
  | "report_template"
  | "trade_execution"
  | "strategy_parameter"
  | "risk_rule"
  | "source_policy";
export type ArtifactType =
  | "deep_research_report"
  | "sell_put_report"
  | "portfolio_review"
  | "ops_diagnostic"
  | "weekly_optimization_confirmation";
export type WriteArtifactKind = "artifact" | "optimization_proposal" | "pending_confirmation" | "memory_candidate";

export interface ToolPolicy {
  policyVersion: string;
  policyHash: string;
  allowedTools: string[];
  forbiddenTools: string[];
}

export interface MemoryScopePolicy {
  tenantId: string;
  allowedMemoryTypes: MemoryKind[];
  forbiddenMemoryTypes: string[];
}

export interface ModelRoute {
  provider: ModelProviderId;
  model: string;
  mode?: "stub" | "live";
  timeoutMs?: number;
}

export interface ModelBudget {
  maxCostUsd?: number;
  quotaType?: string;
}

export interface ModelPolicy {
  primary: ModelRoute;
  fallbacks: ModelRoute[];
  budgetLimit?: ModelBudget;
}

export interface DataScope {
  portfolioViewId?: string;
  followViewId?: string;
  brokerConnectionIds?: string[];
  symbols?: string[];
}

export interface RunContract {
  runId: string;
  tenantId: string;
  channelBindingId?: string;
  openclawAccountId?: string;
  sessionSpace?: string;
  trigger: string;
  intent: string;
  runtimeTarget: HermesRuntimeTarget;
  agentRole: string;
  complexity: HermesComplexity;
  riskLevel: "low" | "medium" | "high" | "admin";
  dataScope: DataScope;
  memoryScope: MemoryScopePolicy;
  modelPolicy: ModelPolicy;
  toolPolicy: ToolPolicy;
  createdAt: string;
}

export interface ContextSourceRef {
  refId: string;
  refType: "business_fact" | "memory" | "session_summary" | "user_message" | "artifact" | "tool_result";
  title: string;
  summary: string;
  freshnessAt?: string;
  trustLevel?: "high" | "medium" | "low";
  hash?: string;
  uri?: string;
}

export interface ContextSnippet {
  refId: string;
  title: string;
  summary: string;
  body?: string;
  priority?: number;
  freshnessAt?: string;
}

export interface ContextPackBuildInput {
  runContract: RunContract;
  userMessage: string;
  sessionSummary?: string;
  businessFacts?: ContextSnippet[];
  memoryResults?: ContextSnippet[];
  artifacts?: ContextSnippet[];
  sourceRefs?: ContextSourceRef[];
  tokenBudget?: number;
  trimStrategy?: "balanced" | "facts_first" | "memory_first";
}

export interface ContextPack {
  contextPackId: string;
  runId: string;
  tenantId: string;
  tokenBudget: number;
  estimatedTokens: number;
  trimStrategy: string;
  createdAt: string;
  sourceRefs: ContextSourceRef[];
  renderedPrompt: string;
  sections: Array<{
    label: string;
    items: string[];
    truncated: boolean;
  }>;
  sourceHash: string;
}

export interface ArtifactDraft {
  tenantId: string;
  artifactType: ArtifactType;
  ownerRunId: string;
  ownerAgent: string;
  modelId: string;
  sourceRefs: ContextSourceRef[];
  title: string;
  content: string;
  metadata?: Record<string, unknown>;
  retentionClass?: "short" | "standard" | "long";
  expiresAt?: string;
  createdByAgent?: string;
}

export interface ArtifactRegistryRecord extends ArtifactDraft {
  artifactId: string;
  storageUri: string;
  contentHash: string;
  createdAt: string;
}

export interface OptimizationSuggestion {
  tenantId: string;
  sourceJobId: string;
  suggestionId?: string;
  proposalType: OptimizationKind;
  title: string;
  rationale: string;
  currentVersion?: string;
  proposedVersion?: string;
  riskLevel: "low" | "medium" | "high";
  requiresHumanConfirmation?: boolean;
  metadata?: Record<string, unknown>;
}

export interface OptimizationProposalDraft {
  kind: "optimization_proposal";
  proposalId: string;
  tenantId: string | null;
  proposalType: OptimizationKind;
  sourceJobId: string;
  currentVersion?: string;
  proposedVersion?: string;
  rationale: string;
  evalResult?: Record<string, unknown>;
  riskLevel: "low" | "medium" | "high";
  approvalStatus: "proposed" | "auto_applied" | "needs_review";
  title: string;
  createdAt: string;
  metadata: Record<string, unknown>;
}

export interface PendingConfirmationDraft {
  kind: "pending_confirmation";
  confirmationId: string;
  tenantId: string;
  confirmationType: "memory_rule_upgrade" | "trade_execution_optimization" | "strategy_parameter_change";
  title: string;
  reason: string;
  payload: Record<string, unknown>;
  sourceJobId: string;
  createdAt: string;
}

export interface MemoryWriteRequest {
  tenantId: string;
  sourceJobId: string;
  title: string;
  content: string;
  kind: MemoryKind;
  sourceLineage: ContextSourceRef[];
  evidenceRefs?: string[];
  confidenceLevel?: "high" | "medium" | "low";
  tags?: string[];
  referencesBusinessFactsOnly?: boolean;
  assertsBusinessFact?: boolean;
  containsCrossTenantData?: boolean;
  containsSecret?: boolean;
  requestedPromotion?: "candidate_only" | "confirmed_rule";
}

export interface MemoryCandidateRecord {
  kind: "memory_candidate";
  candidateId: string;
  tenantId: string;
  sourceJobId: string;
  title: string;
  content: string;
  memoryKind: MemoryKind;
  status: "candidate";
  confidenceLevel: "high" | "medium" | "low";
  sourceLineage: ContextSourceRef[];
  evidenceRefs: string[];
  metadata: Record<string, unknown>;
  createdAt: string;
}

export interface MemoryWriteDecision {
  disposition: MemoryWriteDisposition;
  reason: string;
  candidate?: MemoryCandidateRecord;
  pendingConfirmation?: PendingConfirmationDraft;
  proposal?: OptimizationProposalDraft;
}

export interface WeeklyOptimizationDigest {
  weekKey: string;
  autoApplied: OptimizationProposalDraft[];
  reviewRequired: OptimizationProposalDraft[];
  pendingConfirmations: PendingConfirmationDraft[];
  summaryArtifactDraft?: ArtifactDraft;
}

export interface HermesJob {
  id: string;
  tenantId: string;
  sourceRunId?: string;
  channelBindingId?: string;
  openclawAccountId?: string;
  jobType: HermesJobType;
  objective: string;
  complexity: HermesComplexity;
  status: HermesJobStatus;
  toolPolicy: ToolPolicy;
  modelPolicy: ModelPolicy;
  createdAt: string;
}

export interface HermesWritableEnvelope {
  artifacts: ArtifactRegistryRecord[];
  optimizationProposals: OptimizationProposalDraft[];
  pendingConfirmations: PendingConfirmationDraft[];
  memoryCandidates: MemoryCandidateRecord[];
}

export interface HermesJobRunInput {
  job: HermesJob;
  runContract: RunContract;
  userMessage: string;
  contextInput: Omit<ContextPackBuildInput, "runContract" | "userMessage">;
  artifactType?: ArtifactType;
  artifactTitle?: string;
  memoryWriteRequests?: MemoryWriteRequest[];
  optimizationSuggestions?: OptimizationSuggestion[];
}

export interface HermesJobRunResult {
  jobId: string;
  status: HermesJobStatus;
  timeoutMs: number;
  stages: Array<{ stage: HermesStage; at: string }>;
  contextPack: ContextPack;
  modelResponse: ModelResponse;
  writeEnvelope: HermesWritableEnvelope;
  weeklyOptimizationDigest: WeeklyOptimizationDigest;
}
