import { randomUUID } from "node:crypto";

import type { ContextPack, HermesComplexity, ModelPolicy, ModelProviderId, ModelRoute } from "./hermes-types.js";

export interface ModelMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ModelInvocation {
  objective: string;
  systemPrompt?: string;
  messages?: ModelMessage[];
  prompt: string;
  contextPack?: ContextPack;
  temperature?: number;
}

export interface ModelUsage {
  inputTokens: number;
  outputTokens: number;
  estimatedCostUsd: number;
}

export interface ModelResponse {
  responseId: string;
  provider: ModelProviderId;
  model: string;
  text: string;
  finishReason: "stop" | "fallback";
  stub: boolean;
  usage: ModelUsage;
  attemptedRoutes: string[];
}

export interface ModelProvider {
  id: ModelProviderId;
  supports(route: ModelRoute): boolean;
  generate(route: ModelRoute, invocation: ModelInvocation): Promise<ModelResponse>;
}

function estimateTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

function estimateCost(provider: ModelProviderId, inputTokens: number, outputTokens: number): number {
  const unitPrice =
    provider === "openai" ? 0.00001 : provider === "minimax" ? 0.000004 : 0.0;
  return Number(((inputTokens + outputTokens) * unitPrice).toFixed(6));
}

function resolveOpenAIApiKey(): string {
  return process.env.OPENAI_API_KEY || process.env.GBRAIN_OPENAI_API_KEY || "";
}

function resolveMiniMaxApiKey(): string {
  return process.env.MINIMAX_API_KEY || "";
}

function liveModelsEnabled(): boolean {
  return ["1", "true", "yes"].includes((process.env.GBRAIN_LIVE_MODELS_ENABLED || "").toLowerCase());
}

function hasProviderCredentials(provider: ModelProviderId): boolean {
  if (provider === "openai") return resolveOpenAIApiKey() !== "";
  if (provider === "minimax") return resolveMiniMaxApiKey() !== "";
  return false;
}

function resolveRouteMode(provider: ModelProviderId): "stub" | "live" {
  return hasProviderCredentials(provider) && liveModelsEnabled() ? "live" : "stub";
}

function resolveLightModel(): string {
  return process.env.MINIMAX_MODEL || "text-01";
}

function resolveDeepModel(): string {
  return process.env.HERMES_DEEP_MODEL || "gpt-5.5";
}

function resolveOpenAIBaseUrl(): string {
  return (process.env.OPENAI_BASE_URL || process.env.GBRAIN_OPENAI_BASE_URL || "https://api.openai.com/v1").replace(/\/+$/, "");
}

function resolveMiniMaxBaseUrl(): string {
  return (process.env.MINIMAX_OPENAI_BASE_URL || process.env.MINIMAX_BASE_URL || "https://api.minimax.io/v1").replace(/\/+$/, "");
}

function buildStubText(
  provider: ModelProviderId,
  route: ModelRoute,
  invocation: ModelInvocation,
  fallbackReason?: string,
): string {
  const refs = invocation.contextPack?.sourceRefs.length ?? 0;
  const preview = invocation.prompt.replace(/\s+/g, " ").slice(0, 220);

  return [
    `provider=${provider}`,
    `model=${route.model}`,
    `objective=${invocation.objective}`,
    `context_refs=${refs}`,
    `requested_mode=${route.mode ?? "stub"}`,
    `resolved_mode=stub`,
    fallbackReason ? `fallback_reason=${fallbackReason}` : null,
    `response=Stubbed ${provider} output for Hermes/OpenClaw model adapter.`,
    `prompt_preview=${preview}`,
  ]
    .filter((line): line is string => Boolean(line))
    .join("\n");
}

abstract class BaseStubProvider implements ModelProvider {
  abstract id: ModelProviderId;

  protected hasLiveCredentials(): boolean {
    return hasProviderCredentials(this.id);
  }

  supports(route: ModelRoute): boolean {
    return route.provider === this.id;
  }

