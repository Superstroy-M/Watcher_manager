from unittest.mock import MagicMock, patch

import sender


def test_discard_pending_drops_tracker_events():
    tracker = MagicMock()
    tracker.pop_events.return_value = [{"id": 1}, {"id": 2}]
    event_sender = sender.EventSender(tracker)

    event_sender._discard_pending()

    tracker.pop_events.assert_called_once()


def test_send_events_does_not_buffer_on_failure():
    tracker = MagicMock()
    tracker.pop_events.return_value = [{"id": 1}]
    event_sender = sender.EventSender(tracker)

    with patch("sender.post", side_effect=ConnectionError("down")), patch(
        "sender.mark_offline"
    ) as mark_offline_mock, patch("sender.log_event"):
        try:
            event_sender._send_events()
        except ConnectionError:
            pass

    mark_offline_mock.assert_called_once()
    assert not hasattr(sender, "_save_to_buffer")
