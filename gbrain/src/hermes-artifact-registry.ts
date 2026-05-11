import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

import type { ArtifactDraft, ArtifactRegistryRecord } from "./hermes-types.js";

export interface PreparedStatement {
  text: string;
  values: unknown[];
}

export interface ArtifactRegistrySink {
  write(record: ArtifactRegistryRecord): Promise<ArtifactRegistryRecord>;
}

export interface ArtifactObjectStore {
  write(uri: string, content: string, metadata: Record<string, unknown>): Promise<void>;
  read?(uri: string): Promise<string | null>;
}

export class InMemoryArtifactRegistrySink implements ArtifactRegistrySink {
  public readonly records: ArtifactRegistryRecord[] = [];

  async write(record: ArtifactRegistryRecord): Promise<ArtifactRegistryRecord> {
    this.records.push(record);
    return record;
  }
}

export class InMemoryArtifactObjectStore implements ArtifactObjectStore {
  public readonly objects = new Map<string, { content: string; metadata: Record<string, unknown> }>();

  async write(uri: string, content: string, metadata: Record<string, unknown>): Promise<void> {
    this.objects.set(uri, { content, metadata });
  }

  async read(uri: string): Promise<string | null> {
    return this.objects.get(uri)?.content ?? null;
  }
}

export class FileArtifactObjectStore implements ArtifactObjectStore {
  constructor(private readonly rootDir: string) {}

  async write(uri: string, content: string, metadata: Record<string, unknown>): Promise<void> {
    const path = this.pathForUri(uri);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, content, "utf8");
    await writeFile(`${path}.metadata.json`, JSON.stringify(metadata, null, 2), "utf8");
  }

  async read(uri: string): Promise<string | null> {
    try {
      return await readFile(this.pathForUri(uri), "utf8");
    } catch {
      return null;
    }
  }

  private pathForUri(uri: string): string {
    const storage = parseStorageUri(uri);
    return join(this.rootDir, storage.backend, storage.bucket ?? "_", storage.path);
  }
}

export class SupabaseArtifactObjectStore implements ArtifactObjectStore {
  constructor(
    private readonly supabaseUrl: string,
    private readonly serviceRoleKey: string,
  ) {}

  async write(uri: string, content: string, metadata: Record<string, unknown>): Promise<void> {
    const storage = parseStorageUri(uri);
    if (!storage.bucket) {
      throw new Error(`Supabase artifact uri requires a bucket: ${uri}`);
    }
    const endpoint = `${this.supabaseUrl.replace(/\/+$/, "")}/storage/v1/object/${storage.bucket}/${storage.path}`;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        apikey: this.serviceRoleKey,
        Authorization: `Bearer ${this.serviceRoleKey}`,
        "Content-Type": "text/markdown; charset=utf-8",
        "Cache-Control": "no-store",
        "x-upsert": "true",
        "x-metadata": Buffer.from(JSON.stringify(metadata)).toString("base64"),
      },
      body: content,
    });
    if (!response.ok) {
      throw new Error(`Supabase artifact upload failed ${response.status}: ${(await response.text()).slice(0, 500)}`);
    }
  }
}

export class PostgresArtifactRegistrySink implements ArtifactRegistrySink {
  constructor(private readonly databaseUrl: string) {}

  async write(record: ArtifactRegistryRecord): Promise<ArtifactRegistryRecord> {
    const postgres = (await import("postgres")).default;
    const sql = postgres(this.databaseUrl, { max: 1 });
    const statement = buildArtifactRegistryInsert(record);
    try {
      await sql.unsafe(statement.text, statement.values as never[]);
    } finally {
      await sql.end({ timeout: 5 });
    }
    return record;
  }
}

function hashContent(content: string): string {
  return createHash("sha256").update(content).digest("hex");
}

function normalizeExpiresAt(draft: ArtifactDraft): string {
  if (draft.expiresAt) return draft.expiresAt;

  const days = draft.retentionClass === "short" ? 30 : draft.retentionClass === "long" ? 180 : 90;
  const expiresAt = new Date();
  expiresAt.setUTCDate(expiresAt.getUTCDate() + days);
  return expiresAt.toISOString();
}

function buildStorageUri(artifact: ArtifactRegistryRecord, baseUri: string): string {
  const day = artifact.createdAt.slice(0, 10);
  return `${baseUri}/${artifact.tenantId}/${artifact.artifactType}/${day}/${artifact.artifactId}.md`;
}

function readString(metadata: Record<string, unknown>, key: string): string | undefined {
  const value = metadata[key];
  return typeof value === "string" ? value : undefined;
}

function readArray(metadata: Record<string, unknown>, key: string): unknown[] | undefined {
  const value = metadata[key];
  return Array.isArray(value) ? value : undefined;
}

function extractNestedMetadata(metadata: Record<string, unknown>): Record<string, unknown> {
  const nested = metadata.metadata;
  if (nested && typeof nested === "object" && !Array.isArray(nested)) {
    return nested as Record<string, unknown>;
  }

  return metadata;
}

