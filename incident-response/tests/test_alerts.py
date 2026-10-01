import time

import pytest
from fastapi.testclient import TestClient

from app import config, evidence, main

ALERT = {
    "status": "firing",
    "labels": {"alertname": "Order Tracker 5xx responses", "http_route": "/api/orders/{order_id}", "severity": "critical"},
    "annotations": {"summary": "5xx responses on /api/orders/{order_id}"},
    "startsAt": "2026-10-01T12:00:00.123456789Z",
    "fingerprint": "abc123",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "INCIDENTS_DIR", tmp_path)
    started = []

    async def fake_collect(alert, group, directory):
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text("{}")
        return {"files": ["alert.json"]}

    async def fake_run(directory):
        started.append(directory.name)
        return 0

    monkeypatch.setattr(main.evidence, "collect", fake_collect)
    monkeypatch.setattr(main.agent, "run", fake_run)
    main.in_flight.clear()
    with TestClient(main.app) as c:
        c.started = started
        yield c


def wait_for(predicate, timeout=2):
    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        time.sleep(0.01)


def test_firing_alert_saves_evidence_and_starts_agent(client):
    r = client.post("/alerts", json={"alerts": [ALERT]})
    assert r.status_code == 202
    assert r.json()["started"] == ["20261001T120000Z-abc123"]
    wait_for(lambda: client.started)
    assert client.started == ["20261001T120000Z-abc123"]


def test_resent_alert_is_not_investigated_twice(client):
    client.post("/alerts", json={"alerts": [ALERT]})
    wait_for(lambda: client.started)
    r = client.post("/alerts", json={"alerts": [ALERT]})
    assert r.json()["started"] == []
    assert len(client.started) == 1


def test_resolved_alert_is_ignored(client):
    r = client.post("/alerts", json={"alerts": [{**ALERT, "status": "resolved"}]})
    assert r.json()["started"] == []
    assert client.started == []


def test_affected_endpoint_and_time_parsing():
    assert evidence.affected_endpoint(ALERT) == "/api/orders/{order_id}"
    assert evidence.parse_time(ALERT["startsAt"]).year == 2026
