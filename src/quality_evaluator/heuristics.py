"""Эвристический анализатор — первый фильтр без LLM."""

from __future__ import annotations

from src.models import Anomaly, EpisodeInput, HeuristicResult
from src.knowledge_base.loader import NormsCache
from src.observability.logger import get_logger
from src.observability.metrics import METRICS

logger = get_logger(__name__)


def analyze(episode: EpisodeInput, norms: NormsCache) -> HeuristicResult:
    """
    Сравнивает статистику эпизода с нормами.
    Returns HeuristicResult с флагом hard_fail, списком аномалий и отсутствующих норм.
    """
    anomalies: list[Anomaly] = []
    missing_norms: list[str] = []
    hard_fail = False

    for stat in episode.stats:
        rule = norms.get_rule(stat.topic, stat.field)

        if rule is None:
            key = f"{stat.topic}/{stat.field}"
            missing_norms.append(key)
            logger.warning(
                "No norm found for topic/field",
                extra={
                    "event": "missing_norm",
                    "episode_id": episode.episode_id,
                    "topic": stat.topic,
                    "field": stat.field,
                },
            )
            continue

        severity = rule.get("severity", "hard")
        problems: list[str] = []

        min_val = rule.get("min_val")
        max_val = rule.get("max_val")
        if min_val is not None and stat.min_val < min_val:
            problems.append(f"min={stat.min_val:.3f} < allowed {min_val}")
        if max_val is not None and stat.max_val > max_val:
            problems.append(f"max={stat.max_val:.3f} > allowed {max_val}")

        max_std = rule.get("max_std_dev")
        if max_std is not None and stat.std_val > max_std:
            problems.append(f"std={stat.std_val:.3f} > allowed {max_std}")

        max_gap = rule.get("max_gap_ms")
        if max_gap is not None and stat.max_gap_ms > max_gap:
            problems.append(f"max_gap={stat.max_gap_ms:.1f}ms > allowed {max_gap}ms")

        if problems:
            desc = "; ".join(problems)
            anomaly = Anomaly(
                topic=stat.topic,
                field=stat.field,
                severity=severity,
                description=desc,
            )
            anomalies.append(anomaly)
            METRICS["anomalies_detected_total"].labels(topic=stat.topic, severity=severity).inc()

            if severity == "hard":
                hard_fail = True
                logger.warning(
                    "Hard anomaly detected",
                    extra={
                        "event": "hard_anomaly",
                        "episode_id": episode.episode_id,
                        "topic": stat.topic,
                        "field": stat.field,
                        "description": desc,
                    },
                )

    return HeuristicResult(
        hard_fail=hard_fail,
        anomalies=anomalies,
        missing_norms=missing_norms,
    )
