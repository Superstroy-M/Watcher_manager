import json
from pathlib import Path

import diag_log


def test_log_event_writes_jsonl_in_debug_mode(tmp_path, monkeypatch):
    trace_file = tmp_path / "activity_trace.jsonl"
    monkeypatch.setattr(diag_log, "TRACE_FILE", trace_file)
    monkeypatch.setattr(diag_log, "DEBUG_MODE", True)

    diag_log.log_event(
        "activity_segment",
        "tracker",
        process_name="excel.exe",
        window_title="Secret report.xlsx",
        duration_seconds=120,
        segment_type="focus",
    )

    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["type"] == "activity_segment"
    assert record["component"] == "tracker"
    assert record["process_name"] == "excel.exe"
    assert record["duration_seconds"] == 120
    assert "window_title" not in record


def test_log_event_skipped_when_debug_disabled(tmp_path, monkeypatch):
    trace_file = tmp_path / "activity_trace.jsonl"
    monkeypatch.setattr(diag_log, "TRACE_FILE", trace_file)
    monkeypatch.setattr(diag_log, "DEBUG_MODE", False)

    diag_log.log_event("agent_start", "app", version="1.1")
    assert not trace_file.exists()


def test_log_event_rotation(tmp_path, monkeypatch):
    trace = tmp_path / "activity_trace.jsonl"
    monkeypatch.setattr(diag_log, "TRACE_FILE", trace)
    monkeypatch.setattr(diag_log, "TRACE_MAX_BYTES", 200)
    monkeypatch.setattr(diag_log, "TRACE_KEEP_ROTATED", 2)
    monkeypatch.setattr(diag_log, "DEBUG_MODE", True)

    for i in range(30):
        diag_log.log_event("test", "unit", idx=i, payload="x" * 20)

    assert trace.exists()
    assert trace.stat().st_size <= 200 + 100


def test_truncate_text_limits_long_titles():
    long_title = "A" * 200
    result = diag_log.truncate_text(long_title, limit=50)
    assert len(result) == 53
    assert result.endswith("...")


def test_sanitize_blocks_sensitive_fields():
    clean = diag_log._sanitize_fields(
        {
            "process_name": "chrome.exe",
            "window_title": "Secret",
            "password": "123",
            "error": "x" * 300,
        }
    )
    assert clean["process_name"] == "chrome.exe"
    assert "window_title" not in clean
    assert "password" not in clean
    assert len(clean["error"]) <= 243


def test_is_debug_mode_flag(monkeypatch):
    monkeypatch.setattr(diag_log, "DEBUG_MODE", True)
    assert diag_log.is_debug_mode() is True
    monkeypatch.setattr(diag_log, "DEBUG_MODE", False)
    assert diag_log.is_debug_mode() is False
