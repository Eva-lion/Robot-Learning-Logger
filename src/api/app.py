"""FastAPI Monitoring API — read-only интерфейс для ML Engineer."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware

from src import config
from src.memory_hub import db
from src.observability.logger import get_logger

logger = get_logger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_API_KEY = config.env("API_KEY", "dev-key-change-me")


def _require_api_key(key: str | None = Security(_API_KEY_HEADER)) -> str:
    if not key or key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return key


def create_app() -> FastAPI:
    app = FastAPI(
        title="Robot Learning Logger — Monitoring API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://127.0.0.1"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/episodes")
    def list_episodes(
        status: str | None = None,
        limit: int = 50,
        _key: str = Depends(_require_api_key),
    ) -> list[dict]:
        if limit > 200:
            limit = 200
        return db.get_episodes(status=status, limit=limit)

    @app.get("/episodes/{episode_id}")
    def get_episode(episode_id: str, _key: str = Depends(_require_api_key)) -> dict:
        ep = db.get_episode(episode_id)
        if not ep:
            raise HTTPException(status_code=404, detail="Episode not found")
        report = db.get_report_by_episode(episode_id)
        return {"episode": ep, "report": report}

    @app.get("/metrics/summary")
    def metrics_summary(_key: str = Depends(_require_api_key)) -> dict:
        return db.get_metrics_summary()

    @app.post("/episodes/{episode_id}/approve")
    def approve_episode(
        episode_id: str,
        _key: str = Depends(_require_api_key),
    ) -> dict:
        ep = db.get_episode(episode_id)
        if not ep:
            raise HTTPException(status_code=404, detail="Episode not found")
        db.update_episode_status(episode_id, "APPROVED", notes="Approved by ML Engineer")
        logger.info(
            "Episode approved",
            extra={"event": "episode_approved", "episode_id": episode_id},
        )
        return {"episode_id": episode_id, "status": "APPROVED"}

    @app.post("/episodes/{episode_id}/reject")
    async def reject_episode(
        episode_id: str,
        request: Request,
        _key: str = Depends(_require_api_key),
    ) -> dict:
        ep = db.get_episode(episode_id)
        if not ep:
            raise HTTPException(status_code=404, detail="Episode not found")

        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        reason = str(body.get("reason", "Rejected by ML Engineer"))[:500]  # limit reason length

        db.update_episode_status(episode_id, "REJECTED_MANUAL", notes=reason)
        db.insert_rejected_pattern(episode_id, pattern=reason, reason=reason)
        logger.info(
            "Episode rejected",
            extra={"event": "episode_rejected", "episode_id": episode_id, "reason": reason},
        )
        return {"episode_id": episode_id, "status": "REJECTED_MANUAL"}

    return app
