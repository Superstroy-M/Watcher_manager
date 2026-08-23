"""
Мониторинг сетевых подключений — какие программы выходят в интернет.
Отправляет снимок каждые 2 минуты.
"""
import time
import socket
import logging
import threading
from datetime import datetime
from typing import Optional

import psutil
import requests

from config import SERVER_URL, API_KEY

logger = logging.getLogger("network")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
INTERVAL = 120  # 2 минуты

# Внутренние диапазоны — не интересны
PRIVATE_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
                    "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.",
                    "172.27.", "172.28.", "172.29.", "172.30.", "172.31.", "192.168.",
                    "127.", "0.", "::1", "fe80")


def _is_external(ip: str) -> bool:
    return ip and not any(ip.startswith(p) for p in PRIVATE_PREFIXES)


class NetworkMonitor:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._snapshot()
            except Exception as e:
                logger.warning(f"Network snapshot error: {e}")
            time.sleep(INTERVAL)

    def _snapshot(self):
        pid_to_name = {p.pid: p.name() for p in psutil.process_iter(["name", "pid"])}
        connections = []

        for conn in psutil.net_connections(kind="inet"):
            if conn.status != "ESTABLISHED":
                continue
            if not conn.raddr:
                continue
            remote_ip = conn.raddr.ip
            if not _is_external(remote_ip):
                continue

            proc_name = pid_to_name.get(conn.pid, "unknown") if conn.pid else "unknown"
            connections.append({
                "process_name": proc_name,
                "pid": conn.pid or 0,
                "remote_ip": remote_ip,
                "remote_port": conn.raddr.port,
                "local_port": conn.laddr.port if conn.laddr else 0,
                "status": conn.status,
            })

        if not connections:
            return

        payload = {
            "hostname": socket.gethostname(),
            "captured_at": datetime.utcnow().isoformat(),
            "connections": connections,
        }
        resp = requests.post(
            f"{SERVER_URL}/api/network",
            json=payload,
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        logger.debug(f"Sent {len(connections)} network connections")
