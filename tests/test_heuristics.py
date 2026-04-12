"""Tests: Heuristic Analyzer."""

from __future__ import annotations

import pytest

from tests.conftest import load_fixture, make_episode
from src.quality_evaluator.heuristics import analyze


def test_ok_normal_episode(norms_cache):
    data = load_fixture("good_episode.json")
    episode = make_episode(data)
    result = analyze(episode, norms_cache)
    assert result.hard_fail is False
    assert result.anomalies == []


def test_hard_fail_out_of_range(norms_cache):
    data = load_fixture("bad_episode.json")
    episode = make_episode(data)
    result = analyze(episode, norms_cache)
    assert result.hard_fail is True
    hard = [a for a in result.anomalies if a.severity == "hard"]
    assert len(hard) > 0


def test_soft_warn_gap(norms_cache):
    data = load_fixture("soft_warn_episode.json")
    episode = make_episode(data)
    result = analyze(episode, norms_cache)
    assert result.hard_fail is False
    soft = [a for a in result.anomalies if a.severity == "soft"]
    assert len(soft) > 0


def test_missing_norm_flag(norms_cache):
    from src.models import EpisodeInput, TopicStats
    episode = EpisodeInput(
        episode_id="missing-norm-test",
        session_id="test",
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:01:00+00:00",
        topics=["/unknown/topic"],
        stats=[
            TopicStats(
                topic="/unknown/topic",
                field="weird_field",
                min_val=0.0, max_val=1.0, mean_val=0.5,
                std_val=0.1, max_gap_ms=10.0, count=100,
            )
        ],
        frame_count=0,
    )
    result = analyze(episode, norms_cache)
    assert result.hard_fail is False
    assert "/unknown/topic/weird_field" in result.missing_norms
