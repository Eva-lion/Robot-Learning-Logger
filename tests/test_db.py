"""Tests: Memory Hub DB."""

from __future__ import annotations

import pytest

from src.memory_hub.db import (
    get_episode,
    get_episodes,
    get_metrics_summary,
    insert_report,
    llm_cache_get,
    llm_cache_set,
    update_episode_status,
    upsert_episode,
)


def _ep(episode_id: str, status: str = "PENDING") -> dict:
    return {
        "episode_id": episode_id,
        "session_id": "sess-1",
        "started_at": "2026-04-12T10:00:00+00:00",
        "ended_at": "2026-04-12T10:01:00+00:00",
        "topics": ["/imu/data"],
        "frame_count": 100,
        "quality_score": None,
        "status": status,
        "version": 1,
        "notes": None,
    }


def test_upsert_and_get_episode():
    upsert_episode(_ep("ep-1"))
    ep = get_episode("ep-1")
    assert ep is not None
    assert ep["episode_id"] == "ep-1"
    assert ep["status"] == "PENDING"


def test_update_episode_status():
    upsert_episode(_ep("ep-2"))
    update_episode_status("ep-2", "APPROVED", notes="looks good")
    ep = get_episode("ep-2")
    assert ep["status"] == "APPROVED"
    assert ep["notes"] == "looks good"


def test_get_episodes_filter_by_status():
    upsert_episode(_ep("ep-3", "OK"))
    upsert_episode(_ep("ep-4", "REJECT"))
    ok_eps = get_episodes(status="OK")
    ids = [e["episode_id"] for e in ok_eps]
    assert "ep-3" in ids
    assert "ep-4" not in ids


def test_insert_and_get_report():
    upsert_episode(_ep("ep-5"))
    insert_report({
        "report_id": "rep-1",
        "episode_id": "ep-5",
        "created_at": "2026-04-12T10:05:00+00:00",
        "anomalies": ["imu spike"],
        "annotation": "looks bad",
        "confidence": 0.9,
        "verdict": "REJECT",
        "source": "FULL",
    })
    from src.memory_hub.db import get_report_by_episode
    rep = get_report_by_episode("ep-5")
    assert rep is not None
    assert rep["verdict"] == "REJECT"
    assert "imu spike" in rep["anomalies"]


def test_llm_cache_get_set():
    llm_cache_set("key-abc", '{"annotation": "ok", "confidence": 0.9, "verdict": "OK"}', ttl_hours=1)
    result = llm_cache_get("key-abc")
    assert result is not None
    assert "ok" in result


def test_llm_cache_miss():
    result = llm_cache_get("nonexistent-key")
    assert result is None


def test_metrics_summary():
    upsert_episode({**_ep("ep-m1"), "status": "OK", "quality_score": 0.9})
    upsert_episode({**_ep("ep-m2"), "status": "REJECT", "quality_score": 0.0})
    summary = get_metrics_summary()
    assert summary["total_episodes"] >= 2
    assert "OK" in summary["by_status"]
