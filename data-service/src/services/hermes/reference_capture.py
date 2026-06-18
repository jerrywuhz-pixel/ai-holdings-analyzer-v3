from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID


JsonDict = dict[str, Any]


class WebReferencePersistence:
    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or ""

    @classmethod
    def from_env(cls) -> "WebReferencePersistence":
        return cls()

    async def save(
        self,
        *,
        tenant_id: str,
        reference: JsonDict,
        entry_surface: str,
        prompt: str,
    ) -> JsonDict:
        if not self._database_url:
            return {"status": "skipped", "reason": "DATABASE_URL_missing"}
        try:
            UUID(tenant_id)
        except (TypeError, ValueError):
            return {"status": "skipped", "reason": "tenant_id_is_not_uuid"}
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            return {"status": "skipped", "reason": f"psycopg_not_installed: {exc}"}

        source_refs = _source_refs(reference)
        content_hash = str(reference.get("content_hash") or _sha256_json(reference))
        artifact_key = f"web-reference:{content_hash[:32]}"
        artifact_status = "ready" if reference.get("ok") else "failed"
        artifact_metadata = {
            "schema_version": "web_reference_snapshot_v1",
            "reference_only": True,
            "entry_surface": entry_surface,
            "prompt": prompt[:1000],
            "url": reference.get("url"),
            "canonical_url": reference.get("canonical_url"),
            "title": reference.get("title"),
            "status": reference.get("status"),
            "status_code": reference.get("status_code"),
            "mode_used": reference.get("mode_used"),
            "attempted_modes": reference.get("attempted_modes") or [],
            "fetched_at": reference.get("fetched_at"),
            "failed": reference.get("failed"),
            "audit": reference.get("audit") or {},
            "content_markdown": str(reference.get("content_markdown") or "")[:20000],
            "content_text": str(reference.get("content_text") or "")[:20000],
        }

        try:
            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    row = _fetch_one(
                        cur.execute(
                            """
                            INSERT INTO public.artifact_registry (
                              tenant_id, artifact_key, artifact_type, artifact_status,
                              visibility, storage_backend, storage_path, mime_type,
                              content_hash, source_lineage, artifact_metadata, retention_until
                            )
                            VALUES (
                              %(tenant_id)s, %(artifact_key)s, 'web_reference_snapshot', %(artifact_status)s,
                              'tenant', 'inline_metadata', %(storage_path)s, 'application/json',
                              %(content_hash)s, %(source_lineage)s, %(artifact_metadata)s,
                              now() + interval '90 days'
                            )
                            ON CONFLICT (tenant_id, artifact_key) DO UPDATE
                            SET
                              artifact_status = EXCLUDED.artifact_status,
                              source_lineage = EXCLUDED.source_lineage,
                              artifact_metadata = EXCLUDED.artifact_metadata,
                              updated_at = now()
                            RETURNING id
                            """,
                            {
                                "tenant_id": tenant_id,
                                "artifact_key": artifact_key,
                                "artifact_status": artifact_status,
                                "storage_path": f"inline://web-reference/{content_hash}.json",
                                "content_hash": content_hash,
                                "source_lineage": Jsonb(source_refs),
                                "artifact_metadata": Jsonb(artifact_metadata),
                            },
                        )
                    )
        except Exception as exc:  # noqa: BLE001 - persistence must not hide a successful reference read.
            return {
                "status": "failed",
                "reason": f"postgres_error:{exc.__class__.__name__}",
                "message": str(exc)[:500],
                "artifact_key": artifact_key,
                "artifact_status": artifact_status,
            }
        return {
            "status": "saved",
            "backend": "postgres",
            "artifact_id": str(row.get("id")),
            "artifact_key": artifact_key,
            "artifact_status": artifact_status,
        }


def summarize_web_reference(reference: JsonDict, *, max_chars: int = 700) -> JsonDict:
    title = str(reference.get("title") or "").strip()
    text = str(reference.get("content_text") or reference.get("content_markdown") or "").strip()
    summary = _first_sentences(text, max_chars=max_chars)
    return {
        "schema_version": "web_reference_summary_v1",
        "reference_only": True,
        "title": title or None,
        "url": reference.get("canonical_url") or reference.get("url"),
        "content_hash": reference.get("content_hash"),
        "status": reference.get("status"),
        "fetched_at": reference.get("fetched_at"),
        "summary": summary,
        "failed": reference.get("failed"),
        "source_refs": _source_refs(reference),
    }


def _source_refs(reference: JsonDict) -> list[JsonDict]:
    refs = reference.get("source_refs")
    if isinstance(refs, list):
        return [item for item in refs if isinstance(item, dict)]
    ref = reference.get("canonical_url") or reference.get("url") or "unknown"
    return [{"source": "web", "ref": str(ref)}]


def _first_sentences(text: str, *, max_chars: int) -> str:
    if not text:
        return ""
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    cut = normalized[:max_chars]
    for marker in ("。", "！", "？", ". ", "! ", "? "):
        index = cut.rfind(marker)
        if index >= max(80, max_chars // 2):
            return cut[: index + len(marker)].strip()
    return f"{cut.rstrip()}..."


def _fetch_one(cursor: Any) -> JsonDict:
    row = cursor.fetchone()
    if not row:
        return {}
    return dict(row)


def _sha256_json(value: JsonDict) -> str:
    import json

    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
