from unittest.mock import patch

import diag_log


def setup_function():
    diag_log.TRACE_FILE.unlink(missing_ok=True)
    for i in range(1, 4):
        rotated = diag_log.TRACE_FILE.with_name(f"activity_trace.{i}.jsonl")
        rotated.unlink(missing_ok=True)


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
