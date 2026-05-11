import { randomUUID } from "node:crypto";

import type {
  ArtifactDraft,
  OptimizationKind,
  OptimizationProposalDraft,
  OptimizationSuggestion,
  PendingConfirmationDraft,
  WeeklyOptimizationDigest,
} from "./hermes-types.js";

const AUTO_APPLY_TYPES: ReadonlySet<OptimizationKind> = new Set([
  "prompt",
  "playbook",
  "tool_usage",
  "analysis_output",
  "report_template",
]);

function weekKey(now: Date): string {
  const copy = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const day = copy.getUTCDay() || 7;
  copy.setUTCDate(copy.getUTCDate() - day + 1);
  return copy.toISOString().slice(0, 10);
}

function toProposal(suggestion: OptimizationSuggestion): OptimizationProposalDraft {
  const autoApply = AUTO_APPLY_TYPES.has(suggestion.proposalType) && !suggestion.requiresHumanConfirmation;
  return {
    kind: "optimization_proposal",
    proposalId: suggestion.suggestionId ?? randomUUID(),
    tenantId: suggestion.tenantId,
    proposalType: suggestion.proposalType,
    sourceJobId: suggestion.sourceJobId,
    currentVersion: suggestion.currentVersion,
    proposedVersion: suggestion.proposedVersion,
    rationale: suggestion.rationale,
    riskLevel: suggestion.riskLevel,
    approvalStatus: autoApply ? "auto_applied" : "needs_review",
    title: suggestion.title,
    createdAt: new Date().toISOString(),
    metadata: suggestion.metadata ?? {},
  };
}

function toPendingConfirmation(weekStart: string, proposal: OptimizationProposalDraft): PendingConfirmationDraft {
  return {
    kind: "pending_confirmation",
    confirmationId: randomUUID(),
    tenantId: proposal.tenantId ?? "platform",
    confirmationType: proposal.proposalType === "trade_execution" ? "trade_execution_optimization" : "strategy_parameter_change",
    title: `[Weekly Review] ${proposal.title}`,
    reason: "Trading execution or strategy-affecting optimization requires manual confirmation before activation.",
    payload: {
      week_start: weekStart,
      proposal_id: proposal.proposalId,
      proposal_type: proposal.proposalType,
      rationale: proposal.rationale,
      metadata: proposal.metadata,
    },
    sourceJobId: proposal.sourceJobId,
    createdAt: new Date().toISOString(),
  };
}

function buildSummaryArtifact(weekStart: string, reviewRequired: OptimizationProposalDraft[]): ArtifactDraft | undefined {
  if (reviewRequired.length === 0) {
    return undefined;
  }

  const lines = [
    `# Weekly Optimization Confirmation - ${weekStart}`,
    "",
    "The following execution-affecting optimizations require manual confirmation:",
    "",
    ...reviewRequired.map((proposal, index) => `${index + 1}. ${proposal.title} (${proposal.proposalType}) - ${proposal.rationale}`),
  ];

  return {
    tenantId: reviewRequired[0].tenantId ?? "platform",
    artifactType: "weekly_optimization_confirmation",
    ownerRunId: reviewRequired[0].sourceJobId,
    ownerAgent: "hermes",
    modelId: "optimizer",
    sourceRefs: [],
    title: `weekly-optimization-confirmation-${weekStart}`,
    content: lines.join("\n"),
    retentionClass: "standard",
  };
}

export class WeeklyOptimizationConfirmationProposalGenerator {
  generate(suggestions: OptimizationSuggestion[]): WeeklyOptimizationDigest {
    const start = new Date();
    const currentWeekKey = weekKey(start);
    const proposals = suggestions.map(toProposal);
    const autoApplied = proposals.filter((proposal) => proposal.approvalStatus === "auto_applied");
    const reviewRequired = proposals.filter((proposal) => proposal.approvalStatus !== "auto_applied");
    const pendingConfirmations = reviewRequired.map((proposal) => toPendingConfirmation(currentWeekKey, proposal));

    return {
      weekKey: currentWeekKey,
      autoApplied,
      reviewRequired,
      pendingConfirmations,
      summaryArtifactDraft: buildSummaryArtifact(currentWeekKey, reviewRequired),
    };
  }
}
