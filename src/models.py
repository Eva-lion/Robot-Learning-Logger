"""Общие типы данных, используемые во всех модулях."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal



@dataclass
class ImuData:
    timestamp_ns: int
    angular_velocity_x: float
    angular_velocity_y: float
    angular_velocity_z: float
    linear_acceleration_x: float
    linear_acceleration_y: float
    linear_acceleration_z: float


@dataclass
class OdomData:
    timestamp_ns: int
    position_x: float
    position_y: float
    position_z: float
    linear_x: float
    angular_z: float


@dataclass
class CameraData:
    timestamp_ns: int
    width: int
    height: int
    encoding: str
    fps_actual: float
    data: bytes  # anonymized before storage



@dataclass
class TopicStats:
    """Агрегированная статистика по одному полю топика за эпизод."""
    topic: str
    field: str
    min_val: float
    max_val: float
    mean_val: float
    std_val: float
    max_gap_ms: float
    count: int


@dataclass
class EpisodeInput:
    episode_id: str
    session_id: str
    started_at: str          # ISO 8601
    ended_at: str
    topics: list[str]
    stats: list[TopicStats]
    frame_count: int
    scenario: str | None = None



EpisodeStatus = Literal[
    "PENDING",
    "OK",
    "SOFT_WARN",
    "REJECT",
    "NEEDS_REVIEW",
    "HEURISTIC_ONLY",
    "APPROVED",
    "REJECTED_MANUAL",
]

Verdict = Literal["OK", "SOFT_WARN", "REJECT"]
ReportSource = Literal["FULL", "HEURISTIC_ONLY"]


@dataclass
class Anomaly:
    topic: str
    field: str
    severity: Literal["hard", "soft"]
    description: str


@dataclass
class HeuristicResult:
    hard_fail: bool
    anomalies: list[Anomaly]
    missing_norms: list[str]  # "topic/field" строки


@dataclass
class LLMResponse:
    annotation: str
    anomalies: list[str]
    confidence: float
    verdict: Verdict
    cached: bool = False


@dataclass
class QAReport:
    report_id: str
    episode_id: str
    created_at: str
    anomalies: list[str]
    annotation: str
    confidence: float | None
    verdict: Verdict
    source: ReportSource
    status: EpisodeStatus
    heuristic_anomalies: list[Anomaly] = field(default_factory=list)
