"""Data Collector — буферизация, CRC-валидация, запись эпизодов."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src import config
from src.anonymization.face_blur import FaceBlur
from src.models import EpisodeInput, TopicStats
from src.observability.logger import get_logger
from src.observability.metrics import METRICS

if TYPE_CHECKING:
    from src.quality_evaluator.orchestrator import Orchestrator

logger = get_logger(__name__)

_QUOTA_GB = config.get("data_collector", "quota_gb", 1.0)
_QUOTA_BYTES = int(_QUOTA_GB * 1024**3)
_STORAGE_PATH = Path(config.get("data_collector", "local_path", "data/episodes/"))
_BUFFER_MAXLEN = config.get("data_collector", "buffer_maxlen", 1000)

_face_blur = FaceBlur()


class DataCollector:
    """Принимает ROS-сообщения, буферизует, формирует эпизоды."""

    def __init__(self, orchestrator: "Orchestrator") -> None:
        self._orchestrator = orchestrator
        self._buffer: deque[dict[str, Any]] = deque(maxlen=_BUFFER_MAXLEN)
        self._session_id = str(uuid.uuid4())
        self._current_episode_id: str | None = None
        self._episode_start: str | None = None
        self._frame_count = 0
        self._paused = False
        _STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    def on_message(self, topic: str, message: dict[str, Any]) -> None:
        if self._paused:
            return

        if self._check_disk_quota():
            return

        if self._current_episode_id is None:
            self._start_episode()

        if topic == "/camera/image_raw" and "data" in message:
            message = self._anonymize_frame(message)

        entry = {"topic": topic, "ts_ns": _now_ns(), "msg": message}
        self._buffer.append(entry)

        if topic == "/camera/image_raw":
            self._frame_count += 1

    def flush(self) -> None:
        """Сбросить буфер — завершить текущий эпизод."""
        if self._current_episode_id and self._buffer:
            self._finish_episode()

    def pause(self) -> None:
        self._paused = True
        logger.warning("DataCollector paused", extra={"event": "collector_paused"})

    def resume(self) -> None:
        self._paused = False
        logger.info("DataCollector resumed", extra={"event": "collector_resumed"})

    def _start_episode(self) -> None:
        self._current_episode_id = str(uuid.uuid4())
        self._episode_start = datetime.now(timezone.utc).isoformat()
        self._frame_count = 0
        logger.info(
            "Episode started",
            extra={"event": "episode_start", "episode_id": self._current_episode_id},
        )

    def _finish_episode(self) -> None:
        episode_id = self._current_episode_id
        ended_at = datetime.now(timezone.utc).isoformat()
        messages = list(self._buffer)
        self._buffer.clear()
        self._current_episode_id = None

        saved = self._save_episode_data(episode_id, messages)
        if not saved:
            logger.error("Episode data save failed; rejecting", extra={"event": "episode_save_failed", "episode_id": episode_id})
            METRICS["data_crc_failures_total"].inc()
            return

        stats = _compute_stats(messages)
        topics = list({m["topic"] for m in messages})
        episode = EpisodeInput(
            episode_id=episode_id,
            session_id=self._session_id,
            started_at=self._episode_start,
            ended_at=ended_at,
            topics=topics,
            stats=stats,
            frame_count=self._frame_count,
        )
        METRICS["episodes_total"].inc()

        import threading
        threading.Thread(
            target=self._orchestrator.analyze_episode,
            args=(episode,),
            daemon=True,
        ).start()

    def _save_episode_data(self, episode_id: str, messages: list[dict]) -> bool:
        path = _STORAGE_PATH / f"{episode_id}.json"
        content = json.dumps(messages, default=str).encode()
        expected_hash = hashlib.sha256(content).hexdigest()

        try:
            path.write_bytes(content)
        except OSError as exc:
            logger.error("Write error", extra={"event": "write_error", "error": str(exc)})
            return False

        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            logger.error("CRC mismatch; retrying", extra={"event": "crc_mismatch", "episode_id": episode_id})
            path.write_bytes(content)
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                path.unlink(missing_ok=True)
                return False

        logger.info(
            "Episode saved",
            extra={"event": "episode_saved", "episode_id": episode_id, "sha256": expected_hash},
        )
        return True

    def _check_disk_quota(self) -> bool:
        """Returns True if quota exceeded (collector should pause)."""
        try:
            usage = shutil.disk_usage(_STORAGE_PATH)
            used = _STORAGE_PATH.stat().st_size if _STORAGE_PATH.exists() else 0
            total_size = sum(f.stat().st_size for f in _STORAGE_PATH.rglob("*") if f.is_file())
            METRICS["disk_usage_bytes"].set(total_size)
            if total_size >= _QUOTA_BYTES * 0.9:
                logger.warning(
                    "Disk quota near limit",
                    extra={"event": "disk_quota_warning", "used_gb": total_size / 1024**3},
                )
                if total_size >= _QUOTA_BYTES:
                    self.pause()
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _anonymize_frame(message: dict) -> dict:
        try:
            import base64
            raw = message.get("data", b"")
            if isinstance(raw, str):
                raw = base64.b64decode(raw)
            blurred = _face_blur.process(raw, message.get("width", 640), message.get("height", 480))
            message = {**message, "data": blurred}
        except Exception as exc:
            logger.warning("Anonymization failed", extra={"event": "anon_error", "error": str(exc)})
        return message



def _now_ns() -> int:
    return time.time_ns()


def _compute_stats(messages: list[dict]) -> list[TopicStats]:
    """Агрегировать статистику по каждому топику/полю."""
    import statistics
    from collections import defaultdict

    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    timestamps: dict[str, list[int]] = defaultdict(list)

    for m in messages:
        topic = m["topic"]
        msg = m["msg"]
        ts = m["ts_ns"]
        timestamps[topic].append(ts)

        if topic == "/imu/data":
            for axis in ("x", "y", "z"):
                av = msg.get("angular_velocity", {})
                la = msg.get("linear_acceleration", {})
                if axis in av:
                    buckets[("/imu/angular_velocity", axis)].append(float(av[axis]))
                if axis in la:
                    buckets[("/imu/linear_acceleration", axis)].append(float(la[axis]))

        elif topic == "/odom":
            twist = msg.get("twist", {}).get("twist", {})
            linear = twist.get("linear", {})
            angular = twist.get("angular", {})
            if "x" in linear:
                buckets[("/odom/twist/linear", "x")].append(float(linear["x"]))
            if "z" in angular:
                buckets[("/odom/twist/angular", "z")].append(float(angular["z"]))
            pose = msg.get("pose", {}).get("pose", {}).get("position", {})
            for axis in ("x", "y"):
                if axis in pose:
                    buckets[("/odom/pose/position", axis)].append(float(pose[axis]))

        elif topic == "/camera/image_raw":
            buckets[("/camera/image_raw", "width")].append(float(msg.get("width", 0)))
            buckets[("/camera/image_raw", "height")].append(float(msg.get("height", 0)))

    result: list[TopicStats] = []

    for (topic, field), values in buckets.items():
        if not values:
            continue
        ts_list = timestamps.get(topic, [])
        gaps = [
            (ts_list[i + 1] - ts_list[i]) / 1_000_000  # ns → ms
            for i in range(len(ts_list) - 1)
        ] if len(ts_list) > 1 else [0.0]

        result.append(TopicStats(
            topic=topic,
            field=field,
            min_val=min(values),
            max_val=max(values),
            mean_val=statistics.mean(values),
            std_val=statistics.stdev(values) if len(values) > 1 else 0.0,
            max_gap_ms=max(gaps),
            count=len(values),
        ))

    # Camera FPS
    cam_ts = timestamps.get("/camera/image_raw", [])
    if len(cam_ts) > 1:
        duration_s = (cam_ts[-1] - cam_ts[0]) / 1e9
        fps = len(cam_ts) / duration_s if duration_s > 0 else 0.0
        cam_gaps = [(cam_ts[i + 1] - cam_ts[i]) / 1_000_000 for i in range(len(cam_ts) - 1)]
        result.append(TopicStats(
            topic="/camera/image_raw",
            field="fps",
            min_val=fps,
            max_val=fps,
            mean_val=fps,
            std_val=0.0,
            max_gap_ms=max(cam_gaps),
            count=len(cam_ts),
        ))

    return result
