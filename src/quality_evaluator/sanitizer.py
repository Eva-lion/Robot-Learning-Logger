"""Sanitizer — защита от prompt injection перед LLM-вызовом."""

from __future__ import annotations

from src.observability.logger import get_logger
from src.observability.metrics import METRICS

logger = get_logger(__name__)

# Токен-лимит (приблизительная оценка: 1 токен ≈ 4 символа)
_MAX_TOKENS_APPROX = 3500
_MAX_CHARS = _MAX_TOKENS_APPROX * 4

# Блок-лист опасных паттернов
_BLOCKLIST = [
    "exec(",
    "eval(",
    "__import__",
    "os.system",
    "os.path",
    "sys.exit",
    "subprocess",
    "open(",
    "__class__",
    "__builtins__",
    "ignore previous instructions",
    "ignore all previous",
    "you are now",
    "disregard your",
    "forget everything",
    "new persona",
    "act as if",
]


class SanitizerBlockError(ValueError):
    """Raised when input is blocked by the sanitizer."""


def sanitize(text: str) -> str:
    """
    Проверяет текст на наличие запрещённых паттернов и лимит длины.
    Возвращает текст (возможно, усечённый) или поднимает SanitizerBlockError.
    """
    lower = text.lower()
    for pattern in _BLOCKLIST:
        if pattern.lower() in lower:
            METRICS["sanitizer_blocks_total"].inc()
            logger.warning(
                "Sanitizer blocked input",
                extra={"event": "sanitizer_block", "pattern": pattern},
            )
            raise SanitizerBlockError(f"Blocked pattern detected: '{pattern}'")

    if len(text) > _MAX_CHARS:
        truncated = text[:_MAX_CHARS]
        logger.warning(
            "Input truncated by sanitizer",
            extra={"event": "sanitizer_truncate", "original_len": len(text), "limit": _MAX_CHARS},
        )
        return truncated + "\n[data truncated due to length limit]"

    return text
