"""
Мониторинг сетевых подключений — какие программы выходят в интернет.
Отправляет снимок каждые 2 минуты.
"""
import os
import time
import socket
import logging
import threading
from datetime import datetime
from typing import Optional

import psutil

from config import SERVER_URL, API_KEY
from diag_log import log_event
from http_client import post
from monitoring_control import is_monitoring_active
from server_link import is_online, mark_offline

logger = logging.getLogger("network")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
INTERVAL = 120  # 2 минуты
MAX_CONNECTIONS = int(os.environ.get("NETWORK_CONNECTIONS_MAX", "5000"))

# Внутренние диапазоны — не интересны
PRIVATE_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
                    "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.",
                    "172.27.", "172.28.", "172.29.", "172.30.", "172.31.", "192.168.",
                    "127.", "0.", "::1", "fe80")


def _is_external(ip: str) -> bool:
    return bool(ip) and not any(ip.startswith(p) for p in PRIVATE_PREFIXES)


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
        if not is_online() or not is_monitoring_active():
            return
        log_event("network_cycle_start", "network")
        pid_to_name = {p.pid: p.name() for p in psutil.process_iter(["name", "pid"])}
        connections = []

        try:
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
                log_event("network_cycle_end", "network", count=0)
                return

            total_found = len(connections)
            if total_found > MAX_CONNECTIONS:
                connections = connections[:MAX_CONNECTIONS]
                logger.warning(
                    "Network snapshot truncated: %d connections found, sending %d",
                    total_found,
                    MAX_CONNECTIONS,
                )
                log_event(
                    "network_truncated",
                    "network",
                    total_found=total_found,
                    sent_count=MAX_CONNECTIONS,
                    max_connections=MAX_CONNECTIONS,
                )

            payload = {
                "hostname": socket.gethostname(),
                "captured_at": datetime.utcnow().isoformat(),
                "connections": connections,
            }
            resp = post(
                f"{SERVER_URL}/api/network",
                json=payload,
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            logger.debug(f"Sent {len(connections)} network connections")
            log_event("network_cycle_end", "network", count=len(connections))
        except Exception as e:
            mark_offline(str(e))
            logger.warning(f"Network snapshot send failed: {e}")
            log_event("network_cycle_error", "network", error=str(e))
