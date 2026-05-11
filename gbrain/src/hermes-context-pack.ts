import { createHash } from "node:crypto";

import type { ContextPack, ContextPackBuildInput, ContextSnippet, ContextSourceRef } from "./hermes-types.js";

function estimateTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

function stableHash(input: string): string {
  return createHash("sha256").update(input).digest("hex");
}

function byPriorityDesc(a: ContextSnippet, b: ContextSnippet): number {
  return (b.priority ?? 0) - (a.priority ?? 0);
}

function dedupeRefs(refs: ContextSourceRef[]): ContextSourceRef[] {
  const seen = new Set<string>();
  const output: ContextSourceRef[] = [];

  for (const ref of refs) {
    const key = `${ref.refType}:${ref.refId}`;
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(ref);
  }

  return output;
}

function trimSectionItems(items: string[], budgetTokens: number): { items: string[]; truncated: boolean } {
  const output: string[] = [];
  let usedTokens = 0;

  for (const item of items) {
    const cost = estimateTokens(item);
    if (usedTokens + cost > budgetTokens && output.length > 0) {
      return { items: output, truncated: true };
    }
    if (cost > budgetTokens && output.length === 0) {
      return { items: [item.slice(0, budgetTokens * 4)], truncated: true };
    }
    usedTokens += cost;
    output.push(item);
  }

  return { items: output, truncated: false };
}

export class ContextPackBuilder {
  build(input: ContextPackBuildInput): ContextPack {
    const tokenBudget = input.tokenBudget ?? (input.runContract.complexity === "deep" ? 3_200 : 1_600);
    const trimStrategy = input.trimStrategy ?? "balanced";

    const userSection = [`User message: ${input.userMessage}`];
    const sessionSection = input.sessionSummary ? [`Session summary: ${input.sessionSummary}`] : [];
    const facts = [...(input.businessFacts ?? [])].sort(byPriorityDesc).map((fact) => `${fact.title}: ${fact.summary}`);
    const memories = [...(input.memoryResults ?? [])].sort(byPriorityDesc).map((memory) => `${memory.title}: ${memory.summary}`);
    const artifacts = [...(input.artifacts ?? [])].sort(byPriorityDesc).map((artifact) => `${artifact.title}: ${artifact.summary}`);

    const budgetBySection =
      trimStrategy === "facts_first"
        ? { facts: Math.floor(tokenBudget * 0.45), memories: Math.floor(tokenBudget * 0.2), artifacts: Math.floor(tokenBudget * 0.15), rest: Math.floor(tokenBudget * 0.2) }
        : trimStrategy === "memory_first"
          ? { facts: Math.floor(tokenBudget * 0.2), memories: Math.floor(tokenBudget * 0.45), artifacts: Math.floor(tokenBudget * 0.15), rest: Math.floor(tokenBudget * 0.2) }
          : { facts: Math.floor(tokenBudget * 0.33), memories: Math.floor(tokenBudget * 0.27), artifacts: Math.floor(tokenBudget * 0.15), rest: Math.floor(tokenBudget * 0.25) };

    const factsTrim = trimSectionItems(facts, budgetBySection.facts);
    const memoriesTrim = trimSectionItems(memories, budgetBySection.memories);
    const artifactsTrim = trimSectionItems(artifacts, budgetBySection.artifacts);
    const userTrim = trimSectionItems([...userSection, ...sessionSection], budgetBySection.rest);

    const sections = [
      { label: "request", ...userTrim },
      { label: "business_facts", ...factsTrim },
      { label: "memory", ...memoriesTrim },
      { label: "artifacts", ...artifactsTrim },
    ];

    const renderedPrompt = sections
      .filter((section) => section.items.length > 0)
      .map((section) => [`[${section.label}]`, ...section.items].join("\n"))
      .join("\n\n");
    const refs = dedupeRefs(input.sourceRefs ?? []);
    const sourceHash = stableHash(JSON.stringify(refs.map((ref) => [ref.refType, ref.refId, ref.hash ?? ref.summary])));

    return {
      contextPackId: stableHash(`${input.runContract.runId}:${input.runContract.tenantId}:${sourceHash}`).slice(0, 24),
      runId: input.runContract.runId,
      tenantId: input.runContract.tenantId,
      tokenBudget,
      estimatedTokens: estimateTokens(renderedPrompt),
      trimStrategy,
      createdAt: new Date().toISOString(),
      sourceRefs: refs,
      renderedPrompt,
      sections,
      sourceHash,
    };
  }
}
