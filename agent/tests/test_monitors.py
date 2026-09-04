from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import monitoring_control
import network_monitor
import print_monitor
import process_monitor
from network_monitor import NetworkMonitor, _is_external


def setup_function():
    monitoring_control.reset_for_tests("active")


def test_is_external_filters_private_ips():
    assert _is_external("8.8.8.8") is True
    assert _is_external("192.168.1.1") is False
    assert _is_external("10.0.0.1") is False
    assert _is_external("") is False


def test_process_monitor_skips_when_offline():
    monitor = process_monitor.ProcessMonitor()
    with patch("process_monitor.is_online", return_value=False), patch(
        "process_monitor.post"
    ) as post_mock:
        monitor._snapshot()
    post_mock.assert_not_called()


def test_process_monitor_skips_when_paused():
    monitoring_control.reset_for_tests("paused")
    monitor = process_monitor.ProcessMonitor()
    with patch("process_monitor.is_online", return_value=True), patch(
        "process_monitor.post"
    ) as post_mock:
        monitor._snapshot()
    post_mock.assert_not_called()


def test_process_monitor_sends_when_active(monkeypatch):
    monitor = process_monitor.ProcessMonitor()

    class FakeProc:
        def __init__(self):
            self.info = {
                "name": "chrome.exe",
                "pid": 1,
                "cpu_percent": 1.0,
                "memory_info": MagicMock(rss=1024 * 1024),
                "username": "user",
            }

    monkeypatch.setattr(
        process_monitor.psutil,
        "process_iter",
        lambda attrs: [FakeProc()],
    )
    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch("process_monitor.is_online", return_value=True), patch(
        "process_monitor.post", return_value=response
    ) as post_mock:
        monitor._snapshot()

    post_mock.assert_called_once()
    assert post_mock.call_args.kwargs["json"]["processes"][0]["name"] == "chrome.exe"


def test_network_monitor_skips_when_offline():
    monitor = NetworkMonitor()
    with patch("network_monitor.is_online", return_value=False), patch(
        "network_monitor.post"
    ) as post_mock:
        monitor._snapshot()
    post_mock.assert_not_called()


def test_network_monitor_skips_when_paused():
    monitoring_control.reset_for_tests("paused")
    monitor = NetworkMonitor()
    with patch("network_monitor.is_online", return_value=True), patch(
        "network_monitor.post"
    ) as post_mock:
        monitor._snapshot()
    post_mock.assert_not_called()


def test_network_monitor_sends_external_connections(monkeypatch):
    monitor = NetworkMonitor()

    class FakeConn:
        status = "ESTABLISHED"
        pid = 42
        raddr = MagicMock(ip="8.8.8.8", port=443)
        laddr = MagicMock(port=50000)

    fake_proc = MagicMock()
    fake_proc.pid = 42
    fake_proc.name = MagicMock(return_value="chrome.exe")

    monkeypatch.setattr(
        network_monitor.psutil,
        "process_iter",
        lambda attrs: [fake_proc],
    )
    monkeypatch.setattr(
        network_monitor.psutil,
        "net_connections",
        lambda kind: [FakeConn()],
    )
    response = MagicMock()
    response.raise_for_status = MagicMock()

    with patch("network_monitor.is_online", return_value=True), patch(
        "network_monitor.post", return_value=response
    ) as post_mock:
        monitor._snapshot()

    post_mock.assert_called_once()
    payload = post_mock.call_args.kwargs["json"]
    assert payload["connections"][0]["remote_ip"] == "8.8.8.8"


def test_network_monitor_marks_offline_on_failure(monkeypatch):
    monitor = NetworkMonitor()

    class FakeConn:
        status = "ESTABLISHED"
        pid = 1
        raddr = MagicMock(ip="1.2.3.4", port=80)
        laddr = MagicMock(port=1234)

    monkeypatch.setattr(network_monitor.psutil, "process_iter", lambda attrs: [])
    monkeypatch.setattr(network_monitor.psutil, "net_connections", lambda kind: [FakeConn()])

    with patch("network_monitor.is_online", return_value=True), patch(
        "network_monitor.post", side_effect=ConnectionError("down")
    ), patch("network_monitor.mark_offline_on_transport_error") as mark_offline_mock:
        monitor._snapshot()

    mark_offline_mock.assert_called_once()


def test_print_monitor_skips_when_offline():
    with patch("print_monitor.is_online", return_value=False), patch(
        "print_monitor.post"
    ) as post_mock:
        print_monitor.PrintMonitor()._send_job("doc", "HP", 1, "user")
    post_mock.assert_not_called()


def test_print_monitor_skips_when_paused():
    monitoring_control.reset_for_tests("paused")
    with patch("print_monitor.is_online", return_value=True), patch(
        "print_monitor.post"
    ) as post_mock:
        print_monitor.PrintMonitor()._send_job("doc", "HP", 1, "user")
    post_mock.assert_not_called()


def test_print_monitor_sends_when_active():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    with patch("print_monitor.is_online", return_value=True), patch(
        "print_monitor.post", return_value=response
    ) as post_mock:
        print_monitor.PrintMonitor()._send_job("doc.pdf", "HP", 3, "user")
    post_mock.assert_called_once()
    assert post_mock.call_args.kwargs["json"]["document_name"] == "doc.pdf"
