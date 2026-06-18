/**
 * gbrain MCP Adapter for Hermes
 *
 * MCP stdio server exposing gbrain brain operations as tools.
 * Directly operates on gbrain_* tables in Supabase Postgres.
 * Does NOT depend on gbrain CLI — avoids version coupling.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import postgres from "postgres";
import OpenAI from "openai";
import { z } from "zod";
import { getDatabaseWaitConfig, waitForDatabase } from "./database-retry.js";

// ---------------------------------------------------------------------------
// Environment
// ---------------------------------------------------------------------------
const DATABASE_URL = process.env.DATABASE_URL || process.env.GBRAIN_DATABASE_URL || "";
const OPENAI_API_KEY = process.env.OPENAI_API_KEY || process.env.GBRAIN_OPENAI_API_KEY || "";
const EMBEDDING_MODEL = process.env.GBRAIN_EMBEDDING_MODEL || "text-embedding-3-small";
const CHUNK_SIZE = parseInt(process.env.GBRAIN_CHUNK_SIZE || "500", 10);
const CHUNK_OVERLAP = parseInt(process.env.GBRAIN_CHUNK_OVERLAP || "50", 10);
const ADAPTER_VERSION = process.env.GBRAIN_ADAPTER_VERSION || "0.2.0";
const HERMES_UPSTREAM_TARGET_VERSION = process.env.HERMES_UPSTREAM_TARGET_VERSION || "v2026.5.29";
const HEALTH_CHECK_MODE = process.argv.includes("--health-check");
const HEALTH_JSON_MODE = process.argv.includes("--health-json");

if (!DATABASE_URL) {
  console.error("[gbrain] DATABASE_URL or GBRAIN_DATABASE_URL is required");
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------
const sql = postgres(DATABASE_URL, { max: 5 });

// ---------------------------------------------------------------------------
// OpenAI (optional — embedding generation)
// ---------------------------------------------------------------------------
const openai = OPENAI_API_KEY ? new OpenAI({ apiKey: OPENAI_API_KEY }) : null;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Ensure a gbrain_source exists for a tenant, return its id */
async function ensureSource(tenantId: string): Promise<string> {
  const rows = await sql`
    SELECT id FROM gbrain_sources WHERE tenant_id = ${tenantId}
  `;
  if (rows.length > 0) return rows[0].id as string;

  const inserted = await sql`
    INSERT INTO gbrain_sources (tenant_id, slug, display_name, config)
    VALUES (${tenantId}, ${"tenant-" + tenantId.slice(0, 8)}, ${"User " + tenantId.slice(0, 8)}, '{"federated": false}'::jsonb)
    ON CONFLICT (tenant_id) DO UPDATE SET updated_at = now()
    RETURNING id
  `;
  return inserted[0].id as string;
}

/** Resolve tenant_id to source_id, with caching */
const sourceCache = new Map<string, string>();
async function getSourceId(tenantId: string): Promise<string> {
  const cached = sourceCache.get(tenantId);
  if (cached) return cached;
  const id = await ensureSource(tenantId);
  sourceCache.set(tenantId, id);
  return id;
}

