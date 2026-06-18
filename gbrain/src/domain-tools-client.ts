export interface DomainToolDescriptor {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  safety: "read_only" | "read_only_trade_draft_only" | "reference_only" | string;
}

export interface DomainToolInvocation {
  tool: string;
  tenant_id?: string;
  arguments?: Record<string, unknown>;
  run_id?: string;
}

export interface DomainToolResult {
  ok: boolean;
  run_id?: string;
  result?: {
    tool: string;
    ok: boolean;
    status: string;
    data?: unknown;
    error?: string;
    source_refs?: Array<Record<string, string>>;
  };
}

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export class HermesDomainToolsClient {
  constructor(
    private readonly baseUrl = process.env.HERMES_DOMAIN_TOOLS_URL || process.env.DATA_SERVICE_URL || "http://data-service:8000",
    private readonly apiKey = process.env.HERMES_DOMAIN_TOOLS_KEY || process.env.HERMES_INTERNAL_TOKEN || "",
    private readonly fetchImpl: FetchLike = fetch,
  ) {}

  async listTools(): Promise<DomainToolDescriptor[]> {
    const response = await this.fetchImpl(`${this.baseUrl.replace(/\/$/, "")}/api/hermes/domain-tools`, {
      method: "GET",
      headers: this.headers(),
    });
    if (!response.ok) {
      throw new Error(`domain tools manifest failed: ${response.status}`);
    }
    const payload = (await response.json()) as { ok?: boolean; tools?: DomainToolDescriptor[] };
    if (!payload.ok || !Array.isArray(payload.tools)) {
      throw new Error("domain tools manifest returned invalid payload");
    }
    return payload.tools;
  }

  async invoke(invocation: DomainToolInvocation): Promise<DomainToolResult> {
    const response = await this.fetchImpl(`${this.baseUrl.replace(/\/$/, "")}/api/hermes/domain-tools/invoke`, {
      method: "POST",
      headers: {
        ...this.headers(),
        "content-type": "application/json",
      },
      body: JSON.stringify({
        ...invocation,
        arguments: invocation.arguments ?? {},
      }),
    });
    if (!response.ok) {
      throw new Error(`domain tool invocation failed: ${response.status}`);
    }
    return (await response.json()) as DomainToolResult;
  }

  private headers(): Record<string, string> {
    return this.apiKey ? { "x-hermes-domain-tools-key": this.apiKey } : {};
  }
}
