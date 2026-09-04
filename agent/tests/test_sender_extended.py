from unittest.mock import MagicMock, patch

import monitoring_control
import sender
import server_link


def setup_function():
    monitoring_control.reset_for_tests("active")
    server_link.reset_state(start_online=False)


def test_heartbeat_applies_monitoring_state_from_response():
    tracker = MagicMock()
    event_sender = sender.EventSender(tracker)
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"status": "ok", "monitoring_state": "paused"}

    with patch("sender.post", return_value=response), patch("sender.log_event"):
        event_sender._send_heartbeat()

    assert monitoring_control.get_state() == "paused"


def test_sender_loop_offline_discards_without_post():
    tracker = MagicMock()
    tracker.pop_events.return_value = [{"id": 1}]
    event_sender = sender.EventSender(tracker)
    event_sender._running = True

    with patch("sender.try_probe", return_value=False), patch(
        "sender.post"
    ) as post_mock, patch("sender.sleep_interval", return_value=0), patch(
        "sender.time.sleep", side_effect=StopIteration
    ):
        import pytest

        with pytest.raises(StopIteration):
            event_sender._loop()

    post_mock.assert_not_called()
    tracker.pop_events.assert_called()
