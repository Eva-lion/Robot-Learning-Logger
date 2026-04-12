"""Integration test: offline E2E pipeline (no ROS, no real LLM)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import load_fixture, make_episode
from src.memory_hub.db import get_episode, get_report_by_episode


def test_e2e_good_episode_heuristic_only(norms_cache):
    """Good episode in HEURISTIC_ONLY mode (no LLM key) → status OK or HEURISTIC_ONLY."""
    from src.quality_evaluator.orchestrator import Orchestrator

    orch = Orchestrator(norms_cache)
    episode = make_episode(load_fixture("good_episode.json"))

    with patch("src.quality_evaluator.llm_caller.call", return_value=None):
        report = orch.analyze_episode(episode)

    assert report.verdict in ("OK", "SOFT_WARN")
    assert report.source == "HEURISTIC_ONLY"

    ep_db = get_episode(episode.episode_id)
    assert ep_db is not None
    assert ep_db["status"] in ("OK", "HEURISTIC_ONLY", "SOFT_WARN", "NEEDS_REVIEW")

    rep_db = get_report_by_episode(episode.episode_id)
    assert rep_db is not None


def test_e2e_bad_episode_hard_fail(norms_cache):
    """Bad episode → REJECT without LLM call."""
    from src.quality_evaluator.orchestrator import Orchestrator

    orch = Orchestrator(norms_cache)
    episode = make_episode(load_fixture("bad_episode.json"))

    with patch("src.quality_evaluator.llm_caller.call") as mock_llm:
        report = orch.analyze_episode(episode)
        mock_llm.assert_not_called()  # hard fail skips LLM

    assert report.verdict == "REJECT"
    assert report.status == "REJECT"


def test_e2e_with_mock_llm_ok(norms_cache):
    """Good episode + mock LLM returning OK → status OK."""
    from src.quality_evaluator.orchestrator import Orchestrator
    from src.models import LLMResponse

    orch = Orchestrator(norms_cache)
    episode = make_episode(load_fixture("good_episode.json"))
    episode.episode_id = "e2e-llm-ok"

    mock_response = LLMResponse(
        annotation="Data quality is excellent.",
        anomalies=[],
        confidence=0.95,
        verdict="OK",
    )

    with patch("src.quality_evaluator.llm_caller.call", return_value=mock_response):
        report = orch.analyze_episode(episode)

    assert report.verdict == "OK"
    assert report.status == "OK"
    assert report.confidence == 0.95


def test_e2e_low_confidence_needs_review(norms_cache):
    """Mock LLM returns low confidence → NEEDS_REVIEW."""
    from src.quality_evaluator.orchestrator import Orchestrator
    from src.models import LLMResponse

    orch = Orchestrator(norms_cache)
    episode = make_episode(load_fixture("good_episode.json"))
    episode.episode_id = "e2e-low-conf"

    mock_response = LLMResponse(
        annotation="Uncertain about data quality.",
        anomalies=["possible imu drift"],
        confidence=0.4,
        verdict="SOFT_WARN",
    )

    with patch("src.quality_evaluator.llm_caller.call", return_value=mock_response):
        report = orch.analyze_episode(episode)

    assert report.status == "NEEDS_REVIEW"
