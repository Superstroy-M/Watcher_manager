from unittest.mock import MagicMock, patch

import monitoring_control
import sender


def setup_function():
    monitoring_control.reset_for_tests("active")


def test_apply_paused_from_server():
    monitoring_control.apply_server_state("paused")
    assert monitoring_control.is_monitoring_active() is False
    assert monitoring_control.get_state() == "paused"


def test_apply_active_from_server():
    monitoring_control.apply_server_state("paused")
    monitoring_control.apply_server_state("active")
    assert monitoring_control.is_monitoring_active() is True


def test_sender_heartbeat_only_when_paused():
    monitoring_control.reset_for_tests("paused")
    tracker = MagicMock()
    event_sender = sender.EventSender(tracker)

    with patch.object(event_sender, "_send_heartbeat"), patch.object(
        event_sender, "_send_events"
    ) as events_mock, patch("sender.mark_online"):
        event_sender._send_cycle()

    events_mock.assert_not_called()
    tracker.pop_events.assert_called_once()


def test_sender_sends_events_when_active():
    monitoring_control.reset_for_tests("active")
    tracker = MagicMock()
    event_sender = sender.EventSender(tracker)

    with patch.object(event_sender, "_send_heartbeat"), patch.object(
        event_sender, "_send_events"
    ) as events_mock, patch("sender.mark_online"):
        event_sender._send_cycle()

    events_mock.assert_called_once()
