"""LLM Caller — вызов LLM API с кэшом, retry и fallback."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from src import config
from src.memory_hub.db import llm_cache_get, llm_cache_set
from src.models import EpisodeInput, HeuristicResult, LLMResponse
from src.observability.logger import get_logger
from src.observability.metrics import METRICS
from src.quality_evaluator.sanitizer import SanitizerBlockError, sanitize

logger = get_logger(__name__)

_CONFIDENCE_THRESHOLD = config.get("quality_evaluator", "llm_confidence_threshold", 0.7)
_MAX_RETRIES = config.get("quality_evaluator", "llm_retry_count", 3)
_TIMEOUT = config.get("quality_evaluator", "llm_timeout_s", 30)
_RESPONSE_TOKENS = config.get("quality_evaluator", "llm_response_tokens", 512)
_TEMPERATURE = config.get("quality_evaluator", "llm_temperature", 0.2)
_CACHE_TTL = config.get("memory", "llm_cache_ttl_hours", 24)

_SYSTEM_PROMPT = """You are a Robot Data Quality Analyst. Analyze the provided robot episode summary and return a JSON object with these fields:
- "annotation": string — brief human-readable description of the episode quality
- "anomalies": list of strings — detected issues (empty list if none)
- "confidence": float 0.0-1.0 — your confidence in this assessment
- "verdict": one of "OK", "SOFT_WARN", "REJECT"

Rules:
- REJECT if there are critical sensor failures, data corruption, or safety violations
- SOFT_WARN if there are minor issues that need human review
- OK if the data quality is acceptable for robot learning
- Be concise and factual. Do not hallucinate issues not present in the data.
Return ONLY valid JSON, no markdown, no explanation outside the JSON."""


def build_episode_summary(
    episode: EpisodeInput,
    heuristic: HeuristicResult,
    references: list[dict[str, Any]],
) -> str:
    """Строит JSON-резюме эпизода для LLM ≤ 3000 токенов."""
    anomalous_topics = {a.topic for a in heuristic.anomalies}
    normal_stats = []
    anomalous_stats = []

    for s in episode.stats:
        entry = {
            "topic": s.topic,
            "field": s.field,
            "min": round(s.min_val, 4),
            "max": round(s.max_val, 4),
            "mean": round(s.mean_val, 4),
            "std": round(s.std_val, 4),
            "max_gap_ms": round(s.max_gap_ms, 1),
            "count": s.count,
        }
        if s.topic in anomalous_topics:
            anomalous_stats.append(entry)
        else:
            normal_stats.append(entry)

    summary = {
        "episode_id": episode.episode_id,
        "started_at": episode.started_at,
        "ended_at": episode.ended_at,
        "topics": episode.topics,
        "frame_count": episode.frame_count,
        "scenario": episode.scenario,
        "heuristic_anomalies": [
            {"topic": a.topic, "field": a.field, "severity": a.severity, "description": a.description}
            for a in heuristic.anomalies
        ],
        "missing_norms": heuristic.missing_norms,
        "anomalous_stats": anomalous_stats,
        "normal_stats": normal_stats[:10],  # limit normal stats
        "reference_context": references[:2] if references else [],
    }

    return json.dumps(summary, ensure_ascii=False)


def call(episode: EpisodeInput, heuristic: HeuristicResult, references: list[dict]) -> LLMResponse | None:
    """
    Вызывает LLM с retry и fallback.
    Возвращает LLMResponse или None при ошибке.
    """
    summary_text = build_episode_summary(episode, heuristic, references)

    try:
        sanitized = sanitize(summary_text)
    except SanitizerBlockError:
        return None

    cache_key = hashlib.sha256(sanitized.encode()).hexdigest()
    cached = llm_cache_get(cache_key)
    if cached:
        try:
            data = json.loads(cached)
            logger.info("LLM cache hit", extra={"event": "llm_cache_hit", "episode_id": episode.episode_id})
            METRICS["llm_cache_hits_total"].inc()
            return LLMResponse(
                annotation=data["annotation"],
                anomalies=data.get("anomalies", []),
                confidence=float(data.get("confidence", 0.5)),
                verdict=data.get("verdict", "SOFT_WARN"),
                cached=True,
            )
        except Exception:
            pass

    provider = config.get("llm", "provider", "openai")
    model = config.get("llm", "model", "gpt-4o-mini")

    for attempt in range(1, _MAX_RETRIES + 1):
        t0 = time.time()
        try:
            raw = _call_provider(provider, model, sanitized)
            latency = time.time() - t0
            METRICS["llm_latency_seconds"].observe(latency)
            METRICS["llm_requests_total"].labels(provider=provider, status="success").inc()

            parsed = _parse_response(raw)
            if parsed is None:
                raise ValueError("Unparseable LLM response")

            llm_cache_set(cache_key, json.dumps(parsed), ttl_hours=_CACHE_TTL)

            return LLMResponse(
                annotation=parsed["annotation"],
                anomalies=parsed.get("anomalies", []),
                confidence=float(parsed.get("confidence", 0.5)),
                verdict=parsed.get("verdict", "SOFT_WARN"),
            )

        except Exception as exc:
            latency = time.time() - t0
            METRICS["llm_requests_total"].labels(provider=provider, status="error").inc()
            logger.warning(
                "LLM call failed",
                extra={
                    "event": "llm_error",
                    "attempt": attempt,
                    "error": str(exc),
                    "episode_id": episode.episode_id,
                },
            )
            if attempt < _MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))  # 1s, 2s, 4s

    logger.error("All LLM retries exhausted; fallback", extra={"event": "llm_fallback", "episode_id": episode.episode_id})
    METRICS["llm_fallback_total"].inc()
    return None


def _call_provider(provider: str, model: str, user_content: str) -> str:
    if provider == "openai":
        return _call_openai(model, user_content)
    elif provider == "anthropic":
        return _call_anthropic(model, user_content)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def _call_openai(model: str, user_content: str) -> str:
    from openai import OpenAI

    api_key = config.env("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY not set")

    client = OpenAI(api_key=api_key, timeout=_TIMEOUT)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=_RESPONSE_TOKENS,
        temperature=_TEMPERATURE,
    )
    tokens = response.usage.total_tokens if response.usage else 0
    METRICS["llm_tokens_used_total"].inc(tokens)
    return response.choices[0].message.content or ""


def _call_anthropic(model: str, user_content: str) -> str:
    import anthropic

    api_key = config.env("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=_RESPONSE_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    tokens = response.usage.input_tokens + response.usage.output_tokens if response.usage else 0
    METRICS["llm_tokens_used_total"].inc(tokens)
    return response.content[0].text if response.content else ""


def _parse_response(raw: str) -> dict | None:
    """Пытается распарсить JSON из ответа LLM."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(raw)
        if not all(k in data for k in ("annotation", "confidence", "verdict")):
            return None
        return data
    except json.JSONDecodeError:
        return None
