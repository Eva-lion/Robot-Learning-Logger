"""Memory Hub Writer — сохранение эпизодов и отчётов в SQLite."""

from __future__ import annotations

import json

from src.memory_hub import db
from src.models import EpisodeInput, QAReport


def save_episode_record(
    episode: EpisodeInput,
    status: str = "PENDING",
    quality_score: float | None = None,
) -> None:
    db.upsert_episode({
        "episode_id": episode.episode_id,
        "session_id": episode.session_id,
        "started_at": episode.started_at,
        "ended_at": episode.ended_at,
        "topics": episode.topics,
        "frame_count": episode.frame_count,
        "quality_score": quality_score,
        "status": status,
        "version": 1,
        "notes": None,
    })


def save_report(report: QAReport) -> None:
    db.insert_report({
        "report_id": report.report_id,
        "episode_id": report.episode_id,
        "created_at": report.created_at,
        "anomalies": report.anomalies,
        "annotation": report.annotation,
        "confidence": report.confidence,
        "verdict": report.verdict,
        "source": report.source,
    })