  protected async generateStub(route: ModelRoute, invocation: ModelInvocation, fallbackReason?: string): Promise<ModelResponse> {
    const inputTokens = estimateTokens(invocation.prompt) + estimateTokens(invocation.systemPrompt ?? "");
    const text = buildStubText(this.id, route, invocation, fallbackReason);
    const outputTokens = estimateTokens(text);

    return {
      responseId: randomUUID(),
      provider: this.id,
      model: route.model,
      text,
      finishReason: "stop",
      stub: true,
      usage: {
        inputTokens,
        outputTokens,
        estimatedCostUsd: estimateCost(this.id, inputTokens, outputTokens),
      },
      attemptedRoutes: [`${this.id}:${route.model}`],
    };
  }

  async generate(route: ModelRoute, invocation: ModelInvocation): Promise<ModelResponse> {
    if (route.mode === "live" && !this.hasLiveCredentials()) {
      return this.generateStub(route, invocation, "missing_api_key");
    }

    if (route.mode === "live" && !liveModelsEnabled()) {
      return this.generateStub(route, invocation, "live_provider_disabled");
    }

    if (route.mode === "live") {
      return this.generateStub(route, invocation, "live_provider_not_enabled");
    }

    return this.generateStub(route, invocation);
  }
}

export class MiniMaxStubProvider extends BaseStubProvider {
  id: ModelProviderId = "minimax";
}

export class OpenAIStubProvider extends BaseStubProvider {
  id: ModelProviderId = "openai";
}

abstract class HttpChatCompletionProvider extends BaseStubProvider {
  protected abstract apiKey(): string;
  protected abstract baseUrl(): string;

  protected endpoint(): string {
    return "/chat/completions";
  }

  private buildMessages(invocation: ModelInvocation): ModelMessage[] {
    return [
      invocation.systemPrompt ? { role: "system", content: invocation.systemPrompt } satisfies ModelMessage : null,
      ...(invocation.messages ?? []),
      { role: "user", content: invocation.prompt } satisfies ModelMessage,
    ].filter((message): message is ModelMessage => Boolean(message));
  }

  override async generate(route: ModelRoute, invocation: ModelInvocation): Promise<ModelResponse> {
    if (route.mode !== "live") {
      return this.generateStub(route, invocation);
    }
    if (!this.apiKey()) {
      return this.generateStub(route, invocation, "missing_api_key");
    }
    if (!liveModelsEnabled()) {
      return this.generateStub(route, invocation, "live_provider_disabled");
    }

    const inputTokens = estimateTokens(invocation.prompt) + estimateTokens(invocation.systemPrompt ?? "");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), route.timeoutMs ?? 60_000);

    try {
      const response = await fetch(`${this.baseUrl()}${this.endpoint()}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${this.apiKey()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: route.model,
          messages: this.buildMessages(invocation),
          temperature: invocation.temperature ?? 0.2,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${this.id} provider HTTP ${response.status}: ${text.slice(0, 500)}`);
      }

      const payload = (await response.json()) as {
        id?: string;
        choices?: Array<{ message?: { content?: string }; text?: string; finish_reason?: string }>;
        usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
      };
      const text = payload.choices?.[0]?.message?.content ?? payload.choices?.[0]?.text ?? "";
      if (!text.trim()) {
        throw new Error(`${this.id} provider returned an empty response`);
      }

      const resolvedInputTokens = payload.usage?.prompt_tokens ?? inputTokens;
      const outputTokens = payload.usage?.completion_tokens ?? estimateTokens(text);
      return {
        responseId: payload.id ?? randomUUID(),
        provider: this.id,
        model: route.model,
        text,
        finishReason: "stop",
        stub: false,
        usage: {
          inputTokens: resolvedInputTokens,
          outputTokens,
          estimatedCostUsd: estimateCost(this.id, resolvedInputTokens, outputTokens),
        },
        attemptedRoutes: [`${this.id}:${route.model}`],
      };
    } finally {
      clearTimeout(timeout);
    }
  }
}

export class OpenAIChatCompletionProvider extends HttpChatCompletionProvider {
  id: ModelProviderId = "openai";

  protected apiKey(): string {
    return resolveOpenAIApiKey();
  }

  protected baseUrl(): string {
    return resolveOpenAIBaseUrl();
  }
}

export class MiniMaxChatCompletionProvider extends HttpChatCompletionProvider {
  id: ModelProviderId = "minimax";

