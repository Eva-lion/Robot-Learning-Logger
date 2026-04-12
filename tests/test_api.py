"""Tests: Monitoring API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.memory_hub.db import upsert_episode


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    import src.api.app as app_module
    monkeypatch.setattr(app_module, "_API_KEY", "test-key")
    app = create_app()
    return TestClient(app)


_HEADERS = {"X-API-Key": "test-key"}
_BAD_HEADERS = {"X-API-Key": "wrong-key"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_episodes_unauthorized(client):
    r = client.get("/episodes")
    assert r.status_code == 401


def test_episodes_empty(client):
    r = client.get("/episodes", headers=_HEADERS)
    assert r.status_code == 200
    assert r.json() == []


def test_episodes_after_insert(client):
    upsert_episode({
        "episode_id": "api-ep-1",
        "session_id": "s",
        "started_at": "2026-04-12T10:00:00+00:00",
        "ended_at": "2026-04-12T10:01:00+00:00",
        "topics": [],
        "frame_count": 0,
        "quality_score": 0.8,
        "status": "OK",
        "version": 1,
        "notes": None,
    })
    r = client.get("/episodes", headers=_HEADERS)
    assert r.status_code == 200
    ids = [e["episode_id"] for e in r.json()]
    assert "api-ep-1" in ids


def test_get_single_episode(client):
    upsert_episode({
        "episode_id": "api-ep-2",
        "session_id": "s",
        "started_at": "2026-04-12T10:00:00+00:00",
        "ended_at": "2026-04-12T10:01:00+00:00",
        "topics": [],
        "frame_count": 0,
        "quality_score": None,
        "status": "PENDING",
        "version": 1,
        "notes": None,
    })
    r = client.get("/episodes/api-ep-2", headers=_HEADERS)
    assert r.status_code == 200
    assert r.json()["episode"]["episode_id"] == "api-ep-2"


def test_get_nonexistent_episode(client):
    r = client.get("/episodes/does-not-exist", headers=_HEADERS)
    assert r.status_code == 404


def test_approve_episode(client):
    upsert_episode({
        "episode_id": "api-ep-3",
        "session_id": "s",
        "started_at": "2026-04-12T10:00:00+00:00",
        "ended_at": "2026-04-12T10:01:00+00:00",
        "topics": [],
        "frame_count": 0,
        "quality_score": 0.95,
        "status": "SOFT_WARN",
        "version": 1,
        "notes": None,
    })
    r = client.post("/episodes/api-ep-3/approve", headers=_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "APPROVED"


def test_reject_episode(client):
    upsert_episode({
        "episode_id": "api-ep-4",
        "session_id": "s",
        "started_at": "2026-04-12T10:00:00+00:00",
        "ended_at": "2026-04-12T10:01:00+00:00",
        "topics": [],
        "frame_count": 0,
        "quality_score": 0.1,
        "status": "SOFT_WARN",
        "version": 1,
        "notes": None,
    })
    r = client.post(
        "/episodes/api-ep-4/reject",
        json={"reason": "bad imu data"},
        headers={**_HEADERS, "content-type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "REJECTED_MANUAL"


def test_metrics_summary(client):
    r = client.get("/metrics/summary", headers=_HEADERS)
    assert r.status_code == 200
    assert "total_episodes" in r.json()
