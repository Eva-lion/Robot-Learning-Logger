"""Report Builder — формирует итоговый QA-отчёт из эвристик и LLM-ответа."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src import config
from src.models import (
    Anomaly,
    EpisodeInput,
    EpisodeStatus,
    HeuristicResult,
    LLMResponse,
    QAReport,
    ReportSource,
    Verdict,
)

_CONFIDENCE_THRESHOLD = config.get("quality_evaluator", "llm_confidence_threshold", 0.7)


def build(
    episode: EpisodeInput,
    heuristic: HeuristicResult,
    llm: LLMResponse | None,
) -> QAReport:
    """Определяет вердикт и статус эпизода по матрице правил."""

    source: ReportSource = "FULL" if llm is not None else "HEURISTIC_ONLY"
    verdict: Verdict
    status: EpisodeStatus
    anomalies: list[str]
    annotation: str
    confidence: float | None

    if heuristic.hard_fail:
        verdict = "REJECT"
        status = "REJECT"
        anomalies = [f"[HARD] {a.topic}/{a.field}: {a.description}" for a in heuristic.anomalies if a.severity == "hard"]
        annotation = "Episode rejected by heuristic analyzer: critical sensor anomalies detected."
        confidence = None

    elif llm is None:
        verdict = _verdict_from_heuristics(heuristic)
        status = "HEURISTIC_ONLY"
        anomalies = [f"[{a.severity.upper()}] {a.topic}/{a.field}: {a.description}" for a in heuristic.anomalies]
        if heuristic.missing_norms:
            status = "NEEDS_REVIEW"
        annotation = "LLM unavailable. Assessment based on heuristics only."
        confidence = None

    else:
        confidence = llm.confidence
        verdict = llm.verdict
        heuristic_descs = [f"[{a.severity.upper()}] {a.topic}/{a.field}: {a.description}" for a in heuristic.anomalies]
        anomalies = list(dict.fromkeys(heuristic_descs + llm.anomalies))  # deduplicate, preserve order
        annotation = llm.annotation

        if confidence < _CONFIDENCE_THRESHOLD:
            status = "NEEDS_REVIEW"
        elif verdict == "REJECT":
            status = "REJECT"
        elif verdict == "SOFT_WARN":
            status = "SOFT_WARN"
        else:
            status = "OK" if not heuristic.missing_norms else "NEEDS_REVIEW"

        if heuristic.missing_norms and status == "OK":
            status = "NEEDS_REVIEW"

    return QAReport(
        report_id=str(uuid.uuid4()),
        episode_id=episode.episode_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        anomalies=anomalies,
        annotation=annotation,
        confidence=confidence,
        verdict=verdict,
        source=source,
        status=status,
        heuristic_anomalies=heuristic.anomalies,
    )


def _verdict_from_heuristics(heuristic: HeuristicResult) -> Verdict:
    if heuristic.hard_fail:
        return "REJECT"
    if heuristic.anomalies:
        return "SOFT_WARN"
    return "OK"
