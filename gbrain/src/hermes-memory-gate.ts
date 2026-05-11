import { randomUUID } from "node:crypto";

import type {
  MemoryCandidateRecord,
  MemoryKind,
  MemoryWriteDecision,
  MemoryWriteRequest,
  PendingConfirmationDraft,
  RunContract,
} from "./hermes-types.js";

const AUTO_CANDIDATE_KINDS: ReadonlySet<MemoryKind> = new Set([
  "preference",
  "research_summary",
  "session_summary",
  "broker_fact_ref",
  "task_summary",
]);

const CONFIRMATION_KINDS: ReadonlySet<MemoryKind> = new Set(["lesson", "confirmed_rule"]);

function buildPendingConfirmation(request: MemoryWriteRequest, reason: string): PendingConfirmationDraft {
  return {
    kind: "pending_confirmation",
    confirmationId: randomUUID(),
    tenantId: request.tenantId,
    confirmationType: request.kind === "confirmed_rule" ? "memory_rule_upgrade" : "strategy_parameter_change",
    title: request.title,
    reason,
    payload: {
      requested_kind: request.kind,
      requested_promotion: request.requestedPromotion ?? "candidate_only",
      source_lineage: request.sourceLineage,
      evidence_refs: request.evidenceRefs ?? [],
      content: request.content,
    },
    sourceJobId: request.sourceJobId,
    createdAt: new Date().toISOString(),
  };
}

function buildCandidate(request: MemoryWriteRequest): MemoryCandidateRecord {
  return {
    kind: "memory_candidate",
    candidateId: randomUUID(),
    tenantId: request.tenantId,
    sourceJobId: request.sourceJobId,
    title: request.title,
    content: request.content,
    memoryKind: request.kind,
    status: "candidate",
    confidenceLevel: request.confidenceLevel ?? "medium",
    sourceLineage: request.sourceLineage,
    evidenceRefs: request.evidenceRefs ?? [],
    metadata: {
      tags: request.tags ?? [],
      requested_promotion: request.requestedPromotion ?? "candidate_only",
    },
    createdAt: new Date().toISOString(),
  };
}

export class MemoryWriteGate {
  evaluate(runContract: RunContract, request: MemoryWriteRequest): MemoryWriteDecision {
    if (request.tenantId !== runContract.tenantId) {
      return {
        disposition: "rejected",
        reason: "tenant_mismatch",
      };
    }

    if (request.containsCrossTenantData) {
      return {
        disposition: "rejected",
        reason: "cross_tenant_data_forbidden",
      };
    }

    if (request.containsSecret) {
      return {
        disposition: "rejected",
        reason: "secret_material_forbidden",
      };
    }

    if (request.assertsBusinessFact) {
      return {
        disposition: "rejected",
        reason: "hermes_cannot_write_business_facts",
      };
    }

    if (request.sourceLineage.length === 0) {
      return {
        disposition: "rejected",
        reason: "source_lineage_required",
      };
    }

    if (!runContract.memoryScope.allowedMemoryTypes.includes(request.kind)) {
      return {
        disposition: "rejected",
        reason: "memory_kind_not_allowed_by_run_contract",
      };
    }

    if (request.kind === "broker_fact_ref" && !request.referencesBusinessFactsOnly) {
      return {
        disposition: "rejected",
        reason: "broker_fact_ref_must_store_reference_only",
      };
    }

    if (CONFIRMATION_KINDS.has(request.kind) || request.requestedPromotion === "confirmed_rule") {
      const pendingConfirmation = buildPendingConfirmation(
        request,
        "This memory update changes durable rules/discipline and requires human confirmation.",
      );
      return {
        disposition: "pending_confirmation",
        reason: "confirmation_required_for_rule_or_discipline",
        pendingConfirmation,
      };
    }

    if (!AUTO_CANDIDATE_KINDS.has(request.kind)) {
      return {
        disposition: "rejected",
        reason: "unsupported_memory_kind_for_auto_candidate",
      };
    }

    return {
      disposition: "memory_candidate",
      reason: "allowed_as_candidate_only",
      candidate: buildCandidate(request),
    };
  }

  evaluateMany(runContract: RunContract, requests: MemoryWriteRequest[]): MemoryWriteDecision[] {
    return requests.map((request) => this.evaluate(runContract, request));
  }
}
