"""
Tests for JobManager — 任务生命周期管理器

测试 JobManager 各方法的正确行为，包括：
- 创建 job（含/不含 task_definition）
- 状态流转（start / complete / fail / timeout / abandon）
- 查询方法（find_stale_pending_jobs / find_timed_out_running_jobs）
- retry_count 递增逻辑
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Add project root to sys.path for openclaw imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Mock supabase before importing openclaw modules that depend on it
# (supabase.Client may not be importable in test environments)
if "supabase" not in sys.modules:
    _mock_supabase = MagicMock()
    _mock_supabase.Client = MagicMock
    _mock_supabase.create_client = MagicMock()
    sys.modules["supabase"] = _mock_supabase

from openclaw.gateway.job_manager import JobManager


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def mock_client():
    """Create a fresh mock Supabase client for each test."""
    return MagicMock()


@pytest.fixture
def job_manager(mock_client):
    """Create a JobManager with mock client."""
    return JobManager(client=mock_client)


# ------------------------------------------------------------------ #
# create_job
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_create_job_success(job_manager, mock_client):
    """create_job with task_definition found inserts record and returns job_id."""
    task_def = {
        "id": "task-def-uuid",
        "job_type": "daily_analysis",
        "timeout_seconds": 300,
        "config": {"key": "value"},
    }

    with patch.object(job_manager, "_find_task_definition", return_value=task_def):
        mock_execute = MagicMock(return_value=MagicMock(data=[{"id": "test-job-uuid"}]))
        mock_client.table.return_value.insert.return_value.execute = mock_execute

        result = await job_manager.create_job("daily-analysis", tenant_id="tenant-123")

    assert result == "test-job-uuid"
    # Verify insert was called and payload contains task_definition data
    insert_call = mock_client.table.return_value.insert.call_args
    payload = insert_call[0][0]
    assert payload["status"] == "PENDING"
    assert payload["job_type"] == "daily_analysis"
    assert payload["task_definition_id"] == "task-def-uuid"
    assert payload["timeout_seconds"] == 300
    assert payload["config"] == {"key": "value"}
    assert payload["tenant_id"] == "tenant-123"


@pytest.mark.asyncio
async def test_create_job_no_task_definition(job_manager, mock_client):
    """create_job falls back to task_name as job_type when no task_definition found."""
    with patch.object(job_manager, "_find_task_definition", return_value=None):
        mock_execute = MagicMock(return_value=MagicMock(data=[{"id": "test-job-uuid"}]))
        mock_client.table.return_value.insert.return_value.execute = mock_execute

        result = await job_manager.create_job("custom-task")

    assert result == "test-job-uuid"
    insert_call = mock_client.table.return_value.insert.call_args
    payload = insert_call[0][0]
    assert payload["job_type"] == "custom-task"
    assert payload["timeout_seconds"] == 120


# ------------------------------------------------------------------ #
# start_job
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_start_job(job_manager, mock_client):
    """start_job sets status=RUNNING and started_at."""
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await job_manager.start_job("job-123")

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "RUNNING"
    assert "started_at" in payload
    # Verify eq filter on id
    eq_call = mock_client.table.return_value.update.return_value.eq.call_args
    assert eq_call[0] == ("id", "job-123")


# ------------------------------------------------------------------ #
# complete_job
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_complete_job(job_manager, mock_client):
    """complete_job sets status=SUCCESS and completed_at."""
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await job_manager.complete_job("job-456", result={"trades_analyzed": 5})

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "SUCCESS"
    assert "completed_at" in payload
    assert payload["result_summary"] == {"trades_analyzed": 5}


# ------------------------------------------------------------------ #
# fail_job
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_fail_job_increments_retry(job_manager, mock_client):
    """fail_job reads current retry_count then increments it."""
    # Mock select chain: returns retry_count=2
    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute = MagicMock(
        return_value=MagicMock(data=[{"retry_count": 2}])
    )
    # Mock update chain
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await job_manager.fail_job("job-789", "Something went wrong")

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "FAILED"
    assert payload["retry_count"] == 3  # 2 + 1
    assert payload["error_message"] == "Something went wrong"
    assert "completed_at" in payload


# ------------------------------------------------------------------ #
# timeout_job
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_timeout_job(job_manager, mock_client):
    """timeout_job sets status=TIMED_OUT and error_message."""
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await job_manager.timeout_job("job-timeout")

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "TIMED_OUT"
    assert payload["error_message"] == "Job timed out (detected by heartbeat)"
    assert "completed_at" in payload


# ------------------------------------------------------------------ #
# abandon_job
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_abandon_job(job_manager, mock_client):
    """abandon_job sets status=ABANDONED."""
    mock_client.table.return_value.update.return_value.eq.return_value.execute = MagicMock()

    await job_manager.abandon_job("job-abandon")

    update_call = mock_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["status"] == "ABANDONED"
    assert payload["error_message"] == "Job abandoned after max retries"
    assert "completed_at" in payload


# ------------------------------------------------------------------ #
# find_stale_pending_jobs
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_find_stale_pending_jobs(job_manager, mock_client):
    """find_stale_pending_jobs returns list of stale PENDING jobs from query."""
    stale_jobs = [
        {"id": "job-1", "job_type": "daily", "created_at": "2025-01-01T00:00:00+00:00"},
        {"id": "job-2", "job_type": "weekly", "created_at": "2025-01-01T00:05:00+00:00"},
    ]
    mock_client.table.return_value.select.return_value.eq.return_value.lt.return_value.execute = MagicMock(
        return_value=MagicMock(data=stale_jobs)
    )

    result = await job_manager.find_stale_pending_jobs(stale_threshold_minutes=5)

    assert len(result) == 2
    assert result[0]["id"] == "job-1"
    assert result[1]["id"] == "job-2"
    # Verify query used PENDING status filter
    eq_call = mock_client.table.return_value.select.return_value.eq.call_args
    assert eq_call[0] == ("status", "PENDING")


# ------------------------------------------------------------------ #
# find_timed_out_running_jobs
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_find_timed_out_running_jobs_expired(job_manager, mock_client):
    """Running job with started_at beyond timeout_seconds is included in results."""
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    running_jobs = [
        {
            "id": "job-expired",
            "job_type": "daily",
            "started_at": one_hour_ago,
            "timeout_seconds": 60,  # 60s timeout, but started 1h ago → expired
        },
    ]
    mock_client.table.return_value.select.return_value.eq.return_value.execute = MagicMock(
        return_value=MagicMock(data=running_jobs)
    )

    result = await job_manager.find_timed_out_running_jobs()

    assert len(result) == 1
    assert result[0]["id"] == "job-expired"


@pytest.mark.asyncio
async def test_find_timed_out_running_jobs_not_expired(job_manager, mock_client):
    """Running job with recent started_at (within timeout) is NOT included."""
    just_now = datetime.now(timezone.utc).isoformat()
    running_jobs = [
        {
            "id": "job-recent",
            "job_type": "daily",
            "started_at": just_now,
            "timeout_seconds": 3600,  # 1h timeout, just started → not expired
        },
    ]
    mock_client.table.return_value.select.return_value.eq.return_value.execute = MagicMock(
        return_value=MagicMock(data=running_jobs)
    )

    result = await job_manager.find_timed_out_running_jobs()

    assert len(result) == 0
