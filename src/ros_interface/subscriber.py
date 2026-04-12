"""
ROS subscriber — подписка на топики ROS.

Поддерживаемые режимы:
  - roslibpy: подключение через rosbridge WebSocket (не требует ROS окружения)
  - rclpy: нативный ROS 2 (только если rclpy установлен)
  - mock: для тестирования без ROS
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Callable

from src import config
from src.observability.logger import get_logger
from src.observability.metrics import METRICS

if TYPE_CHECKING:
    from src.data_collector.collector import DataCollector

logger = get_logger(__name__)

TOPICS = ["/odom", "/imu/data", "/camera/image_raw"]
_HEARTBEAT_TIMEOUT = config.get("ros", "heartbeat_timeout_s", 5)
_RECONNECT_RETRIES = config.get("ros", "reconnect_retries", 3)


class ROSSubscriber:
    """Абстракция подписки на ROS-топики."""

    def __init__(self, collector: "DataCollector") -> None:
        self._collector = collector
        self._mode = config.get("ros", "mode", "roslibpy")
        self._client: object | None = None
        self._subscriptions: list = []
        self._connected = False
        self._reconnect_count = 0
        self._heartbeat_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def connect(self) -> None:
        if self._mode == "roslibpy":
            self._connect_roslibpy()
        elif self._mode == "rclpy":
            self._connect_rclpy()
        else:
            logger.warning("ROS mode not recognised; running without ROS", extra={"event": "ros_no_connect"})
            return

        self._start_heartbeat()

    def disconnect(self) -> None:
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=3)
        if self._mode == "roslibpy" and self._client:
            try:
                for sub in self._subscriptions:
                    sub.unsubscribe()
                self._client.terminate()  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning("Error during ROS disconnect", extra={"event": "ros_disconnect_error", "error": str(exc)})
        self._connected = False
        METRICS["ros_connected"].set(0)

    def _connect_roslibpy(self) -> None:
        try:
            import roslibpy
        except ImportError:
            logger.warning("roslibpy not installed; skipping ROS connection", extra={"event": "roslibpy_missing"})
            return

        host = config.get("ros", "host", "localhost")
        port = config.get("ros", "port", 9090)
        self._client = roslibpy.Ros(host=host, port=port)

        try:
            self._client.run(timeout=_HEARTBEAT_TIMEOUT)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.error("Cannot connect to ROS bridge", extra={"event": "ros_connect_failed", "error": str(exc)})
            return

        self._connected = True
        METRICS["ros_connected"].set(1)

        for topic_name in TOPICS:
            msg_type = _topic_type(topic_name)
            listener = roslibpy.Topic(self._client, topic_name, msg_type)
            callback = self._make_callback(topic_name)
            listener.subscribe(callback)
            self._subscriptions.append(listener)

        logger.info("Subscribed to ROS topics", extra={"event": "ros_subscribed", "topics": TOPICS})

    def _make_callback(self, topic: str) -> Callable[[dict], None]:
        def _cb(message: dict) -> None:
            self._collector.on_message(topic, message)
        return _cb

    def _connect_rclpy(self) -> None:
        try:
            import rclpy  # noqa: F401
        except ImportError:
            logger.warning("rclpy not available", extra={"event": "rclpy_missing"})
            return
        logger.info("rclpy mode: not fully implemented in PoC", extra={"event": "rclpy_stub"})

    def _start_heartbeat(self) -> None:
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(_HEARTBEAT_TIMEOUT)
            if self._stop_event.is_set():
                break
            if self._mode == "roslibpy" and self._client:
                try:
                    is_connected = self._client.is_connected  # type: ignore[attr-defined]
                except Exception:
                    is_connected = False

                if not is_connected and not self._stop_event.is_set():
                    self._reconnect_count += 1
                    METRICS["ros_reconnects_total"].inc()
                    logger.warning(
                        "ROS connection lost; attempting reconnect",
                        extra={"event": "ros_reconnect", "attempt": self._reconnect_count},
                    )
                    if self._reconnect_count <= _RECONNECT_RETRIES:
                        try:
                            self._client.run(timeout=_HEARTBEAT_TIMEOUT)  # type: ignore[attr-defined]
                            self._reconnect_count = 0
                            METRICS["ros_connected"].set(1)
                        except Exception as exc:
                            logger.error("Reconnect failed", extra={"event": "ros_reconnect_failed", "error": str(exc)})
                            METRICS["ros_connected"].set(0)
                    else:
                        logger.error("Max reconnect attempts reached; pausing collector", extra={"event": "ros_max_reconnects"})
                        self._collector.pause()
                        break


def _topic_type(topic: str) -> str:
    _types = {
        "/odom": "nav_msgs/Odometry",
        "/imu/data": "sensor_msgs/Imu",
        "/camera/image_raw": "sensor_msgs/Image",
    }
    return _types.get(topic, "std_msgs/String")
