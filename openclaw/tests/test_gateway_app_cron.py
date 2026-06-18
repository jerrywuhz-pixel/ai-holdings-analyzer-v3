from dataclasses import dataclass

from fastapi.testclient import TestClient

import openclaw.gateway.post_confirmation_worker as worker_module
from openclaw.gateway_app import app


@dataclass
class FakeStats:
    scanned: int = 2
    succeeded: int = 1
    failed: int = 1
    skipped: int = 0
    receipts_queued: int = 1
    receipts_failed: int = 0


def test_post_confirmation_cron_processes_confirmed_jobs(monkeypatch) -> None:
    class FakeWorker:
        async def process_once(self, *, limit: int = 20) -> FakeStats:
            assert limit == 7
            return FakeStats()

    monkeypatch.setenv("OPENCLAW_CRON_SECRET", "cron-secret")
    monkeypatch.setattr(worker_module, "create_post_confirmation_worker_from_env", lambda: FakeWorker())

    with TestClient(app) as client:
        response = client.post(
            "/api/cron/post-confirmation",
            headers={"Authorization": "Bearer cron-secret"},
            json={"limit": 7},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "scanned": 2,
        "succeeded": 1,
        "failed": 1,
        "skipped": 0,
        "receipts_queued": 1,
        "receipts_failed": 0,
    }