function buildArtifactMetadata(
  record: ArtifactRegistryRecord,
  storage: { backend: string; bucket: string | null; path: string },
  metadata: Record<string, unknown>,
): Record<string, unknown> {
  return {
    title: record.title,
    owner_agent: record.ownerAgent,
    created_by_agent: record.createdByAgent ?? record.ownerAgent,
    tenant_id: record.tenantId,
    artifact_type: record.artifactType,
    source_run_id: readString(metadata, "source_run_id") ?? record.ownerRunId,
    model_id: readString(metadata, "model_id") ?? record.modelId,
    model_provider: readString(metadata, "model_provider") ?? null,
    lineage: readArray(metadata, "lineage") ?? record.sourceRefs,
    source_refs: readArray(metadata, "source_refs") ?? record.sourceRefs,
    retention_class: record.retentionClass ?? "standard",
    retention_until: record.expiresAt,
    storage_backend: storage.backend,
    storage_bucket: storage.bucket,
    storage_path: storage.path,
    metadata: extractNestedMetadata(metadata),
  };
}

export function buildArtifactRegistryInsert(record: ArtifactRegistryRecord): PreparedStatement {
  const storage = parseStorageUri(record.storageUri);
  const metadata = buildArtifactMetadata(record, storage, record.metadata ?? {});
  return {
    text: [
      "INSERT INTO artifact_registry (",
      "  id, tenant_id, source_run_id, artifact_key, artifact_type, artifact_status, visibility,",
      "  storage_backend, storage_bucket, storage_path, content_hash, source_lineage,",
      "  artifact_metadata, retention_until, created_at",
      ") VALUES (",
      "  $1, $2, $3, $4, $5, $6, $7,",
      "  $8, $9, $10, $11, $12,",
      "  $13, $14, $15",
      ")",
    ].join("\n"),
    values: [
      record.artifactId,
      record.tenantId,
      record.ownerRunId,
      record.artifactId,
      record.artifactType,
      "ready",
      "tenant",
      storage.backend,
      storage.bucket,
      storage.path,
      record.contentHash,
      JSON.stringify(record.sourceRefs),
      JSON.stringify(metadata),
      record.expiresAt,
      record.createdAt,
    ],
  };
}

function parseStorageUri(uri: string): { backend: string; bucket: string | null; path: string } {
  const match = uri.match(/^([^:]+):\/\/([^/]+)\/(.+)$/);
  if (!match) {
    return {
      backend: "object_storage",
      bucket: null,
      path: uri,
    };
  }
  return {
    backend: match[1],
    bucket: match[2],
    path: match[3],
  };
}

export class ArtifactRegistryWriterClient {
  constructor(
    private readonly sink: ArtifactRegistrySink = new InMemoryArtifactRegistrySink(),
    private readonly baseUri = process.env.HERMES_ARTIFACT_BASE_URI || "supabase://artifacts",
    private readonly objectStore: ArtifactObjectStore = new InMemoryArtifactObjectStore(),
  ) {}

  async register(draft: ArtifactDraft): Promise<ArtifactRegistryRecord> {
    const createdAt = new Date().toISOString();
    const artifactId = randomUUID();
    const inputMetadata = draft.metadata ?? {};
    const record: ArtifactRegistryRecord = {
      ...draft,
      artifactId,
      createdAt,
      contentHash: hashContent(draft.content),
      expiresAt: normalizeExpiresAt(draft),
      storageUri: "",
      createdByAgent: draft.createdByAgent ?? draft.ownerAgent,
    };
    record.storageUri = buildStorageUri(record, this.baseUri);
    record.metadata = buildArtifactMetadata(record, parseStorageUri(record.storageUri), inputMetadata);
    await this.objectStore.write(record.storageUri, draft.content, record.metadata ?? {});
    return this.sink.write(record);
  }
}

export function createArtifactRegistryWriterFromEnv(): ArtifactRegistryWriterClient {
  const baseUri = process.env.HERMES_ARTIFACT_BASE_URI || "supabase://artifacts";
  const sink = process.env.DATABASE_URL
    ? new PostgresArtifactRegistrySink(process.env.DATABASE_URL)
    : new InMemoryArtifactRegistrySink();

  const backend = (process.env.HERMES_ARTIFACT_STORAGE_BACKEND || "").toLowerCase();
  if (backend === "file") {
    return new ArtifactRegistryWriterClient(
      sink,
      baseUri,
      new FileArtifactObjectStore(process.env.HERMES_ARTIFACT_FILE_ROOT || ".artifacts/hermes"),
    );
  }
  if (backend === "supabase") {
    const supabaseUrl = process.env.SUPABASE_URL || "";
    const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY || "";
    if (!supabaseUrl || !serviceRoleKey) {
      throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for Supabase artifact storage");
    }
    return new ArtifactRegistryWriterClient(
      sink,
      baseUri,
      new SupabaseArtifactObjectStore(supabaseUrl, serviceRoleKey),
    );
  }

  return new ArtifactRegistryWriterClient(sink, baseUri, new InMemoryArtifactObjectStore());
}
