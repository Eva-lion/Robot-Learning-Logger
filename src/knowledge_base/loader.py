"""Загрузка норм сенсоров и reference-траекторий в memory cache."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src import config
from src.observability.logger import get_logger

logger = get_logger(__name__)


class NormsCache:
    """
    In-memory кэш норм сенсоров.
    dict[topic][field] → rule dict
    """

    def __init__(self) -> None:
        self._norms: dict[str, dict[str, dict[str, Any]]] = {}
        self._references: list[dict[str, Any]] = []

    def load(self) -> None:
        self._load_norms()
        self._load_references()
        logger.info(
            "NormsCache loaded",
            extra={
                "event": "norms_loaded",
                "topics_count": len(self._norms),
                "references_count": len(self._references),
            },
        )

    def _load_norms(self) -> None:
        path = Path(config.get("memory", "sensor_norms_path", "data/norms.json"))
        if not path.exists():
            logger.warning("norms.json not found", extra={"event": "norms_missing", "path": str(path)})
            return

        with open(path) as f:
            rules: list[dict[str, Any]] = json.load(f)

        # Also try to load from DB (overrides JSON if present)
        db_rules = self._load_norms_from_db()
        if db_rules:
            rules = db_rules

        for rule in rules:
            topic = rule["topic"]
            field = rule["field"]
            self._norms.setdefault(topic, {})[field] = rule

    @staticmethod
    def _load_norms_from_db() -> list[dict[str, Any]]:
        try:
            from src.memory_hub.db import get_conn
            with get_conn() as conn:
                rows = conn.execute("SELECT * FROM sensor_norms").fetchall()
            return [dict(r) for r in rows] if rows else []
        except Exception:
            return []

    def _load_references(self) -> None:
        path = Path(config.get("memory", "reference_traces_path", "data/reference_trajectories.json"))
        if not path.exists():
            return
        with open(path) as f:
            self._references = json.load(f)

    def get_rule(self, topic: str, field: str) -> dict[str, Any] | None:
        return self._norms.get(topic, {}).get(field)

    def get_references_for_scenario(self, scenario: str) -> list[dict[str, Any]]:
        return [r for r in self._references if r.get("scenario") == scenario]

    def all_norms(self) -> dict[str, dict[str, dict[str, Any]]]:
        return self._norms
