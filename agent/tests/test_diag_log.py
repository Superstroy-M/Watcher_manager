import json
from pathlib import Path

import diag_log


def test_log_event_writes_jsonl(tmp_path, monkeypatch):
    trace_file = tmp_path / "activity_trace.jsonl"
    monkeypatch.setattr(diag_log, "TRACE_FILE", trace_file)
    monkeypatch.setattr(diag_log, "DIAG_ENABLED", True)

    diag_log.log_event(
        "activity_segment",
        "tracker",
        process_name="excel.exe",
        window_title="Отчёт.xlsx",
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


def test_log_event_respects_disabled(tmp_path, monkeypatch):
    trace_file = tmp_path / "activity_trace.jsonl"
    monkeypatch.setattr(diag_log, "TRACE_FILE", trace_file)
    monkeypatch.setattr(diag_log, "DIAG_ENABLED", False)

    diag_log.log_event("agent_start", "app", version="1.1")
    assert not trace_file.exists()
