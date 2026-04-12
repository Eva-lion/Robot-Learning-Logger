"""Анонимизация camera-фреймов: обнаружение и замыливание лиц."""

from __future__ import annotations

import hashlib

from src.observability.logger import get_logger

logger = get_logger(__name__)

# Processed frame cache to avoid re-processing identical frames
_processed_cache: dict[str, bytes] = {}
_CACHE_MAX = 256


class FaceBlur:
    """
    Детектирует лица на кадре и применяет Gaussian blur.
    При невозможности загрузить OpenCV — работает в passthrough-режиме с предупреждением.
    """

    def __init__(self) -> None:
        self._cv2 = None
        self._detector = None
        self._enabled = False
        self._init_cv()

    def _init_cv(self) -> None:
        try:
            import cv2  # type: ignore
            self._cv2 = cv2
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._detector = cv2.CascadeClassifier(cascade_path)
            self._enabled = True
            logger.info("FaceBlur initialized with OpenCV", extra={"event": "face_blur_init"})
        except Exception as exc:
            logger.warning(
                "OpenCV unavailable; anonymization disabled",
                extra={"event": "face_blur_disabled", "error": str(exc)},
            )

    def process(self, raw_bytes: bytes, width: int = 640, height: int = 480) -> bytes:
        """
        Принимает raw bytes изображения (BGR), возвращает bytes с размытыми лицами.
        Если OpenCV недоступен — возвращает оригинал.
        """
        if not self._enabled or not raw_bytes:
            return raw_bytes

        frame_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
        if frame_hash in _processed_cache:
            return _processed_cache[frame_hash]

        try:
            result = self._blur_faces(raw_bytes, width, height)
        except Exception as exc:
            logger.warning("Face blur error; returning original", extra={"event": "face_blur_error", "error": str(exc)})
            result = raw_bytes

        if len(_processed_cache) >= _CACHE_MAX:
            _processed_cache.pop(next(iter(_processed_cache)))
        _processed_cache[frame_hash] = result
        return result

    def _blur_faces(self, raw_bytes: bytes, width: int, height: int) -> bytes:
        cv2 = self._cv2
        import numpy as np

        arr = np.frombuffer(raw_bytes, dtype=np.uint8)

        # Try to decode as image; if fails, interpret as raw pixel buffer
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            # Raw pixel buffer (e.g. from ROS sensor_msgs/Image)
            try:
                img = arr.reshape((height, width, 3))
            except ValueError:
                return raw_bytes

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = self._detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
        )

        if len(faces) == 0:
            _, buf = cv2.imencode(".jpg", img)
            return buf.tobytes()

        for x, y, w, h in faces:
            roi = img[y : y + h, x : x + w]
            blurred_roi = cv2.GaussianBlur(roi, (99, 99), 30)
            img[y : y + h, x : x + w] = blurred_roi

        _, buf = cv2.imencode(".jpg", img)
        logger.info(
            "Faces blurred",
            extra={"event": "faces_blurred", "count": len(faces)},
        )
        return buf.tobytes()
