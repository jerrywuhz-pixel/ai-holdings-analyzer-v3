from __future__ import annotations

"""
Historical manifest + cached bars storage contract.

P0 目标：
1. 统一 manifest 记录结构，兼容现有历史接口字段。
2. 查询优先读已保存 manifest/object，命中失败时显式返回 cache_miss/degraded。
3. 提供内存与文件系统 stub，测试不依赖真实对象存储。
"""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional, Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

StorageBackend = Literal["local", "s3", "supabase_storage", "r2", "memory", "file"]
HistoricalFreshness = Literal["fresh", "stale", "unknown"]
HistoricalStatus = Literal["ready", "partial", "failed"]
HistoricalCacheStatus = Literal["hit", "cache_miss", "degraded"]


def _normalize_symbol(value: str) -> str:
    return value.upper().strip()


def _normalize_market(value: str) -> str:
    return value.upper().strip()


def _map_quality_to_status(value: Optional[str]) -> HistoricalStatus:
    if value == "failed":
        return "failed"
    if value == "partial":
        return "partial"
    return "ready"


def _map_quality_to_freshness(value: Optional[str]) -> HistoricalFreshness:
    if value == "stale":
        return "stale"
    if value == "validated":
        return "fresh"
    return "unknown"


def _map_status_to_quality(status: HistoricalStatus, freshness: HistoricalFreshness) -> str:
    if status == "failed":
        return "failed"
    if status == "partial":
        return "partial"
    if freshness == "stale":
        return "stale"
    return "validated"


class HistoricalRange(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_bounds(self) -> "HistoricalRange":
        if self.start > self.end:
            raise ValueError("range.start must be <= range.end")
        return self


class HistoricalManifestCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    tenant_id: Optional[str] = None
    universe_id: Optional[str] = None
    job_id: Optional[str] = None
    source: Optional[str] = None
    source_key: Optional[str] = None
    market: str
    symbol: str
    instrument_type: str = "stock"
    data_kind: Optional[str] = None
    bar_interval: Optional[str] = None
    interval: Optional[str] = None
    adjustment: str = "raw"
    range: Optional[HistoricalRange] = None
    coverage_start: Optional[date] = None
    coverage_end: Optional[date] = None
    storage_backend: StorageBackend = "memory"
    storage_root: str = "market-data/curated"
    storage_uri: Optional[str] = None
    schema_version: str = "v3_p0"
    row_count: Optional[int] = None
    freshness: Optional[HistoricalFreshness] = None
    status: Optional[HistoricalStatus] = None
    quality_status: Optional[Literal["validated", "partial", "stale", "failed"]] = None
    quality_report: dict[str, Any] = Field(default_factory=dict)
    bars: Optional[list[dict[str, Any]]] = None

    @model_validator(mode="after")
    def normalize_contract(self) -> "HistoricalManifestCreateRequest":
        self.symbol = _normalize_symbol(self.symbol)
        self.market = _normalize_market(self.market)

        resolved_source = (self.source or self.source_key or "").strip()
        if not resolved_source:
            raise ValueError("source or source_key is required")
        self.source = resolved_source
        self.source_key = resolved_source

        resolved_interval = (self.bar_interval or self.interval or "").strip()
        if not resolved_interval:
            raise ValueError("bar_interval or interval is required")
        self.bar_interval = resolved_interval
        self.interval = resolved_interval

        if self.range is None:
            if self.coverage_start is None or self.coverage_end is None:
                raise ValueError("range or coverage_start/coverage_end is required")
            self.range = HistoricalRange(start=self.coverage_start, end=self.coverage_end)
        self.coverage_start = self.range.start
        self.coverage_end = self.range.end

        if not self.data_kind:
            self.data_kind = f"bar_{self.bar_interval}"

        resolved_status = self.status or _map_quality_to_status(self.quality_status)
        resolved_freshness = self.freshness or _map_quality_to_freshness(self.quality_status)
        self.status = resolved_status
        self.freshness = resolved_freshness
        self.quality_status = _map_status_to_quality(resolved_status, resolved_freshness)
        return self


class HistoricalManifestRecord(BaseModel):
    id: str
    tenant_id: Optional[str] = None
    universe_id: Optional[str] = None
    job_id: str
    source: str
    source_key: str
    market: str
    symbol: str
    instrument_type: str
    data_kind: str
    bar_interval: str
    interval: str
    adjustment: str
    range: HistoricalRange
    coverage_start: date
    coverage_end: date
    storage_backend: str
    storage_uri: str
    schema_version: str
    freshness: HistoricalFreshness
    status: HistoricalStatus
    quality_status: str
    quality_report: dict[str, Any] = Field(default_factory=dict)
    row_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class HistoricalCoverageResponse(BaseModel):
    found: bool
    manifest: Optional[HistoricalManifestRecord] = None
    gap_reason: Optional[str] = None


class HistoricalQueryResponse(BaseModel):
    found: bool
    cache_status: HistoricalCacheStatus
    manifest: Optional[HistoricalManifestRecord] = None
    bars: list[dict[str, Any]] = Field(default_factory=list)
    reason: Optional[str] = None


class HistoricalBlobStore(Protocol):
    async def put(self, uri: str, payload: list[dict[str, Any]]) -> None: ...

    async def get(self, uri: str) -> Optional[list[dict[str, Any]]]: ...


class MemoryHistoricalBlobStore:
    def __init__(self) -> None:
        self._objects: dict[str, list[dict[str, Any]]] = {}

    async def put(self, uri: str, payload: list[dict[str, Any]]) -> None:
        self._objects[uri] = json.loads(json.dumps(payload))

    async def get(self, uri: str) -> Optional[list[dict[str, Any]]]:
        payload = self._objects.get(uri)
        if payload is None:
            return None
        return json.loads(json.dumps(payload))


class FileSystemHistoricalBlobStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _path_for_uri(self, uri: str) -> Path:
        scheme, _, rest = uri.partition("://")
        relative_parts = [part for part in rest.split("/") if part]
        base = self._root / (scheme or "file")
        return base.joinpath(*relative_parts)

    async def put(self, uri: str, payload: list[dict[str, Any]]) -> None:
        path = self._path_for_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True, default=str), encoding="utf-8")

    async def get(self, uri: str) -> Optional[list[dict[str, Any]]]:
        path = self._path_for_uri(uri)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


