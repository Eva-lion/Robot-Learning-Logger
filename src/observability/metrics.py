"""Prometheus metrics — все счётчики и gauges системы."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

from src import config

_PROMETHEUS_PORT = config.get("observability", "prometheus_port", 8001)
_started = False


def start_prometheus() -> None:
    global _started
    if not _started:
        start_http_server(_PROMETHEUS_PORT)
        _started = True


METRICS: dict = {
    "ros_connected": Gauge("rll_ros_connected", "1 if ROS is connected"),
    "ros_reconnects_total": Counter("rll_ros_reconnects_total", "Number of ROS reconnects"),
    "disk_usage_bytes": Gauge("rll_disk_usage_bytes", "Episode storage size in bytes"),
    "episodes_total": Counter("rll_episodes_total", "Total episodes collected"),
    "episodes_by_status": Counter(
        "rll_episodes_by_status_total",
        "Episodes by status",
        ["status"],
    ),
    "data_crc_failures_total": Counter("rll_data_crc_failures_total", "CRC validation failures"),
    "anomalies_detected_total": Counter(
        "rll_anomalies_detected_total",
        "Anomalies detected by heuristics",
        ["topic", "severity"],
    ),
    "quality_score": Histogram(
        "rll_quality_score",
        "Distribution of episode quality scores",
        buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    ),
    "llm_requests_total": Counter(
        "rll_llm_requests_total",
        "LLM API requests",
        ["provider", "status"],
    ),
    "llm_latency_seconds": Histogram(
        "rll_llm_latency_seconds",
        "LLM call latency",
        buckets=[1, 2, 5, 10, 15, 20, 30],
    ),
    "llm_tokens_used_total": Counter("rll_llm_tokens_used_total", "Total LLM tokens consumed"),
    "llm_cache_hits_total": Counter("rll_llm_cache_hits_total", "LLM cache hits"),
    "llm_fallback_total": Counter("rll_llm_fallback_total", "LLM fallback to heuristics"),
    "llm_confidence": Histogram(
        "rll_llm_confidence",
        "LLM response confidence distribution",
        buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    ),
    "sanitizer_blocks_total": Counter("rll_sanitizer_blocks_total", "Sanitizer block events"),
    "api_requests_total": Counter(
        "rll_api_requests_total",
        "Monitoring API requests",
        ["endpoint", "status_code"],
    ),
    "api_latency_seconds": Histogram(
        "rll_api_latency_seconds",
        "Monitoring API latency",
        ["endpoint"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
    ),
}
