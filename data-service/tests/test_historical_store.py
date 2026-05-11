import asyncio
import json
from datetime import date

import httpx

from services.historical_store import (
    FileSystemHistoricalBlobStore,
    HistoricalDataStore,
    HistoricalManifestCreateRequest,
    SupabaseStorageHistoricalBlobStore,
)


def _sample_bars() -> list[dict]:
    return [
        {"date": "2026-05-01", "open": 100.0, "close": 101.0, "volume": 1000},
        {"date": "2026-05-02", "open": 101.0, "close": 102.0, "volume": 1100},
        {"date": "2026-05-05", "open": 102.0, "close": 103.0, "volume": 1200},
    ]


def test_register_manifest_normalizes_legacy_and_p0_fields():
    store = HistoricalDataStore()

    manifest = asyncio.run(
        store.register_manifest(
            HistoricalManifestCreateRequest(
                tenant_id="tenant-1",
                job_id="job-1",
                source_key="futu_openapi",
                market="us",
                symbol="aapl",
                instrument_type="stock",
                interval="1d",
                coverage_start=date(2026, 5, 1),
                coverage_end=date(2026, 5, 9),
                quality_status="validated",
            )
        )
    )

    assert manifest.tenant_id == "tenant-1"
    assert manifest.symbol == "AAPL"
    assert manifest.market == "US"
    assert manifest.source == "futu_openapi"
    assert manifest.source_key == "futu_openapi"
    assert manifest.bar_interval == "1d"
    assert manifest.interval == "1d"
    assert manifest.range.start == date(2026, 5, 1)
    assert manifest.range.end == date(2026, 5, 9)
    assert manifest.storage_uri.startswith("memory://market-data/curated/")
    assert manifest.freshness == "fresh"
    assert manifest.status == "ready"


def test_read_bars_returns_hit_when_cached_dataset_exists():
    store = HistoricalDataStore()
    payload = HistoricalManifestCreateRequest(
        tenant_id="tenant-1",
        job_id="job-2",
        source="yahoo",
        market="US",
        symbol="AAPL",
        instrument_type="stock",
        bar_interval="1d",
        range={"start": date(2026, 5, 1), "end": date(2026, 5, 9)},
        freshness="fresh",
        status="ready",
    )

    asyncio.run(store.save_dataset(payload, bars=_sample_bars()))
    result = asyncio.run(
        store.read_bars(
            tenant_id="tenant-1",
            symbol="AAPL",
            market="US",
            bar_interval="1d",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 2),
        )
    )

    assert result.found is True
    assert result.cache_status == "hit"
    assert result.reason is None
    assert len(result.bars) == 2
    assert result.manifest is not None
    assert result.manifest.storage_uri.startswith("memory://")


def test_read_bars_returns_degraded_when_manifest_exists_without_object():
    store = HistoricalDataStore()
    payload = HistoricalManifestCreateRequest(
        tenant_id="tenant-1",
        job_id="job-3",
        source="yahoo",
        market="US",
        symbol="AAPL",
        instrument_type="stock",
        bar_interval="1d",
        range={"start": date(2026, 5, 1), "end": date(2026, 5, 9)},
        status="ready",
    )

    asyncio.run(store.register_manifest(payload))
    result = asyncio.run(
        store.read_bars(
            tenant_id="tenant-1",
            symbol="AAPL",
            market="US",
            bar_interval="1d",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 2),
        )
    )

    assert result.found is False
    assert result.cache_status == "degraded"
    assert result.reason == "object_missing"
    assert result.manifest is not None


def test_read_bars_returns_cache_miss_when_coverage_is_missing():
    store = HistoricalDataStore()
    payload = HistoricalManifestCreateRequest(
        tenant_id="tenant-1",
        job_id="job-4",
        source="yahoo",
        market="US",
        symbol="AAPL",
        instrument_type="stock",
        bar_interval="1d",
        range={"start": date(2026, 5, 1), "end": date(2026, 5, 3)},
        status="ready",
    )

    asyncio.run(store.save_dataset(payload, bars=_sample_bars()))
    result = asyncio.run(
        store.read_bars(
            tenant_id="tenant-1",
            symbol="AAPL",
            market="US",
            bar_interval="1d",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 9),
        )
    )

    assert result.found is False
    assert result.cache_status == "cache_miss"
    assert result.reason == "coverage_gap"
    assert result.manifest is not None


def test_filesystem_blob_store_round_trips_cached_history(tmp_path):
    store = HistoricalDataStore(blob_store=FileSystemHistoricalBlobStore(tmp_path))
    payload = HistoricalManifestCreateRequest(
        tenant_id="tenant-9",
        job_id="job-9",
        source="futu_openapi",
        market="US",
        symbol="MSFT",
        instrument_type="stock",
        bar_interval="1d",
        range={"start": date(2026, 5, 1), "end": date(2026, 5, 9)},
        storage_backend="file",
    )

    manifest = asyncio.run(store.save_dataset(payload, bars=_sample_bars()))
    result = asyncio.run(
        store.read_bars(
            tenant_id="tenant-9",
            symbol="MSFT",
            market="US",
            bar_interval="1d",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 5),
        )
    )

    assert manifest.storage_uri.startswith("file://")
    assert result.cache_status == "hit"
    assert len(result.bars) == 3


def test_supabase_storage_blob_store_round_trips_with_signed_rest_contract():
    calls: list[dict] = []
    stored: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"method": request.method, "url": str(request.url), "headers": dict(request.headers)})
        key = str(request.url)
        if request.method == "POST":
            stored[key] = request.content
            return httpx.Response(200, json={"Key": "market-data/path.json"})
        if request.method == "GET":
            post_key = key
            if post_key not in stored:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, content=stored[post_key], headers={"content-type": "application/json"})
        return httpx.Response(405)

    store = SupabaseStorageHistoricalBlobStore(
        "https://supabase.example",
        "service-role-key",
        transport=httpx.MockTransport(handler),
    )
    uri = "supabase_storage://market-data/tenant=tenant-1/source=futu/AAPL.json"

    asyncio.run(store.put(uri, _sample_bars()))
    result = asyncio.run(store.get(uri))

    assert result == _sample_bars()
    assert calls[0]["method"] == "POST"
    assert calls[0]["headers"]["authorization"] == "Bearer service-role-key"
    assert calls[0]["headers"]["x-upsert"] == "true"
    assert json.loads(stored["https://supabase.example/storage/v1/object/market-data/tenant=tenant-1/source=futu/AAPL.json"]) == _sample_bars()
