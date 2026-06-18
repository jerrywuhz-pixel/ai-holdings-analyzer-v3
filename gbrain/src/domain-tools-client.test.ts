import { describe, expect, test } from "bun:test";

import { HermesDomainToolsClient } from "./domain-tools-client.js";

describe("HermesDomainToolsClient", () => {
  test("lists domain tools with internal auth header", async () => {
    const calls: Request[] = [];
    const client = new HermesDomainToolsClient("http://data-service:8000", "secret", async (input, init) => {
      const request = new Request(input, init);
      calls.push(request);
      return Response.json({
        ok: true,
        tools: [
          {
            name: "market.quote",
            description: "quote",
            input_schema: {},
            safety: "read_only",
          },
        ],
      });
    });

    const tools = await client.listTools();

    expect(tools[0].name).toBe("market.quote");
    expect(calls[0].headers.get("x-hermes-domain-tools-key")).toBe("secret");
  });

  test("invokes a tenant-scoped domain tool", async () => {
    let body: Record<string, unknown> = {};
    const client = new HermesDomainToolsClient("http://data-service:8000", "secret", async (input, init) => {
      const request = new Request(input, init);
      body = (await request.json()) as Record<string, unknown>;
      return Response.json({
        ok: true,
        result: {
          tool: "broker.positions_read",
          ok: true,
          status: "ok",
          data: { equity_positions: [] },
        },
      });
    });

    const result = await client.invoke({
      tool: "broker.positions_read",
      tenant_id: "tenant-1",
      arguments: { source: "portfolio_read_model" },
    });

    expect(body.tool).toBe("broker.positions_read");
    expect(body.tenant_id).toBe("tenant-1");
    expect(result.ok).toBe(true);
    expect(result.result?.status).toBe("ok");
  });
});
