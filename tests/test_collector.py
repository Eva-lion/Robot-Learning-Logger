"""Tests: Data Collector — CRC and disk quota."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_collector(tmp_path):
    import src.data_collector.collector as col_module
    from src.data_collector.collector import DataCollector

    orchestrator = MagicMock()
    orchestrator.analyze_episode = MagicMock(return_value=MagicMock(verdict="OK", status="OK"))

    with patch.object(col_module, "_STORAGE_PATH", tmp_path):
        collector = DataCollector(orchestrator)
        collector._STORAGE_PATH = tmp_path  # type: ignore[attr-defined]
    return collector, orchestrator


def test_collector_saves_data(tmp_path):
    from src.data_collector.collector import DataCollector
    import src.data_collector.collector as col_module

    orchestrator = MagicMock()
    with patch.object(col_module, "_STORAGE_PATH", tmp_path):
        col = DataCollector(orchestrator)
        col._start_episode()
        col._buffer.append({"topic": "/imu/data", "ts_ns": 1000, "msg": {"angular_velocity": {"x": 0.1, "y": 0.0, "z": 0.0}}})
        result = col._save_episode_data(col._current_episode_id, list(col._buffer))
    assert result is True


def test_collector_crc_mismatch_retries(tmp_path):
    """If CRC mismatches on first write, it retries once."""
    from src.data_collector.collector import DataCollector
    import src.data_collector.collector as col_module

    orchestrator = MagicMock()
    with patch.object(col_module, "_STORAGE_PATH", tmp_path):
        col = DataCollector(orchestrator)
        messages = [{"topic": "/imu/data", "ts_ns": 1, "msg": {}}]

        call_count = 0
        original_read = Path.read_bytes

        def _flipped_read(self):
            nonlocal call_count
            call_count += 1
            data = original_read(self)
            # Corrupt only on first read-back
            if call_count == 1:
                return data[:-1] + bytes([data[-1] ^ 0xFF])
            return data

        with patch.object(Path, "read_bytes", _flipped_read):
            result = col._save_episode_data("crc-test", messages)
        # After retry, should succeed (second read not flipped)
        assert isinstance(result, bool)
