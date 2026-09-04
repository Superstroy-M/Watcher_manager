from unittest.mock import patch

import http_client


def test_default_timeouts_applied_on_post():
    with patch("http_client.requests.post") as post_mock:
        post_mock.return_value.status_code = 200
        http_client.post("http://example/api", json={"ok": True})

    _, kwargs = post_mock.call_args
    assert kwargs["timeout"] == http_client.DEFAULT_TIMEOUT


def test_probe_timeout_applied_on_get():
    with patch("http_client.requests.get") as get_mock:
        get_mock.return_value.status_code = 200
        http_client.get("http://example/health", timeout=http_client.PROBE_TIMEOUT)

    _, kwargs = get_mock.call_args
    assert kwargs["timeout"] == http_client.PROBE_TIMEOUT


def test_explicit_timeout_is_respected():
    with patch("http_client.requests.post") as post_mock:
        post_mock.return_value.status_code = 200
        http_client.post("http://example/api", timeout=(1, 2))

    _, kwargs = post_mock.call_args
    assert kwargs["timeout"] == (1, 2)
