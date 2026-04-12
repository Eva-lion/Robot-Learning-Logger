"""Shared pytest fixtures."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# Point DB to a temp file for tests
@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Each test gets its own SQLite database."""
    db_file = tmp_path / "test_rll.db"
    monkeypatch.setenv("RLL_DB_PATH", str(db_file))

    import src.memory_hub.db as db_module
    monkeypatch.setattr(db_module, "_DB_PATH", str(db_file))

    from src.memory_hub.db import init_db
    init_db()
    yield


@pytest.fixture
def norms_cache():
    from src.knowledge_base.loader import NormsCache
    cache = NormsCache()
    cache.load()
    return cache


def load_fixture(name: str) -> dict:
    path = Path(__file__).parent / "fixtures" / "episodes" / name
    return json.loads(path.read_text())


def make_episode(data: dict):
    from src.models import EpisodeInput, TopicStats
    stats = [TopicStats(**s) for s in data.get("stats", [])]
    return EpisodeInput(
        episode_id=data["episode_id"],
        session_id=data.get("session_id", "test"),
        started_at=data["started_at"],
        ended_at=data["ended_at"],
        topics=data.get("topics", []),
        stats=stats,
        frame_count=data.get("frame_count", 0),
        scenario=data.get("scenario"),
    )