/** Simple text chunker — splits by paragraphs, then by chunk_size */
function chunkText(text: string, chunkSize = CHUNK_SIZE, overlap = CHUNK_OVERLAP): string[] {
  if (!text) return [];
  const paragraphs = text.split(/\n\n+/).filter(Boolean);
  const chunks: string[] = [];
  let current = "";

  for (const para of paragraphs) {
    if ((current + "\n\n" + para).length > chunkSize && current.length > 0) {
      chunks.push(current.trim());
      // Keep overlap
      const words = current.split(/\s+/);
      const overlapWords = words.slice(-Math.ceil(overlap / 5));
      current = overlapWords.join(" ") + "\n\n" + para;
    } else {
      current = current ? current + "\n\n" + para : para;
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.length > 0 ? chunks : [text.slice(0, chunkSize)];
}

/** Generate embedding for a text string */
async function generateEmbedding(text: string): Promise<number[] | null> {
  if (!openai) return null;
  try {
    const resp = await openai.embeddings.create({
      model: EMBEDDING_MODEL,
      input: text.slice(0, 8000),
    });
    return resp.data[0].embedding;
  } catch (err) {
    console.error("[gbrain] embedding error:", err);
    return null;
  }
}

async function sha256Hex(text: string): Promise<string | null> {
  try {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  } catch {
    return null;
  }
}

function buildHealthStatus() {
  const deepProvider =
    process.env.HERMES_DEEP_PROVIDER ||
    (process.env.MODEL_AUTH_MODE === "openai_codex" || process.env.MODEL_AUTH_MODE === "hermes_auth_profile"
      ? "openai-codex"
      : process.env.MODEL_ADAPTER_FALLBACK_PROVIDER || "openai");
  const normalizedDeepProvider = ["openai", "openai-codex", "minimax"].includes(deepProvider) ? deepProvider : "openai";
  const openaiCodexAuthProfileConfigured = Boolean(
    process.env.OPENAI_CODEX_AUTH_PROFILE || process.env.HERMES_AUTH_PROFILE_ID || process.env.OPENCLAW_AUTH_PROFILE
  );
  const openaiCodexBridgeConfigured = Boolean(
    process.env.OPENAI_CODEX_BRIDGE_BASE_URL || process.env.HERMES_CODEX_GATEWAY_BASE_URL || process.env.OPENCLAW_CODEX_GATEWAY_BASE_URL
  );
  const openaiConfigured = Boolean(OPENAI_API_KEY);
  const minimaxConfigured = Boolean(
    process.env.MINIMAX_API_KEY ||
      process.env.ANTHROPIC_AUTH_TOKEN ||
      process.env.ANTHROPIC_API_KEY ||
      (["hermes-cli", "openclaw-cli"].includes((process.env.MINIMAX_API_FORMAT || "").toLowerCase()) &&
        ["1", "true", "yes"].includes(
          (process.env.HERMES_MINIMAX_CLI_ENABLED || process.env.OPENCLAW_MINIMAX_CLI_ENABLED || "").toLowerCase(),
        )),
  );
  const liveModelsEnabled = (process.env.GBRAIN_LIVE_MODELS_ENABLED || "false").toLowerCase() === "true";
  const providerReady =
    normalizedDeepProvider === "openai"
      ? openaiConfigured
      : normalizedDeepProvider === "openai-codex"
        ? openaiCodexAuthProfileConfigured && openaiCodexBridgeConfigured
        : minimaxConfigured;

  return {
    ok: true,
    engine: "postgres",
    adapter: "gbrain-hermes",
    adapter_version: ADAPTER_VERSION,
    embedding_enabled: !!openai,
    embedding_model: openai ? EMBEDDING_MODEL : null,
    hermes_upstream_target: HERMES_UPSTREAM_TARGET_VERSION,
    artifact_backend: process.env.HERMES_ARTIFACT_STORAGE_BACKEND || "file",
    live_models_enabled: liveModelsEnabled,
    model_auth_mode: process.env.MODEL_AUTH_MODE || "api_key",
    deep_provider: normalizedDeepProvider,
    openai_configured: openaiConfigured,
    openai_codex_auth_profile_configured: openaiCodexAuthProfileConfigured,
    openai_codex_bridge_configured: openaiCodexBridgeConfigured,
    openai_codex_configured: openaiCodexAuthProfileConfigured && openaiCodexBridgeConfigured,
    minimax_configured: minimaxConfigured,
    minimax_api_format:
      process.env.MINIMAX_API_FORMAT ||
      (process.env.ANTHROPIC_BASE_URL ||
      process.env.ANTHROPIC_AUTH_TOKEN ||
      process.env.ANTHROPIC_API_KEY ||
      (process.env.MINIMAX_OPENAI_BASE_URL || process.env.MINIMAX_BASE_URL || "").includes("/anthropic")
        ? "anthropic"
        : "openai"),
    system_model_auth_ready: liveModelsEnabled && providerReady,
  };
}

/** Hybrid search: vector + keyword + RRF fusion */
async function hybridSearch(
  tenantId: string,
  query: string,
  limit = 10,
  searchType = "hybrid"
): Promise<Array<Record<string, unknown>>> {
  const sourceId = await getSourceId(tenantId);

  let vectorResults: Array<Record<string, unknown>> = [];
  let keywordResults: Array<Record<string, unknown>> = [];

  // Vector search
  if ((searchType === "hybrid" || searchType === "vector") && openai) {
    const embedding = await generateEmbedding(query);
    if (embedding) {
      vectorResults = await sql`
        SELECT p.id, p.path, p.title, p.content, p.page_type, p.metadata,
               c.chunk_text,
               1 - (c.embedding <=> ${JSON.stringify(embedding)}::vector) AS score
        FROM gbrain_content_chunks c
        JOIN gbrain_pages p ON p.id = c.page_id
        WHERE p.source_id = ${sourceId} AND p.tenant_id = ${tenantId}
        ORDER BY c.embedding <=> ${JSON.stringify(embedding)}::vector
        LIMIT ${limit * 2}
      ` as Array<Record<string, unknown>>;
    }
  }

  // Keyword search
  if (searchType === "hybrid" || searchType === "keyword") {
    keywordResults = await sql`
      SELECT p.id, p.path, p.title, p.content, p.page_type, p.metadata,
             ts_rank(p.search_vector, plainto_tsquery('simple', ${query})) AS score
      FROM gbrain_pages p
      WHERE p.source_id = ${sourceId}
        AND p.tenant_id = ${tenantId}
        AND p.search_vector @@ plainto_tsquery('simple', ${query})
      ORDER BY ts_rank(p.search_vector, plainto_tsquery('simple', ${query})) DESC
      LIMIT ${limit * 2}
    ` as Array<Record<string, unknown>>;
  }

  // RRF fusion
  const K = 60;
  const rrfScores = new Map<string, { page: Record<string, unknown>; score: number }>();

  for (let i = 0; i < vectorResults.length; i++) {
    const r = vectorResults[i];
    const key = r.path as string;
    const existing = rrfScores.get(key);
    const rrf = 1 / (K + i + 1);
    if (existing) {
      existing.score += rrf;
    } else {
      rrfScores.set(key, { page: r, score: rrf });
    }
  }

  for (let i = 0; i < keywordResults.length; i++) {
    const r = keywordResults[i];
    const key = r.path as string;
    const existing = rrfScores.get(key);
    const rrf = 1 / (K + i + 1);
    if (existing) {
      existing.score += rrf;
    } else {
      rrfScores.set(key, { page: r, score: rrf });
    }
  }

  return Array.from(rrfScores.values())
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map(({ page, score }) => ({ ...page, rrf_score: score }));
}

// ---------------------------------------------------------------------------
// MCP Server
// ---------------------------------------------------------------------------
const server = new McpServer({
  name: "gbrain-hermes",
  version: "0.1.0",
});

// --- Tool: health ---
server.tool("health", {}, async () => {
  try {
    await sql`SELECT 1`;
    return {
      content: [{ type: "text", text: JSON.stringify(buildHealthStatus()) }],
    };
  } catch (err) {
    return {
      content: [{ type: "text", text: JSON.stringify({ ok: false, error: String(err) }) }],
      isError: true,
    };
  }
});

// --- Tool: ensure_source ---
server.tool(
  "ensure_source",
  { tenant_id: z.string().uuid() },
  async ({ tenant_id }) => {
    const sourceId = await getSourceId(tenant_id);
    return {
      content: [{ type: "text", text: JSON.stringify({ source_id: sourceId }) }],
    };
  }
);

// --- Tool: upsert_page ---
server.tool(
  "upsert_page",
  {
    tenant_id: z.string().uuid(),
    path: z.string().min(1),
    title: z.string().min(1),
    content: z.string().default(""),
    page_type: z.string().default("compiled_truth"),
    metadata: z.record(z.string(), z.unknown()).default({}),
  },
  async ({ tenant_id, path, title, content, page_type, metadata }) => {
    const sourceId = await getSourceId(tenant_id);
    const contentHash = content ? await sha256Hex(content) : null;

    // Upsert page
    const rows = await sql`
      INSERT INTO gbrain_pages (source_id, path, title, content, page_type, metadata, tenant_id, content_hash)
      VALUES (${sourceId}, ${path}, ${title}, ${content}, ${page_type}, ${JSON.stringify(metadata)}, ${tenant_id}, ${contentHash})
      ON CONFLICT (source_id, path) DO UPDATE SET
        title = EXCLUDED.title,
        content = EXCLUDED.content,
        page_type = EXCLUDED.page_type,
        metadata = EXCLUDED.metadata,
        content_hash = EXCLUDED.content_hash,
        updated_at = now()
      RETURNING id, path, title, page_type, updated_at
    `;

    const pageId = rows[0].id as string;

    // Chunk + embed content (async, non-blocking for response)
    if (content && content.length > 50) {
      const chunks = chunkText(content);
      // Fire and forget embedding — don't block the response
      (async () => {
        try {
          await sql`DELETE FROM gbrain_content_chunks WHERE page_id = ${pageId}`;
          for (let i = 0; i < chunks.length; i++) {
            const embedding = await generateEmbedding(chunks[i]);
            await sql`
              INSERT INTO gbrain_content_chunks (page_id, chunk_index, chunk_text, embedding, model, tenant_id)
              VALUES (${pageId}, ${i}, ${chunks[i]}, ${embedding ? JSON.stringify(embedding) : null}, ${EMBEDDING_MODEL}, ${tenant_id})
            `;
          }
        } catch (err) {
          console.error("[gbrain] chunk/embed error:", err);
        }
      })();
    }

    return {
      content: [{ type: "text", text: JSON.stringify({ page_id: pageId, path, updated: rows[0].updated_at }) }],
    };
  }
);

// --- Tool: get_page ---
server.tool(
  "get_page",
  {
    tenant_id: z.string().uuid(),
    path: z.string().min(1),
  },
  async ({ tenant_id, path }) => {
    const rows = await sql`
      SELECT id, path, title, content, page_type, metadata, created_at, updated_at
      FROM gbrain_pages
      WHERE tenant_id = ${tenant_id} AND path = ${path}
      LIMIT 1
    `;
    if (rows.length === 0) {
      return { content: [{ type: "text", text: JSON.stringify(null) }] };
    }
    return { content: [{ type: "text", text: JSON.stringify(rows[0]) }] };
  }
);

// --- Tool: search ---
server.tool(
  "search",
  {
    tenant_id: z.string().uuid(),
    query: z.string().min(1),
    limit: z.number().default(10),
    search_type: z.enum(["hybrid", "keyword", "vector"]).default("hybrid"),
  },
  async ({ tenant_id, query, limit, search_type }) => {
    const results = await hybridSearch(tenant_id, query, limit, search_type);
    return { content: [{ type: "text", text: JSON.stringify(results) }] };
  }
);

// --- Tool: add_timeline_entry ---
server.tool(
  "add_timeline_entry",
  {
    tenant_id: z.string().uuid(),
    page_path: z.string().min(1),
    event_date: z.string(),
    event_type: z.string().default("MANUAL"),
    title: z.string().min(1),
    content: z.string().default(""),
    importance: z.number().default(5),
    metadata: z.record(z.string(), z.unknown()).default({}),
  },
  async ({ tenant_id, page_path, event_date, event_type, title, content, importance, metadata }) => {
    // Find page by path
    const pageRows = await sql`
      SELECT id FROM gbrain_pages WHERE tenant_id = ${tenant_id} AND path = ${page_path} LIMIT 1
    `;
    if (pageRows.length === 0) {
      return {
        content: [{ type: "text", text: JSON.stringify({ error: "page_not_found", path: page_path }) }],
        isError: true,
      };
    }
    const pageId = pageRows[0].id;

    const rows = await sql`
      INSERT INTO gbrain_timeline_entries (page_id, event_date, event_type, title, content, importance, metadata, tenant_id)
      VALUES (${pageId}, ${event_date}, ${event_type}, ${title}, ${content}, ${importance}, ${JSON.stringify(metadata)}, ${tenant_id})
      ON CONFLICT (page_id, event_date, title) DO NOTHING
      RETURNING id
    `;

    return {
      content: [{ type: "text", text: JSON.stringify({ entry_id: rows[0]?.id || null, created: rows.length > 0 }) }],
    };
  }
);

// --- Tool: create_link ---
server.tool(
  "create_link",
  {
    tenant_id: z.string().uuid(),
    source_path: z.string().min(1),
    target_path: z.string().min(1),
    link_type: z.string().default("MENTIONS"),
    confidence: z.number().default(0.7),
    metadata: z.record(z.string(), z.unknown()).default({}),
  },
  async ({ tenant_id, source_path, target_path, link_type, confidence, metadata }) => {
    // Resolve page ids
    const pages = await sql`
      SELECT id, path FROM gbrain_pages
      WHERE tenant_id = ${tenant_id} AND path IN (${source_path}, ${target_path})
    `;
    const pageMap = new Map(pages.map((r) => [r.path, r.id]));
    const sourcePageId = pageMap.get(source_path);
    const targetPageId = pageMap.get(target_path);

    if (!sourcePageId || !targetPageId) {
      return {
        content: [{ type: "text", text: JSON.stringify({ error: "page_not_found", source: !!sourcePageId, target: !!targetPageId }) }],
        isError: true,
      };
    }

    await sql`
      INSERT INTO gbrain_links (source_page_id, target_page_id, link_type, confidence, metadata, tenant_id)
      VALUES (${sourcePageId}, ${targetPageId}, ${link_type}, ${confidence}, ${JSON.stringify(metadata)}, ${tenant_id})
      ON CONFLICT (source_page_id, target_page_id, link_type) DO NOTHING
    `;

    return {
      content: [{ type: "text", text: JSON.stringify({ created: true, source: source_path, target: target_path, link_type }) }],
    };
  }
);

// --- Tool: get_page_context (page + timeline + links) ---
server.tool(
  "get_page_context",
  {
    tenant_id: z.string().uuid(),
    path: z.string().min(1),
    include_timeline: z.boolean().default(true),
    include_links: z.boolean().default(true),
    timeline_limit: z.number().default(10),
  },
  async ({ tenant_id, path, include_timeline, include_links, timeline_limit }) => {
    // Get page
    const pageRows = await sql`
      SELECT id, path, title, content, page_type, metadata, created_at, updated_at
      FROM gbrain_pages WHERE tenant_id = ${tenant_id} AND path = ${path} LIMIT 1
    `;
    if (pageRows.length === 0) {
      return { content: [{ type: "text", text: JSON.stringify(null) }] };
    }
    const page = pageRows[0];
    const pageId = page.id;

    const result: Record<string, unknown> = { page };

    // Timeline
    if (include_timeline) {
      const timeline = await sql`
        SELECT event_date, event_type, title, content, importance, metadata, created_at
        FROM gbrain_timeline_entries
        WHERE page_id = ${pageId}
        ORDER BY event_date DESC
        LIMIT ${timeline_limit}
      `;
      result.timeline = timeline;
    }

    // Links (outgoing + incoming)
    if (include_links) {
      const outgoing = await sql`
        SELECT l.link_type, l.confidence, p.path AS target_path, p.title AS target_title
        FROM gbrain_links l
        JOIN gbrain_pages p ON p.id = l.target_page_id
        WHERE l.source_page_id = ${pageId}
      `;
      const incoming = await sql`
        SELECT l.link_type, l.confidence, p.path AS source_path, p.title AS source_title
        FROM gbrain_links l
        JOIN gbrain_pages p ON p.id = l.source_page_id
        WHERE l.target_page_id = ${pageId}
      `;
      result.links_outgoing = outgoing;
      result.links_incoming = incoming;
    }

    return { content: [{ type: "text", text: JSON.stringify(result) }] };
  }
);

// ---------------------------------------------------------------------------
// Start server
// ---------------------------------------------------------------------------
async function main() {
  try {
    await waitForDatabase(
      () => sql`SELECT 1`,
      getDatabaseWaitConfig(process.env, HEALTH_CHECK_MODE),
    );
    if (HEALTH_CHECK_MODE || HEALTH_JSON_MODE) {
      console.log(HEALTH_JSON_MODE ? JSON.stringify(buildHealthStatus()) : "ok");
      await sql.end();
      process.exit(0);
    }
  } catch (err) {
    if (HEALTH_CHECK_MODE) {
      console.error("[gbrain] health-check failed:", err);
    } else {
      console.error("[gbrain] Database connection FAILED:", err);
    }
    await sql.end().catch(() => undefined);
    process.exit(1);
  }

  console.error("[gbrain] Starting MCP adapter for OpenClaw...");
  console.error(`[gbrain] Database: ${DATABASE_URL.replace(/:[^:@]+@/, ":****@")}`);
  console.error(`[gbrain] Embedding: ${openai ? EMBEDDING_MODEL : "disabled (no OPENAI_API_KEY)"}`);
  console.error("[gbrain] Database connection OK");

  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("[gbrain] MCP server ready on stdio");
}

main().catch((err) => {
  console.error("[gbrain] Fatal error:", err);
  process.exit(1);
});

// Graceful shutdown
process.on("SIGTERM", async () => {
  console.error("[gbrain] Shutting down...");
  await sql.end();
  process.exit(0);
});

process.on("SIGINT", async () => {
  console.error("[gbrain] Interrupted, shutting down...");
  await sql.end();
  process.exit(0);
});
