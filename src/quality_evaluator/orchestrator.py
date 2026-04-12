"""Orchestrator — центральный пайплайн анализа эпизода."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src import config
from src.models import EpisodeInput, EpisodeStatus, QAReport
from src.observability.logger import get_logger
from src.observability.metrics import METRICS
from src.quality_evaluator import heuristics, llm_caller, report_builder

if TYPE_CHECKING:
    from src.knowledge_base.loader import NormsCache

logger = get_logger(__name__)

_MAX_SANITIZER_BLOCKS = 5
_sanitizer_block_streak = 0


class Orchestrator:
    def __init__(self, norms: "NormsCache") -> None:
        self._norms = norms
        self._sanitizer_blocks = 0
        self._heuristic_only_mode = False

    def analyze_episode(self, episode: EpisodeInput) -> QAReport:
        """
        Полный пайплайн анализа. Возвращает QAReport.
        Сохраняет отчёт в Memory Hub и нотифицирует Human Gateway.
        """
        from src.memory_hub.writer import save_episode_record, save_report

        t0 = datetime.now(timezone.utc)
        logger.info(
            "Episode analysis started",
            extra={"event": "analysis_start", "episode_id": episode.episode_id},
        )

        heuristic_result = heuristics.analyze(episode, self._norms)

        save_episode_record(episode, status="PENDING")

        llm_response = None
        if not heuristic_result.hard_fail and not self._heuristic_only_mode:
            references = []
            if episode.scenario:
                references = self._norms.get_references_for_scenario(episode.scenario)

            try:
                llm_response = llm_caller.call(episode, heuristic_result, references)
            except Exception as exc:
                if "Blocked pattern" in str(exc):
                    self._sanitizer_blocks += 1
                    logger.warning(
                        "Sanitizer block",
                        extra={"event": "sanitizer_block_orchestrator", "streak": self._sanitizer_blocks},
                    )
                    if self._sanitizer_blocks >= _MAX_SANITIZER_BLOCKS:
                        logger.error("Sanitizer block limit reached; halting LLM calls", extra={"event": "sanitizer_halt"})
                        self._heuristic_only_mode = True
                else:
                    logger.error("Unexpected LLM error", extra={"event": "llm_unexpected_error", "error": str(exc)})

        report = report_builder.build(episode, heuristic_result, llm_response)

        quality_score = _compute_quality_score(report)

        save_episode_record(episode, status=report.status, quality_score=quality_score)
        save_report(report)

        METRICS["episodes_by_status"].labels(status=report.status).inc()
        if report.confidence is not None:
            METRICS["llm_confidence"].observe(report.confidence)
        METRICS["quality_score"].observe(quality_score)

        _notify_human_gateway(report)

        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        logger.info(
            "Episode analysis complete",
            extra={
                "event": "analysis_complete",
                "episode_id": episode.episode_id,
                "verdict": report.verdict,
                "status": report.status,
                "elapsed_s": round(elapsed, 2),
            },
        )
        return report


def _compute_quality_score(report: QAReport) -> float:
    """Числовое качество эпизода 0.0–1.0."""
    if report.verdict == "REJECT":
        return 0.0
    if report.verdict == "SOFT_WARN":
        base = 0.5
    else:
        base = 1.0

    if report.confidence is not None:
        return round((base + report.confidence) / 2, 3)
    return base


def _notify_human_gateway(report: QAReport) -> None:
    """PoC: вывод уведомления в stdout + лог."""
    msg = (
        f"\n[HUMAN GATEWAY] Episode {report.episode_id} → "
        f"VERDICT: {report.verdict} | STATUS: {report.status}"
    )
    if report.status in ("SOFT_WARN", "NEEDS_REVIEW", "REJECT", "HEURISTIC_ONLY"):
        msg += f"\nAction required. Annotation: {report.annotation[:200]}"

    print(msg)
    logger.info(
        "Human gateway notified",
        extra={
            "event": "human_gateway_notify",
            "episode_id": report.episode_id,
            "status": report.status,
        },
    )