class SupabaseStorageHistoricalBlobStore:
    def __init__(
        self,
        supabase_url: str,
        service_role_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._supabase_url = supabase_url.rstrip("/")
        self._service_role_key = service_role_key
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    async def put(self, uri: str, payload: list[dict[str, Any]]) -> None:
        bucket, path = self._bucket_and_path(uri)
        body = json.dumps(payload, ensure_ascii=True, default=str).encode("utf-8")
        async with httpx.AsyncClient(timeout=self._timeout_seconds, transport=self._transport) as client:
            response = await client.post(
                f"{self._supabase_url}/storage/v1/object/{bucket}/{path}",
                content=body,
                headers={
                    "apikey": self._service_role_key,
                    "Authorization": f"Bearer {self._service_role_key}",
                    "Content-Type": "application/json",
                    "Cache-Control": "no-store",
                    "x-upsert": "true",
                },
            )
            response.raise_for_status()

    async def get(self, uri: str) -> Optional[list[dict[str, Any]]]:
        bucket, path = self._bucket_and_path(uri)
        async with httpx.AsyncClient(timeout=self._timeout_seconds, transport=self._transport) as client:
            response = await client.get(
                f"{self._supabase_url}/storage/v1/object/{bucket}/{path}",
                headers={
                    "apikey": self._service_role_key,
                    "Authorization": f"Bearer {self._service_role_key}",
                    "Accept": "application/json",
                },
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                return None
            return [dict(item) for item in payload if isinstance(item, dict)]

    def _bucket_and_path(self, uri: str) -> tuple[str, str]:
        scheme, separator, rest = uri.partition("://")
        if not separator:
            raise ValueError(f"Invalid storage uri: {uri}")
        parts = [part for part in rest.split("/") if part]
        if len(parts) < 2:
            raise ValueError(f"{scheme} storage uri must include bucket and path: {uri}")
        return parts[0], "/".join(parts[1:])


def create_historical_blob_store_from_env() -> HistoricalBlobStore:
    backend = os.getenv("HISTORICAL_STORAGE_BACKEND", "").strip().lower()
    if backend == "file":
        return FileSystemHistoricalBlobStore(os.getenv("HISTORICAL_STORAGE_FILE_ROOT", ".historical-cache"))
    if backend in {"supabase", "supabase_storage"}:
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not supabase_url or not service_role_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for historical Supabase Storage")
        return SupabaseStorageHistoricalBlobStore(supabase_url, service_role_key)
    return MemoryHistoricalBlobStore()


class HistoricalDataStore:
    def __init__(self, blob_store: HistoricalBlobStore | None = None) -> None:
        self._manifests: dict[str, HistoricalManifestRecord] = {}
        self._blob_store = blob_store or MemoryHistoricalBlobStore()

    def build_storage_uri(self, payload: HistoricalManifestCreateRequest) -> str:
        if payload.storage_uri:
            return payload.storage_uri

        tenant_segment = payload.tenant_id or "shared"
        return (
            f"{payload.storage_backend}://{payload.storage_root}/"
            f"tenant={tenant_segment}/source={payload.source}/market={payload.market}/symbol={payload.symbol}/"
            f"bar_interval={payload.bar_interval}/range={payload.coverage_start}_{payload.coverage_end}.parquet"
        )

    async def register_manifest(
        self,
        payload: HistoricalManifestCreateRequest,
    ) -> HistoricalManifestRecord:
        now = datetime.now(timezone.utc)
        storage_uri = self.build_storage_uri(payload)
        materialized_bars = payload.bars or None
        effective_row_count = payload.row_count if payload.row_count is not None else (
            len(materialized_bars) if materialized_bars is not None else None
        )

        record = HistoricalManifestRecord(
            id=str(uuid4()),
            tenant_id=payload.tenant_id,
            universe_id=payload.universe_id,
            job_id=payload.job_id or f"manual-{uuid4().hex[:10]}",
            source=payload.source or payload.source_key or "unknown",
            source_key=payload.source_key or payload.source or "unknown",
            market=payload.market,
            symbol=payload.symbol,
            instrument_type=payload.instrument_type,
            data_kind=payload.data_kind or f"bar_{payload.bar_interval}",
            bar_interval=payload.bar_interval or payload.interval or "1d",
            interval=payload.interval or payload.bar_interval or "1d",
            adjustment=payload.adjustment,
            range=payload.range or HistoricalRange(start=payload.coverage_start, end=payload.coverage_end),  # type: ignore[arg-type]
            coverage_start=payload.coverage_start,  # type: ignore[arg-type]
            coverage_end=payload.coverage_end,  # type: ignore[arg-type]
            storage_backend=payload.storage_backend,
            storage_uri=storage_uri,
            schema_version=payload.schema_version,
            freshness=payload.freshness or "unknown",
            status=payload.status or "ready",
            quality_status=payload.quality_status or "validated",
            quality_report=payload.quality_report,
            row_count=effective_row_count,
            created_at=now,
            updated_at=now,
        )
        self._manifests[record.id] = record

        if materialized_bars is not None:
            await self._blob_store.put(record.storage_uri, materialized_bars)
        return record

    async def save_dataset(
        self,
        payload: HistoricalManifestCreateRequest,
        *,
        bars: list[dict[str, Any]],
    ) -> HistoricalManifestRecord:
        enriched_payload = payload.model_copy(update={"bars": bars, "row_count": len(bars)})
        return await self.register_manifest(enriched_payload)

    async def get_manifest(self, manifest_id: str) -> Optional[HistoricalManifestRecord]:
        return self._manifests.get(manifest_id)

    async def find_coverage(
        self,
        *,
        symbol: str,
        market: str,
        data_kind: str,
        interval: str,
    ) -> HistoricalCoverageResponse:
        candidates = [
            item
            for item in self._manifests.values()
            if item.symbol == _normalize_symbol(symbol)
            and item.market == _normalize_market(market)
            and item.data_kind == data_kind
            and item.interval == interval
        ]
        if not candidates:
            return HistoricalCoverageResponse(found=False, gap_reason="manifest_not_found")

        latest = self._sort_candidates(candidates)[0]
        return HistoricalCoverageResponse(found=True, manifest=latest)

    async def read_bars(
        self,
        *,
        symbol: str,
        market: str,
        bar_interval: str,
        start_date: date,
        end_date: date,
        tenant_id: Optional[str] = None,
    ) -> HistoricalQueryResponse:
        requested_range = HistoricalRange(start=start_date, end=end_date)
        candidates = self._matching_manifests(
            symbol=_normalize_symbol(symbol),
            market=_normalize_market(market),
            bar_interval=bar_interval,
            tenant_id=tenant_id,
        )
        if not candidates:
            return HistoricalQueryResponse(
                found=False,
                cache_status="cache_miss",
                reason="manifest_not_found",
            )

        covering = [
            item
            for item in candidates
            if item.coverage_start <= requested_range.start and item.coverage_end >= requested_range.end
        ]
        if not covering:
            return HistoricalQueryResponse(
                found=False,
                cache_status="cache_miss",
                manifest=self._sort_candidates(candidates)[0],
                reason="coverage_gap",
            )

        manifest = self._sort_candidates(covering)[0]
        bars = await self._blob_store.get(manifest.storage_uri)
        if bars is None:
            return HistoricalQueryResponse(
                found=False,
                cache_status="degraded",
                manifest=manifest,
                reason="object_missing",
            )

        try:
            filtered_bars = self._filter_bars_by_range(bars, requested_range)
        except ValueError:
            return HistoricalQueryResponse(
                found=False,
                cache_status="degraded",
                manifest=manifest,
                reason="invalid_cached_payload",
            )

        if not filtered_bars:
            return HistoricalQueryResponse(
                found=False,
                cache_status="degraded",
                manifest=manifest,
                reason="empty_cached_range",
            )

        cache_status: HistoricalCacheStatus = "hit"
        if manifest.status != "ready" or manifest.freshness == "stale":
            cache_status = "degraded"

        return HistoricalQueryResponse(
            found=True,
            cache_status=cache_status,
            manifest=manifest,
            bars=filtered_bars,
            reason=None if cache_status == "hit" else "manifest_not_fresh",
        )

    def _matching_manifests(
        self,
        *,
        symbol: str,
        market: str,
        bar_interval: str,
        tenant_id: Optional[str],
    ) -> list[HistoricalManifestRecord]:
        candidates = [
            item
            for item in self._manifests.values()
            if item.symbol == symbol and item.market == market and item.bar_interval == bar_interval
        ]
        if tenant_id is None:
            return candidates
        return [item for item in candidates if item.tenant_id in {tenant_id, None}]

    def _sort_candidates(self, candidates: list[HistoricalManifestRecord]) -> list[HistoricalManifestRecord]:
        return sorted(
            candidates,
            key=lambda item: (item.tenant_id is not None, item.updated_at, item.created_at),
            reverse=True,
        )

    def _filter_bars_by_range(
        self,
        bars: list[dict[str, Any]],
        requested_range: HistoricalRange,
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for bar in bars:
            bar_date = self._extract_bar_date(bar)
            if requested_range.start <= bar_date <= requested_range.end:
                filtered.append(bar)
        return filtered

    def _extract_bar_date(self, bar: dict[str, Any]) -> date:
        raw_value = bar.get("date") or bar.get("trading_date") or bar.get("time")
        if raw_value is None:
            raise ValueError("bar payload missing date/trading_date/time")
        if isinstance(raw_value, date) and not isinstance(raw_value, datetime):
            return raw_value
        if isinstance(raw_value, datetime):
            return raw_value.date()
        text = str(raw_value)
        try:
            if "T" in text:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
            return date.fromisoformat(text[:10])
        except ValueError as exc:
            raise ValueError("bar payload contains invalid date") from exc
