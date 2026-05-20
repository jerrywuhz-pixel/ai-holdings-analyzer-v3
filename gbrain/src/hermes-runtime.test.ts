import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, test } from "node:test";

import type { ContextSourceRef, MemoryWriteRequest, RunContract } from "./hermes-types.js";
import { ContextPackBuilder } from "./hermes-context-pack.js";
import { ArtifactRegistryWriterClient, FileArtifactObjectStore, InMemoryArtifactRegistrySink, buildArtifactRegistryInsert } from "./hermes-artifact-registry.js";
import { getDatabaseWaitConfig, waitForDatabase } from "./database-retry.js";
import { MemoryWriteGate } from "./hermes-memory-gate.js";
import { WeeklyOptimizationConfirmationProposalGenerator } from "./hermes-optimization.js";
import { HermesWorker, createHermesJob, createOptimizationSuggestions } from "./hermes-runtime.js";
import { ContextPackBuilder as RuntimeContextPackBuilder } from "./hermes-context-pack.js";
import { FailingProvider, FallbackTemplateProvider, ModelAdapter, buildDefaultModelAdapter, createDefaultHermesModelPolicy } from "./model-adapter.js";
import { MemoryWriteGate as RuntimeMemoryWriteGate } from "./hermes-memory-gate.js";
import { WeeklyOptimizationConfirmationProposalGenerator as RuntimeOptimizer } from "./hermes-optimization.js";

async function withEnv<T>(overrides: Record<string, string | undefined>, run: () => Promise<T> | T): Promise<T> {
  const previous = new Map<string, string | undefined>();
  for (const [key, value] of Object.entries(overrides)) {
    previous.set(key, process.env[key]);
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }

  try {
    return await run();
  } finally {
    for (const [key, value] of previous.entries()) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  }
}

function createRunContract(): RunContract {
  return {
    runId: "run-123",
    tenantId: "tenant-123",
    trigger: "wechat_message",
    intent: "deep_research",
    runtimeTarget: "hermes",
    agentRole: "deep_research_agent",
    complexity: "deep",
    riskLevel: "medium",
    dataScope: {
      symbols: ["NVDA"],
    },
    memoryScope: {
      tenantId: "tenant-123",
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
      policyHash: "policy-123",
      allowedTools: ["research_artifacts.write", "market.quote.read"],
      forbiddenTools: ["broker.trade.place_order", "portfolio_positions.direct_update"],
    },
    createdAt: new Date().toISOString(),
  };
}

function createSourceRef(refId: string): ContextSourceRef {
  return {
    refId,
    refType: "business_fact",
    title: `ref-${refId}`,
    summary: `summary-${refId}`,
    trustLevel: "high",
  };
}