  protected apiKey(): string {
    return resolveMiniMaxApiKey();
  }

  protected baseUrl(): string {
    return resolveMiniMaxBaseUrl();
  }
}

export class FallbackTemplateProvider extends BaseStubProvider {
  id: ModelProviderId = "fallback-template";

  async generate(route: ModelRoute, invocation: ModelInvocation): Promise<ModelResponse> {
    const base = await super.generate(route, invocation);
    return {
      ...base,
      text: [
        "# Hermes Fallback Template",
        `Objective: ${invocation.objective}`,
        `Fallback model: ${route.model}`,
        `Context refs: ${invocation.contextPack?.sourceRefs.length ?? 0}`,
        "",
        "This is a deterministic fallback template. Use it for degraded analysis summaries, never for direct business-fact writes.",
      ].join("\n"),
    };
  }
}

export class FailingProvider implements ModelProvider {
  constructor(public readonly id: ModelProviderId, private readonly errorMessage: string) {}

  supports(route: ModelRoute): boolean {
    return route.provider === this.id;
  }

  async generate(): Promise<ModelResponse> {
    throw new Error(this.errorMessage);
  }
}

export class ModelAdapter {
  private readonly providers: ModelProvider[];

  constructor(providers: ModelProvider[]) {
    this.providers = providers;
  }

  async generate(modelPolicy: ModelPolicy, invocation: ModelInvocation): Promise<ModelResponse> {
    const attempts: string[] = [];
    const routes = [modelPolicy.primary, ...modelPolicy.fallbacks];
    let lastError: Error | null = null;

    for (const route of routes) {
      const provider = this.providers.find((candidate) => candidate.supports(route));
      attempts.push(`${route.provider}:${route.model}`);
      if (!provider) {
        lastError = new Error(`No provider registered for ${route.provider}`);
        continue;
      }

      try {
        const response = await provider.generate(route, invocation);
        return {
          ...response,
          finishReason: attempts.length > 1 ? "fallback" : response.finishReason,
          attemptedRoutes: attempts,
        };
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));
      }
    }

    throw lastError ?? new Error("ModelAdapter failed without a provider error");
  }
}

export function buildDefaultModelAdapter(): ModelAdapter {
  return new ModelAdapter([
    new OpenAIChatCompletionProvider(),
    new MiniMaxChatCompletionProvider(),
    new FallbackTemplateProvider(),
  ]);
}

function shouldUseDeepResearchRoute(timeoutMs: number, complexity?: HermesComplexity): boolean {
  return complexity === "deep" || complexity === "background" || timeoutMs > 300_000;
}

export function createDefaultHermesModelPolicy(timeoutMs: number, complexity?: HermesComplexity): ModelPolicy {
  const primaryProvider: ModelProviderId = shouldUseDeepResearchRoute(timeoutMs, complexity) ? "openai" : "minimax";
  const primaryModel = primaryProvider === "openai" ? resolveDeepModel() : resolveLightModel();

  return {
    primary: {
      provider: primaryProvider,
      model: primaryModel,
      mode: resolveRouteMode(primaryProvider),
      timeoutMs,
    },
    fallbacks: [
      {
        provider: "fallback-template",
        model: "hermes-fallback-v1",
        mode: "stub",
        timeoutMs: Math.min(timeoutMs, 30_000),
      },
    ],
    budgetLimit: {
      maxCostUsd: timeoutMs > 300_000 ? 3.0 : 0.5,
      quotaType: timeoutMs > 300_000 ? "deep_research" : "standard",
    },
  };
}

export function createDefaultOpenClawModelPolicy(timeoutMs: number): ModelPolicy {
  return {
    primary: {
      provider: "minimax",
      model: resolveLightModel(),
      mode: resolveRouteMode("minimax"),
      timeoutMs,
    },
    fallbacks: [
      {
        provider: "fallback-template",
        model: "openclaw-fallback-v1",
        mode: "stub",
        timeoutMs: Math.min(timeoutMs, 10_000),
      },
    ],
    budgetLimit: {
      maxCostUsd: 0.15,
      quotaType: "daily_text",
    },
  };
}
