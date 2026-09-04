"""
Тесты activity_log.py — аналитика событий, таймлайны, отчёты.
S3-вызовы полностью замокированы.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call


# ══════════════════════════════════════════════════════════════════════════════
#  _get_app_name
# ══════════════════════════════════════════════════════════════════════════════

class TestGetAppName:

    def test_known_process(self):
        from activity_log import _get_app_name
        assert _get_app_name("chrome.exe") == "Google Chrome"

    def test_known_process_1c(self):
        from activity_log import _get_app_name
        assert _get_app_name("1cv8.exe") == "1С:Предприятие"

    def test_unknown_process_returns_itself(self):
        from activity_log import _get_app_name
        assert _get_app_name("myprog.exe") == "myprog.exe"

    def test_none_returns_unknown(self):
        from activity_log import _get_app_name
        assert _get_app_name(None) == "unknown"

    def test_empty_returns_unknown(self):
        from activity_log import _get_app_name
        assert _get_app_name("") == "unknown"

    def test_case_insensitive(self):
        from activity_log import _get_app_name
        # Должен быть lowercase в словаре
        assert _get_app_name("EXCEL.EXE".lower()) == "Microsoft Excel"

    def test_idle_pseudo_process(self):
        from activity_log import _get_app_name
        assert _get_app_name("idle") == "Простой"


# ══════════════════════════════════════════════════════════════════════════════
#  _get_category
# ══════════════════════════════════════════════════════════════════════════════

class TestGetCategory:

    def test_browser_category(self):
        from activity_log import _get_category
        for proc in ["chrome.exe", "firefox.exe", "msedge.exe", "opera.exe"]:
            assert _get_category(proc) == "browser", f"Failed for {proc}"

    def test_office_category(self):
        from activity_log import _get_category
        assert _get_category("excel.exe") == "office"
        assert _get_category("word.exe") == "office"

    def test_erp_category(self):
        from activity_log import _get_category
        assert _get_category("1cv8.exe") == "erp"

    def test_communication_category(self):
        from activity_log import _get_category
        assert _get_category("teams.exe") == "communication"
        assert _get_category("zoom.exe") == "communication"

    def test_development_category(self):
        from activity_log import _get_category
        assert _get_category("code.exe") == "development"
        assert _get_category("pycharm64.exe") == "development"

    def test_unknown_returns_other(self):
        from activity_log import _get_category
        assert _get_category("random_app.exe") == "other"

    def test_none_returns_other(self):
        from activity_log import _get_category
        assert _get_category(None) == "other"


# ══════════════════════════════════════════════════════════════════════════════
#  _get_productivity
# ══════════════════════════════════════════════════════════════════════════════

class TestGetProductivity:

    def test_productive_app(self):
        from activity_log import _get_productivity
        assert _get_productivity("excel.exe") == "productive"
        assert _get_productivity("1cv8.exe") == "productive"
        assert _get_productivity("word.exe") == "productive"
        assert _get_productivity("devenv.exe") == "productive"

    def test_distracting_app_directly(self):
        from activity_log import _get_productivity
        assert _get_productivity("discord.exe") == "distracting"

    def test_neutral_app(self):
        from activity_log import _get_productivity
        assert _get_productivity("telegram.exe") == "neutral"

    def test_browser_neutral_no_site(self):
        from activity_log import _get_productivity
        assert _get_productivity("chrome.exe", "GitHub — Pull Requests") == "neutral"

    def test_browser_distracting_with_site(self):
        from activity_log import _get_productivity
        assert _get_productivity("chrome.exe", "YouTube — watch videos") == "distracting"
        assert _get_productivity("firefox.exe", "vk.com — new post") == "distracting"
        assert _get_productivity("msedge.exe", "reddit thread") == "distracting"

    def test_idle_productivity(self):
        from activity_log import _get_productivity
        assert _get_productivity("idle") == "idle"

    def test_unknown_app_neutral(self):
        from activity_log import _get_productivity
        assert _get_productivity("myapp.exe") == "neutral"

    def test_none_app_neutral(self):
        from activity_log import _get_productivity
        assert _get_productivity(None) == "neutral"


# ══════════════════════════════════════════════════════════════════════════════
#  _ts_to_sec
# ══════════════════════════════════════════════════════════════════════════════

class TestTsToSec:

    def test_hms_format(self):
        from activity_log import _ts_to_sec
        assert _ts_to_sec("09:00:00") == 9 * 3600
        assert _ts_to_sec("00:00:00") == 0
        assert _ts_to_sec("23:59:59") == 23 * 3600 + 59 * 60 + 59

    def test_iso_datetime_format(self):
        from activity_log import _ts_to_sec
        assert _ts_to_sec("2024-01-15T10:30:00") == 10 * 3600 + 30 * 60

    def test_iso_with_space_separator(self):
        from activity_log import _ts_to_sec
        assert _ts_to_sec("2024-01-15 14:00:00") == 14 * 3600

    def test_invalid_returns_zero(self):
        from activity_log import _ts_to_sec
        assert _ts_to_sec("") == 0
        assert _ts_to_sec("invalid") == 0
        assert _ts_to_sec(None) == 0

    def test_midnight(self):
        from activity_log import _ts_to_sec
        assert _ts_to_sec("00:00:01") == 1

    def test_end_of_day(self):
        from activity_log import _ts_to_sec
        assert _ts_to_sec("23:59:59") == 86399


# ══════════════════════════════════════════════════════════════════════════════
#  _fmt
# ══════════════════════════════════════════════════════════════════════════════

class TestFmt:

    def test_seconds_only(self):
        from activity_log import _fmt
        assert _fmt(0) == "0с"
        assert _fmt(30) == "30с"
        assert _fmt(59) == "59с"

    def test_minutes(self):
        from activity_log import _fmt
        assert _fmt(60) == "1м 0с"
        assert _fmt(90) == "1м 30с"
        assert _fmt(3599) == "59м 59с"

    def test_hours(self):
        from activity_log import _fmt
        assert _fmt(3600) == "1ч 0м"
        assert _fmt(7260) == "2ч 1м"
        assert _fmt(9000) == "2ч 30м"


# ══════════════════════════════════════════════════════════════════════════════
#  _session_id
# ══════════════════════════════════════════════════════════════════════════════

class TestSessionId:

    def test_deterministic(self):
        from activity_log import _session_id
        a = _session_id("pc-01", "2024-01-15T09:00:00", "chrome.exe")
        b = _session_id("pc-01", "2024-01-15T09:00:00", "chrome.exe")
        assert a == b

    def test_different_for_different_inputs(self):
        from activity_log import _session_id
        a = _session_id("pc-01", "2024-01-15T09:00:00", "chrome.exe")
        b = _session_id("pc-01", "2024-01-15T09:00:00", "excel.exe")
        assert a != b

    def test_length_12(self):
        from activity_log import _session_id
        sid = _session_id("host", "ts", "app")
        assert len(sid) == 12


# ══════════════════════════════════════════════════════════════════════════════
#  get_activity_for_screenshot
# ══════════════════════════════════════════════════════════════════════════════

class TestGetActivityForScreenshot:

    def _make_event(self, ts: str, proc: str, etype: str = "focus") -> dict:
        return {
            "timestamp": ts,
            "app": proc,
            "app_name": proc,
            "window_title": "",
            "event_type": etype,
            "productivity": "neutral",
        }

    def test_returns_nearest_event(self):
        from activity_log import get_activity_for_screenshot
        activity = [
            self._make_event("09:00:00", "excel.exe"),
            self._make_event("09:10:00", "word.exe"),
        ]
        # 60 секунд от 09:00:00 — должен найти excel.exe
        result = get_activity_for_screenshot(activity, "09:01:00")
        assert result is not None
        assert result["app"] == "excel.exe"

    def test_returns_none_when_too_far(self):
        from activity_log import get_activity_for_screenshot
        activity = [self._make_event("09:00:00", "excel.exe")]
        # >90 сек разница — не считается
        result = get_activity_for_screenshot(activity, "09:02:01")
        assert result is None

    def test_returns_none_for_empty_list(self):
        from activity_log import get_activity_for_screenshot
        assert get_activity_for_screenshot([], "09:00:00") is None

    def test_skips_idle_events(self):
        from activity_log import get_activity_for_screenshot
        activity = [
            self._make_event("09:00:00", "idle", "idle"),
            self._make_event("09:00:30", "excel.exe", "focus"),
        ]
        result = get_activity_for_screenshot(activity, "09:00:00")
        assert result["app"] == "excel.exe"

    def test_exact_match(self):
        from activity_log import get_activity_for_screenshot
        activity = [self._make_event("10:30:00", "chrome.exe")]
        result = get_activity_for_screenshot(activity, "10:30:00")
        assert result["app"] == "chrome.exe"

    def test_boundary_90_seconds(self):
        from activity_log import get_activity_for_screenshot
        # ровно 89 секунд — должен найти
        activity = [self._make_event("10:00:00", "word.exe")]
        result = get_activity_for_screenshot(activity, "10:01:29")
        assert result is not None
        # ровно 90 секунд — не должен найти
        result2 = get_activity_for_screenshot(activity, "10:01:30")
        assert result2 is None


# ══════════════════════════════════════════════════════════════════════════════
#  save_activity (с моком S3)
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveActivity:

    @pytest.fixture(autouse=True)
    def mock_s3(self, mocker):
        self.put_mock = mocker.patch("activity_log._s3_put")
        # По умолчанию S3 пуст (нет существующей активности)
        mocker.patch("activity_log._s3_get_json", return_value=[])

    def _event(self, proc="chrome.exe", started="2024-01-15T09:00:00",
                ended="2024-01-15T09:05:00", dur=300, etype="focus"):
        return {
            "started_at": started,
            "ended_at": ended,
            "duration_seconds": dur,
            "process_name": proc,
            "window_title": f"{proc} — Window",
            "event_type": etype,
            "productivity": "neutral",
        }

    def test_save_new_events(self):
        from activity_log import save_activity
        save_activity("test-pc", "2024-01-15", [self._event()])
        assert self.put_mock.called
        # должен вызваться 3 раза: activity.json, timeline.json, summary.json
        files_saved = {call_args[0][2] for call_args in self.put_mock.call_args_list}
        assert "activity.json" in files_saved
        assert "timeline.json" in files_saved
        assert "summary.json" in files_saved

    def test_activity_json_contains_enriched_data(self):
        from activity_log import save_activity
        save_activity("test-pc", "2024-01-15", [self._event("excel.exe")])
        # Найдём вызов для activity.json
        for c in self.put_mock.call_args_list:
            if c[0][2] == "activity.json":
                content = json.loads(c[0][3])
                assert len(content) == 1
                assert content[0]["app"] == "excel.exe"
                assert content[0]["app_name"] == "Microsoft Excel"
                assert content[0]["productivity"] == "productive"
                assert content[0]["category"] == "office"
                break
        else:
            pytest.fail("activity.json was not saved")

    def test_deduplication_prevents_re_adding(self, mocker):
        from activity_log import save_activity
        existing = [{
            "timestamp": "2024-01-15T09:00:00",
            "ended_at": "2024-01-15T09:05:00",
            "app": "chrome.exe",
            "app_name": "Google Chrome",
            "event_type": "focus",
            "productivity": "neutral",
            "category": "browser",
            "duration_seconds": 300,
            "active": True,
            "session_id": "abc123",
            "screenshot": None,
            "window_title": "",
        }]
        mocker.patch("activity_log._s3_get_json", return_value=existing)
        # Пытаемся добавить то же событие ещё раз
        save_activity("test-pc", "2024-01-15", [self._event("chrome.exe")])
        # В activity.json должен быть только 1 элемент
        for c in self.put_mock.call_args_list:
            if c[0][2] == "activity.json":
                content = json.loads(c[0][3])
                assert len(content) == 1
                break

    def test_sorts_events_by_timestamp(self):
        from activity_log import save_activity
        events = [
            self._event(proc="word.exe",  started="2024-01-15T10:00:00"),
            self._event(proc="excel.exe", started="2024-01-15T09:00:00"),
        ]
        save_activity("test-pc", "2024-01-15", events)
        for c in self.put_mock.call_args_list:
            if c[0][2] == "activity.json":
                content = json.loads(c[0][3])
                assert content[0]["app"] == "excel.exe"
                assert content[1]["app"] == "word.exe"
                break


# ══════════════════════════════════════════════════════════════════════════════
#  _save_timeline
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveTimeline:

    @pytest.fixture(autouse=True)
    def mock_s3_put(self, mocker):
        self.put_mock = mocker.patch("activity_log._s3_put")

    def _ev(self, app, started, ended, etype="focus", dur=300, title=""):
        return {
            "timestamp": started,
            "ended_at": ended,
            "app": app,
            "app_name": app,
            "window_title": title,
            "event_type": etype,
            "productivity": "neutral",
            "category": "other",
            "duration_seconds": dur,
            "session_id": "sid",
            "active": etype != "idle",
            "screenshot": None,
        }

    def test_same_app_sessions_merged(self):
        from activity_log import _save_timeline
        events = [
            self._ev("excel.exe", "09:00:00", "09:05:00"),
            self._ev("excel.exe", "09:05:10", "09:10:00"),  # пауза 10с — сливаем
        ]
        _save_timeline("pc", "2024-01-15", events)
        content = json.loads(self.put_mock.call_args[0][3])
        assert len(content) == 1
        assert content[0]["app"] == "excel.exe"
        assert content[0]["duration_seconds"] == 600

    def test_different_apps_create_separate_sessions(self):
        from activity_log import _save_timeline
        events = [
            self._ev("excel.exe", "09:00:00", "09:05:00"),
            self._ev("chrome.exe", "09:05:00", "09:10:00"),
        ]
        _save_timeline("pc", "2024-01-15", events)
        content = json.loads(self.put_mock.call_args[0][3])
        assert len(content) == 2
        assert content[0]["app"] == "excel.exe"
        assert content[1]["app"] == "chrome.exe"

    def test_idle_creates_separate_entry(self):
        from activity_log import _save_timeline
        events = [
            self._ev("excel.exe", "09:00:00", "09:10:00"),
            self._ev("idle",      "09:10:00", "09:30:00", etype="idle", dur=1200),
            self._ev("excel.exe", "09:30:00", "09:40:00"),
        ]
        _save_timeline("pc", "2024-01-15", events)
        content = json.loads(self.put_mock.call_args[0][3])
        assert len(content) == 3
        apps = [s["app"] for s in content]
        assert apps == ["excel.exe", "idle", "excel.exe"]

    def test_large_gap_creates_new_session(self):
        from activity_log import _save_timeline
        # Разные заголовки окон + пауза 120с > 90с → две сессии
        events = [
            self._ev("chrome.exe", "09:00:00", "09:01:00", title="Page A"),
            self._ev("chrome.exe", "09:03:00", "09:04:00", title="Page B"),
        ]
        _save_timeline("pc", "2024-01-15", events)
        content = json.loads(self.put_mock.call_args[0][3])
        assert len(content) == 2

    def test_empty_events(self):
        from activity_log import _save_timeline
        _save_timeline("pc", "2024-01-15", [])
        content = json.loads(self.put_mock.call_args[0][3])
        assert content == []


# ══════════════════════════════════════════════════════════════════════════════
#  _save_summary
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveSummary:

    @pytest.fixture(autouse=True)
    def mock_s3_put(self, mocker):
        self.put_mock = mocker.patch("activity_log._s3_put")

    def _ev(self, app, dur=300, etype="focus", prod="neutral"):
        return {
            "timestamp": "2024-01-15T09:00:00",
            "ended_at": "2024-01-15T09:05:00",
            "app": app,
            "event_type": etype,
            "productivity": prod,
            "duration_seconds": dur,
        }

    def test_basic_summary(self):
        from activity_log import _save_summary
        _save_summary("pc", "2024-01-15", [
            self._ev("excel.exe", dur=3600, prod="productive"),
        ])
        content = json.loads(self.put_mock.call_args[0][3])
        assert content["active_seconds"] == 3600
        assert content["idle_seconds"] == 0
        assert content["productivity"]["productive_percent"] == 100

    def test_idle_counted_separately(self):
        from activity_log import _save_summary
        _save_summary("pc", "2024-01-15", [
            self._ev("excel.exe", dur=3000, prod="productive"),
            self._ev("idle",      dur=600,  etype="idle"),
        ])
        content = json.loads(self.put_mock.call_args[0][3])
        assert content["active_seconds"] == 3000
        assert content["idle_seconds"] == 600
        assert content["total_seconds"] == 3600

    def test_top_apps_sorted_by_seconds(self):
        from activity_log import _save_summary
        _save_summary("pc", "2024-01-15", [
            self._ev("word.exe",  dur=1000),
            self._ev("excel.exe", dur=2000),
            self._ev("chrome.exe",dur=500),
        ])
        content = json.loads(self.put_mock.call_args[0][3])
        top = content["top_apps"]
        assert top[0]["app"] == "excel.exe"
        assert top[1]["app"] == "word.exe"

    def test_empty_events(self):
        from activity_log import _save_summary
        _save_summary("pc", "2024-01-15", [])
        content = json.loads(self.put_mock.call_args[0][3])
        assert content["active_seconds"] == 0
        assert content["idle_seconds"] == 0
        assert content["productivity"]["productive_percent"] == 0

    def test_switch_count(self):
        from activity_log import _save_summary
        _save_summary("pc", "2024-01-15", [
            self._ev("excel.exe"),
            self._ev("chrome.exe"),
            self._ev("excel.exe"),
        ])
        content = json.loads(self.put_mock.call_args[0][3])
        assert content["switch_count"] == 3

    def test_distracting_seconds_tracked(self):
        from activity_log import _save_summary
        _save_summary("pc", "2024-01-15", [
            self._ev("discord.exe", dur=1800, prod="distracting"),
            self._ev("excel.exe",   dur=7200, prod="productive"),
        ])
        content = json.loads(self.put_mock.call_args[0][3])
        assert content["productivity"]["distracting_seconds"] == 1800
        assert content["productivity"]["productive_seconds"] == 7200


# ══════════════════════════════════════════════════════════════════════════════
#  build_report_html
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildReportHtml:

    @pytest.fixture(autouse=True)
    def mock_s3(self, mocker):
        self.put_mock = mocker.patch("activity_log._s3_put")
        mocker.patch("activity_log._s3_get_json", side_effect=lambda h, d, f: (
            {} if f == "summary.json" else []
        ))

    def test_returns_html_string(self):
        from activity_log import build_report_html
        html = build_report_html("test-pc", "2024-01-15")
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_hostname_and_day(self):
        from activity_log import build_report_html
        html = build_report_html("myhost", "2024-06-15")
        assert "myhost" in html
        assert "2024-06-15" in html

    def test_saves_report_to_s3(self):
        from activity_log import build_report_html
        build_report_html("test-pc", "2024-01-15")
        files_saved = {c[0][2] for c in self.put_mock.call_args_list}
        assert "report.html" in files_saved

    def test_html_structure_valid(self):
        from activity_log import build_report_html
        html = build_report_html("test-pc", "2024-01-15")
        assert "<html" in html
        assert "</html>" in html
        assert "<body" in html
        assert "</body>" in html

    def test_with_summary_data(self, mocker):
        from activity_log import build_report_html
        mocker.patch("activity_log._s3_get_json", side_effect=lambda h, d, f: (
            {
                "active_formatted": "2ч 0м",
                "idle_formatted": "30м",
                "first_event": "2024-01-15T09:00:00",
                "last_event": "2024-01-15T18:00:00",
                "switch_count": 25,
                "top_apps": [],
                "productivity": {
                    "productive_percent": 75,
                    "productive_formatted": "1ч 30м",
                    "distracting_formatted": "10м",
                },
            } if f == "summary.json" else []
        ))
        html = build_report_html("test-pc", "2024-01-15")
        assert "2ч 0м" in html
        assert "75" in html


class TestActivityPatterns:
    def test_build_activity_patterns_detects_repeats(self):
        from activity_log import _build_activity_patterns

        events = []
        for i in range(6):
            events.append({
                "timestamp": f"2024-01-15T09:0{i}:00",
                "ended_at": f"2024-01-15T09:0{i}:30",
                "duration_seconds": 30,
                "app": "excel.exe",
                "window_title": "Отчёт продаж.xlsx",
                "event_type": "focus",
            })
            events.append({
                "timestamp": f"2024-01-15T09:0{i}:30",
                "ended_at": f"2024-01-15T09:0{i}:45",
                "duration_seconds": 15,
                "app": "chrome.exe",
                "window_title": "Почта",
                "event_type": "focus",
            })

        patterns = _build_activity_patterns(events)

        assert patterns["repeated_window_titles"]
        assert patterns["repeated_window_titles"][0]["title"] == "Отчёт продаж.xlsx"
        assert patterns["repeated_window_titles"][0]["count"] == 6
        assert patterns["frequent_app_switches"]
        assert patterns["hourly_active_seconds"]["09"] == 270