describe("ModelAdapter", () => {
  test("routes light Hermes jobs to minimax and deep jobs to gpt-5.5 defaults", async () => {
    await withEnv(
      {
        OPENAI_API_KEY: undefined,
        GBRAIN_OPENAI_API_KEY: undefined,
        MINIMAX_API_KEY: undefined,
        GBRAIN_LIVE_MODELS_ENABLED: undefined,
        MINIMAX_MODEL: "text-01",
        HERMES_DEEP_PROVIDER: undefined,
        HERMES_DEEP_MODEL: undefined,
        MODEL_AUTH_MODE: undefined,
        MODEL_ADAPTER_FALLBACK_PROVIDER: undefined,
      },
      () => {
        const lightPolicy = createDefaultHermesModelPolicy(5 * 60 * 1000, "standard");
        const deepPolicy = createDefaultHermesModelPolicy(30 * 60 * 1000, "deep");

        assert.equal(lightPolicy.primary.provider, "minimax");
        assert.equal(lightPolicy.primary.model, "text-01");
        assert.equal(lightPolicy.primary.mode, "stub");
        assert.equal(deepPolicy.primary.provider, "openai");
        assert.equal(deepPolicy.primary.model, "gpt-5.5");
        assert.equal(deepPolicy.primary.mode, "stub");
      },
    );
  });

  test("can route deep Hermes jobs through the system-level openai-codex provider", async () => {
    await withEnv(
      {
        HERMES_DEEP_PROVIDER: "openai-codex",
        HERMES_DEEP_MODEL: undefined,
        MODEL_AUTH_MODE: undefined,
        MODEL_ADAPTER_FALLBACK_PROVIDER: undefined,
        OPENAI_CODEX_AUTH_PROFILE: undefined,
        OPENAI_CODEX_BRIDGE_BASE_URL: undefined,
        GBRAIN_LIVE_MODELS_ENABLED: undefined,
      },
      () => {
        const deepPolicy = createDefaultHermesModelPolicy(30 * 60 * 1000, "deep");

        assert.equal(deepPolicy.primary.provider, "openai-codex");
        assert.equal(deepPolicy.primary.model, "gpt-5.5");
        assert.equal(deepPolicy.primary.mode, "stub");
      },
    );
  });

  test("falls back to stub output when live mode is requested without provider credentials", async () => {
    await withEnv(
      {
        MINIMAX_API_KEY: undefined,
      },
      async () => {
        const adapter = buildDefaultModelAdapter();
        const response = await adapter.generate(
          {
            primary: { provider: "minimax", model: "text-01", mode: "live" },
            fallbacks: [],
          },
          {
            objective: "daily summary",
            prompt: "Summarize the watchlist in one paragraph.",
          },
        );

        assert.equal(response.provider, "minimax");
        assert.equal(response.stub, true);
        assert.match(response.text, /fallback_reason=missing_api_key/);
      },
    );
  });

  test("uses live OpenAI-compatible chat completion only behind the live gate", async () => {
    const previousFetch = globalThis.fetch;
    const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      calls.push({
        url: String(input),
        body: JSON.parse(String(init?.body ?? "{}")),
      });
      return new Response(
        JSON.stringify({
          id: "resp-live-1",
          choices: [{ message: { content: "Live model response" } }],
          usage: { prompt_tokens: 12, completion_tokens: 3 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }) as typeof fetch;

    try {
      await withEnv(
        {
          OPENAI_API_KEY: "test-openai-key",
          GBRAIN_LIVE_MODELS_ENABLED: "true",
          OPENAI_BASE_URL: "https://openai.example/v1",
        },
        async () => {
          const adapter = buildDefaultModelAdapter();
          const response = await adapter.generate(
            {
              primary: { provider: "openai", model: "gpt-5.5", mode: "live" },
              fallbacks: [],
            },
            {
              objective: "deep research",
              systemPrompt: "Be precise.",
              prompt: "Summarize NVDA.",
            },
          );

          assert.equal(response.stub, false);
          assert.equal(response.provider, "openai");
          assert.equal(response.text, "Live model response");
          assert.equal(calls[0].url, "https://openai.example/v1/chat/completions");
          assert.equal(calls[0].body.model, "gpt-5.5");
        },
      );
    } finally {
      globalThis.fetch = previousFetch;
    }
  });

  test("uses MiniMax Anthropic-compatible endpoint when configured", async () => {
    const previousFetch = globalThis.fetch;
    const calls: Array<{ url: string; headers: Headers; body: Record<string, unknown> }> = [];
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      calls.push({
        url: String(input),
        headers: new Headers(init?.headers),
        body: JSON.parse(String(init?.body ?? "{}")),
      });
      return new Response(
        JSON.stringify({
          id: "msg-minimax-1",
          content: [{ type: "text", text: "MiniMax response" }],
          usage: { input_tokens: 11, output_tokens: 4 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }) as typeof fetch;

    try {
      await withEnv(
        {
          MINIMAX_API_KEY: "test-minimax-key",
          MINIMAX_OPENAI_BASE_URL: "https://api.minimaxi.com/anthropic",
          MINIMAX_API_FORMAT: "anthropic",
          GBRAIN_LIVE_MODELS_ENABLED: "true",
        },
        async () => {
          const adapter = buildDefaultModelAdapter();
          const response = await adapter.generate(
            {
              primary: { provider: "minimax", model: "MiniMax-M2.7", mode: "live" },
              fallbacks: [],
            },
            {
              objective: "daily intent",
              systemPrompt: "Be concise.",
              prompt: "Reply ok.",
            },
          );

          assert.equal(response.stub, false);
          assert.equal(response.provider, "minimax");
          assert.equal(response.text, "MiniMax response");
          assert.equal(calls[0].url, "https://api.minimaxi.com/anthropic/v1/messages");
          assert.equal(calls[0].headers.get("x-api-key"), "test-minimax-key");
          assert.equal(calls[0].headers.get("anthropic-version"), "2023-06-01");
          assert.equal(calls[0].body.model, "MiniMax-M2.7");
          assert.equal(calls[0].body.system, "Be concise.");
          assert.equal(calls[0].body.max_tokens, 2048);
        },
      );
    } finally {
      globalThis.fetch = previousFetch;
    }
  });

  test("uses Anthropic-style MiniMax token plan environment", async () => {
    const previousFetch = globalThis.fetch;
    const calls: Array<{ url: string; headers: Headers; body: Record<string, unknown> }> = [];
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      calls.push({
        url: String(input),
        headers: new Headers(init?.headers),
        body: JSON.parse(String(init?.body ?? "{}")),
      });
      return new Response(
        JSON.stringify({
          id: "msg-minimax-token-plan",
          content: [{ type: "text", text: "MiniMax token plan response" }],
          usage: { input_tokens: 9, output_tokens: 5 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }) as typeof fetch;

    try {
      await withEnv(
        {
          MINIMAX_API_KEY: undefined,
          MINIMAX_OPENAI_BASE_URL: undefined,
          MINIMAX_API_FORMAT: undefined,
          ANTHROPIC_AUTH_TOKEN: "test-anthropic-token",
          ANTHROPIC_BASE_URL: "https://api.minimaxi.com/anthropic/v1",
          ANTHROPIC_MODEL: "MiniMax-M2.7",
          GBRAIN_LIVE_MODELS_ENABLED: "true",
        },
        async () => {
          const adapter = buildDefaultModelAdapter();
          const response = await adapter.generate(
            {
              primary: { provider: "minimax", model: "MiniMax-M2.7", mode: "live" },
              fallbacks: [],
            },
            {
              objective: "daily intent",
              prompt: "Reply ok.",
            },
          );

          assert.equal(response.stub, false);
          assert.equal(response.text, "MiniMax token plan response");
          assert.equal(calls[0].url, "https://api.minimaxi.com/anthropic/v1/messages");
          assert.equal(calls[0].headers.get("x-api-key"), "test-anthropic-token");
          assert.equal(calls[0].headers.get("anthropic-version"), "2023-06-01");
          assert.equal(calls[0].body.model, "MiniMax-M2.7");
        },
      );
    } finally {
      globalThis.fetch = previousFetch;
    }
  });

  test("uses the configured openai-codex bridge without requiring an OpenAI API key", async () => {
    const previousFetch = globalThis.fetch;
    const calls: Array<{ url: string; headers: Headers; body: Record<string, unknown> }> = [];
    globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
      calls.push({
        url: String(input),
        headers: new Headers(init?.headers),
        body: JSON.parse(String(init?.body ?? "{}")),
      });
      return new Response(
        JSON.stringify({
          id: "resp-codex-1",
          choices: [{ message: { content: "Codex auth profile response" } }],
          usage: { prompt_tokens: 18, completion_tokens: 5 },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }) as typeof fetch;

    try {
      await withEnv(
        {
          OPENAI_API_KEY: undefined,
          GBRAIN_OPENAI_API_KEY: undefined,
          GBRAIN_LIVE_MODELS_ENABLED: "true",
          OPENAI_CODEX_AUTH_PROFILE: "system-pro",
          OPENAI_CODEX_BRIDGE_BASE_URL: "https://codex-bridge.example/v1",
          OPENAI_CODEX_BRIDGE_API_KEY: undefined,
        },
        async () => {
          const adapter = buildDefaultModelAdapter();
          const response = await adapter.generate(
            {
              primary: { provider: "openai-codex", model: "gpt-5.5", mode: "live" },
              fallbacks: [],
            },
            {
              objective: "deep research",
              systemPrompt: "Be precise.",
              prompt: "Summarize NVDA.",
            },
          );

          assert.equal(response.stub, false);
          assert.equal(response.provider, "openai-codex");
          assert.equal(response.text, "Codex auth profile response");
          assert.equal(calls[0].url, "https://codex-bridge.example/v1/chat/completions");
          assert.equal(calls[0].headers.get("x-hermes-auth-profile"), "system-pro");
          assert.equal(calls[0].headers.has("authorization"), false);
          assert.equal(calls[0].body.model, "openai-codex/gpt-5.5");
        },
      );
    } finally {
      globalThis.fetch = previousFetch;
    }
  });

  test("falls back to template provider when primary provider fails", async () => {
    const adapter = new ModelAdapter([
      new FailingProvider("openai", "simulated provider failure"),
      new FallbackTemplateProvider(),
    ]);

    const response = await adapter.generate(
      {
        primary: { provider: "openai", model: "gpt-5.5", mode: "stub" },
        fallbacks: [{ provider: "fallback-template", model: "hermes-fallback-v1", mode: "stub" }],
      },
      {
        objective: "deep research",
        prompt: "Summarize NVDA risk.",
      },
    );

    assert.equal(response.provider, "fallback-template");
    assert.match(response.text, /Hermes Fallback Template/);
    assert.deepEqual(response.attemptedRoutes, ["openai:gpt-5.5", "fallback-template:hermes-fallback-v1"]);
  });
});

describe("database startup retry", () => {
  test("retries transient database connection failures before giving up", async () => {
    let attempts = 0;
    const messages: string[] = [];

    await waitForDatabase(
      async () => {
        attempts += 1;
        if (attempts < 3) {
          throw new Error("database not ready");
        }
      },
      { attempts: 4, delayMs: 0 },
      (message) => messages.push(message),
    );

    assert.equal(attempts, 3);
    assert.equal(messages.length, 2);
    assert.match(messages[0], /attempt 1\/4/);
  });

  test("uses one attempt for Docker health checks", () => {
    const config = getDatabaseWaitConfig(
      {
        GBRAIN_DATABASE_CONNECT_RETRIES: "9",
        GBRAIN_DATABASE_CONNECT_RETRY_DELAY_MS: "250",
      },
      true,
    );

    assert.deepEqual(config, { attempts: 1, delayMs: 250 });
  });
});

describe("ContextPackBuilder", () => {
  test("dedupes refs and stays within a practical token budget", () => {
    const builder = new ContextPackBuilder();
    const contextPack = builder.build({
      runContract: createRunContract(),
      userMessage: "做一份 NVDA 深研",
      businessFacts: [
        { refId: "quote", title: "Quote", summary: "NVDA last close 100", priority: 10 },
        { refId: "earnings", title: "Earnings", summary: "Revenue growth strong", priority: 8 },
      ],
      memoryResults: [{ refId: "m1", title: "Prior note", summary: "User prefers conservative entries" }],
      sourceRefs: [createSourceRef("quote"), createSourceRef("quote"), createSourceRef("earnings")],
      tokenBudget: 120,
    });

    assert.equal(contextPack.sourceRefs.length, 2);
    assert.ok(contextPack.estimatedTokens <= 160);
  });

  test("retains distinct source refs across ref types while trimming oversized sections", () => {
    const builder = new ContextPackBuilder();
    const repeatedBody = "very long context ".repeat(20);
    const contextPack = builder.build({
      runContract: createRunContract(),
      userMessage: "整理上下文",
      businessFacts: [{ refId: "same-id", title: "Fact", summary: repeatedBody, priority: 10 }],
      memoryResults: [{ refId: "memory-1", title: "Memory", summary: "Keep the user's risk preference visible", priority: 9 }],
      sourceRefs: [
        createSourceRef("same-id"),
        { ...createSourceRef("same-id"), refType: "memory" },
      ],
      tokenBudget: 40,
      trimStrategy: "memory_first",
    });

    assert.equal(contextPack.sourceRefs.length, 2);
    assert.equal(contextPack.sections.find((section) => section.label === "business_facts")?.truncated, true);
    assert.match(contextPack.renderedPrompt, /\[memory\]/);
  });
});

describe("MemoryWriteGate", () => {
  test("blocks business fact writes and routes durable rules to confirmation", () => {
    const gate = new MemoryWriteGate();
    const runContract = createRunContract();

    const factAttempt: MemoryWriteRequest = {
      tenantId: "tenant-123",
      sourceJobId: "job-1",
      title: "Position update",
      content: "AAPL now has 20 shares",
      kind: "broker_fact_ref",
      sourceLineage: [createSourceRef("position-snapshot")],
      referencesBusinessFactsOnly: false,
      assertsBusinessFact: true,
    };
    const ruleAttempt: MemoryWriteRequest = {
      tenantId: "tenant-123",
      sourceJobId: "job-1",
      title: "Default roll threshold",
      content: "Always roll at 0.2 delta.",
      kind: "confirmed_rule",
      sourceLineage: [createSourceRef("rule-review")],
      requestedPromotion: "confirmed_rule",
    };

    const factDecision = gate.evaluate(runContract, factAttempt);
    const ruleDecision = gate.evaluate(runContract, ruleAttempt);

    assert.equal(factDecision.disposition, "rejected");
    assert.equal(ruleDecision.disposition, "pending_confirmation");
    assert.equal(ruleDecision.pendingConfirmation?.confirmationType, "memory_rule_upgrade");
  });

  test("rejects secret and cross-tenant memory writes before candidate generation", () => {
    const gate = new MemoryWriteGate();
    const runContract = createRunContract();

    const secretAttempt: MemoryWriteRequest = {
      tenantId: "tenant-123",
      sourceJobId: "job-2",
      title: "Leaked credential",
      content: "API key is sk-live-123",
      kind: "session_summary",
      sourceLineage: [createSourceRef("chat-secret")],
      containsSecret: true,
    };
    const crossTenantAttempt: MemoryWriteRequest = {
      tenantId: "tenant-999",
      sourceJobId: "job-2",
      title: "Other tenant note",
      content: "This belongs elsewhere.",
      kind: "research_summary",
      sourceLineage: [createSourceRef("chat-cross-tenant")],
      containsCrossTenantData: true,
    };

    const [secretDecision, crossTenantDecision] = gate.evaluateMany(runContract, [secretAttempt, crossTenantAttempt]);

    assert.deepEqual(
      [secretDecision.disposition, secretDecision.reason],
      ["rejected", "secret_material_forbidden"],
    );
    assert.deepEqual(
      [crossTenantDecision.disposition, crossTenantDecision.reason],
      ["rejected", "tenant_mismatch"],
    );
  });
});

describe("HermesWorker", () => {
  test("emits only allowed write targets and applies deep timeout defaults", async () => {
    await withEnv(
      {
        OPENAI_API_KEY: undefined,
        GBRAIN_OPENAI_API_KEY: undefined,
        MINIMAX_API_KEY: undefined,
      },
      async () => {
        const sink = new InMemoryArtifactRegistrySink();
        const worker = new HermesWorker(
          buildDefaultModelAdapter(),
          new RuntimeContextPackBuilder(),
          new RuntimeMemoryWriteGate(),
          new ArtifactRegistryWriterClient(sink),
          new RuntimeOptimizer(),
        );
        const job = createHermesJob({
          id: "job-deep-1",
          tenantId: "tenant-123",
          sourceRunId: "source-run-789",
          jobType: "deep_research",
          complexity: "deep",
        });
        const runContract = createRunContract();
        const result = await worker.run({
          job,
          runContract,
          userMessage: "给我一份 NVDA 深研",
          contextInput: {
            businessFacts: [{ refId: "quote", title: "Quote", summary: "NVDA cashflow stable", priority: 10 }],
            memoryResults: [{ refId: "m1", title: "Preference", summary: "User dislikes leverage", priority: 8 }],
            sourceRefs: [createSourceRef("quote"), createSourceRef("m1")],
          },
          memoryWriteRequests: [
            {
              tenantId: "tenant-123",
              sourceJobId: "job-deep-1",
              title: "Conservative tech preference",
              content: "User prefers staggered entries for high-beta names.",
              kind: "preference",
              sourceLineage: [createSourceRef("chat-1")],
            },
          ],
          optimizationSuggestions: createOptimizationSuggestions("job-deep-1", "tenant-123"),
        });

        assert.equal(result.timeoutMs, 30 * 60 * 1000);
        assert.ok(result.writeEnvelope.artifacts.length >= 1);
        assert.equal(result.writeEnvelope.memoryCandidates.length, 1);
        assert.ok(result.writeEnvelope.pendingConfirmations.some((item) => item.confirmationType === "trade_execution_optimization"));
        assert.equal(Object.prototype.hasOwnProperty.call(result.writeEnvelope, "facts"), false);

        const primaryArtifact = result.writeEnvelope.artifacts[0];
        assert.deepEqual(primaryArtifact.metadata?.tenant_id, "tenant-123");
        assert.deepEqual(primaryArtifact.metadata?.artifact_type, "deep_research_report");
        assert.deepEqual(primaryArtifact.metadata?.source_run_id, "source-run-789");
        assert.deepEqual(primaryArtifact.metadata?.model_id, "gpt-5.5");
        assert.deepEqual(primaryArtifact.metadata?.model_provider, "openai");
        assert.ok(Array.isArray(primaryArtifact.metadata?.lineage));
        assert.ok(Array.isArray(primaryArtifact.metadata?.source_refs));
        assert.equal(typeof primaryArtifact.metadata?.retention_until, "string");
        assert.equal(primaryArtifact.metadata?.storage_backend, "supabase");
        assert.equal(typeof primaryArtifact.metadata?.storage_path, "string");

        const insert = buildArtifactRegistryInsert(primaryArtifact);
        assert.match(insert.text, /INSERT INTO artifact_registry/);
        assert.equal(insert.values[1], "tenant-123");
        assert.equal(insert.values[2], "source-run-789");

        const metadata = JSON.parse(String(insert.values[12]));
        assert.equal(metadata.tenant_id, "tenant-123");
        assert.equal(metadata.artifact_type, "deep_research_report");
        assert.equal(metadata.source_run_id, "source-run-789");
        assert.equal(metadata.model_id, "gpt-5.5");
        assert.equal(metadata.model_provider, "openai");
        assert.ok(Array.isArray(metadata.lineage));
        assert.ok(Array.isArray(metadata.source_refs));
        assert.equal(typeof metadata.retention_until, "string");
        assert.equal(metadata.storage_backend, "supabase");
        assert.equal(typeof metadata.storage_path, "string");
      },
    );
  });
});

describe("ArtifactRegistryWriterClient", () => {
  test("writes artifact content to object storage before registry insert", async () => {
    const root = await mkdtemp(join(tmpdir(), "hermes-artifact-"));
    try {
      const sink = new InMemoryArtifactRegistrySink();
      const objectStore = new FileArtifactObjectStore(root);
      const writer = new ArtifactRegistryWriterClient(sink, "file://artifacts", objectStore);
      const record = await writer.register({
        tenantId: "tenant-123",
        artifactType: "deep_research_report",
        ownerRunId: "run-123",
        ownerAgent: "deep_research_agent",
        modelId: "gpt-5.5",
        sourceRefs: [createSourceRef("quote")],
        title: "NVDA research",
        content: "# NVDA\n\nResearch body",
      });

      assert.equal(sink.records.length, 1);
      assert.equal(await objectStore.read?.(record.storageUri), "# NVDA\n\nResearch body");
      assert.equal(record.metadata?.storage_backend, "file");
      assert.equal(record.metadata?.storage_bucket, "artifacts");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe("WeeklyOptimizationConfirmationProposalGenerator", () => {
  test("auto applies low-risk output optimizations and queues execution changes for review", () => {
    const generator = new WeeklyOptimizationConfirmationProposalGenerator();
    const digest = generator.generate(createOptimizationSuggestions("job-weekly-1", "tenant-123"));

    assert.equal(digest.autoApplied.length, 1);
    assert.equal(digest.reviewRequired.length, 1);
    assert.equal(digest.pendingConfirmations.length, 1);
    assert.equal(digest.summaryArtifactDraft?.artifactType, "weekly_optimization_confirmation");
  });
});
