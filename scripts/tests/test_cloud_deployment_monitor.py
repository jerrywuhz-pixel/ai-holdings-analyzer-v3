from scripts.cloud_deployment_monitor import (
    EXPECTED_SCHEDULER_JOBS,
    Probe,
    cloud_run_service_probe,
    scheduler_probe,
    summarize,
)


def test_summarize_fails_when_any_probe_fails():
    summary = summarize(
        [
            Probe("cloud-run", "gateway", "pass", "ready"),
            Probe("scheduler", "daily-market-scan", "fail", "missing"),
        ]
    )

    assert summary["status"] == "fail"
    assert summary["counts"] == {"pass": 1, "warn": 0, "fail": 1}


def test_cloud_run_probe_reads_ready_condition_and_url(monkeypatch):
    def fake_run_json(command):
        assert command[:4] == ["gcloud", "run", "services", "describe"]
        return (
            {
                "status": {
                    "url": "https://gateway.example",
                    "conditions": [{"type": "Ready", "status": "True"}],
                }
            },
            "",
        )

    monkeypatch.setattr("scripts.cloud_deployment_monitor._run_json", fake_run_json)

    probe, url = cloud_run_service_probe("openclaw-gateway", project="p", region="r")

    assert probe.status == "pass"
    assert url == "https://gateway.example"


def test_scheduler_probe_requires_expected_jobs(monkeypatch):
    def fake_run_json(command):
        return ([{"name": f"projects/p/locations/r/jobs/{EXPECTED_SCHEDULER_JOBS[0]}"}], "")

    monkeypatch.setattr("scripts.cloud_deployment_monitor._run_json", fake_run_json)

    probes = scheduler_probe(project="p", region="r")
    statuses = {probe.name: probe.status for probe in probes}

    assert statuses[EXPECTED_SCHEDULER_JOBS[0]] == "pass"
    assert statuses[EXPECTED_SCHEDULER_JOBS[1]] == "fail"
