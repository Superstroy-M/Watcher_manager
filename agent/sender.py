"""
Отправка событий на сервер.
При недоступности сервера данные не буферизуются — просто отбрасываются.
"""
import logging
import threading
import time
from datetime import datetime, timedelta

from config import SERVER_URL, API_KEY, AGENT_VERSION, IDLE_THRESHOLD
from diag_log import log_event
from http_client import post
from memory_guard import check_memory, last_ram_mb, process_ram_mb, screenshots_allowed
from monitoring_control import apply_server_state, get_state, is_monitoring_active
from server_link import is_online, mark_offline, mark_online, sleep_interval, try_probe
from window_tracker import get_active_window_info, get_idle_seconds

logger = logging.getLogger("sender")

HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


class EventSender:
    def __init__(self, tracker):
        self.tracker = tracker
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            check_memory()
            try:
                if is_online():
                    self._send_cycle()
                elif try_probe():
                    self._send_cycle()
                else:
                    self._discard_pending()
            except Exception as e:
                mark_offline(str(e))
                self._discard_pending()
                logger.warning("Send error: %s", e)
            time.sleep(sleep_interval())

    def _send_cycle(self):
        try:
            self._send_heartbeat()
            if is_monitoring_active():
                self._send_events()
            else:
                self._discard_pending()
            mark_online()
        except Exception as e:
            mark_offline(str(e))
            raise

    def _discard_pending(self):
        dropped = self.tracker.pop_events()
        if dropped:
            logger.info("Dropped %d event(s) while server offline", len(dropped))
            log_event("events_dropped_offline", "sender", events_count=len(dropped))

    def _send_heartbeat(self):
        import socket
        import os
        import platform

        payload = {
            "hostname": socket.gethostname(),
            "ip_address": _get_local_ip(),
            "username": os.environ.get("USERNAME") or os.environ.get("USER"),
            "os_version": platform.platform(),
            "agent_version": AGENT_VERSION,
            "ram_mb": last_ram_mb() or process_ram_mb(),
            "screenshots_enabled": screenshots_allowed(),
            "monitoring_state": get_state(),
        }
        try:
            resp = post(
                f"{SERVER_URL}/api/heartbeat",
                json=payload,
                headers=HEADERS,
            )
            resp.raise_for_status()
            apply_server_state(resp.json().get("monitoring_state", "active"))
            log_event(
                "heartbeat_ok",
                "sender",
                ip_address=payload.get("ip_address"),
                monitoring_state=get_state(),
                ram_mb=payload.get("ram_mb"),
            )
        except Exception as e:
            log_event("heartbeat_fail", "sender", error=str(e))
            raise

    def _send_events(self):
        import socket

        try:
            self.tracker.force_checkpoint()
        except Exception:
            pass

        live_events = self.tracker.pop_events()
        if not live_events:
            fallback = self._build_fallback_event()
            if fallback:
                live_events = [fallback]
            else:
                return

        hostname = socket.gethostname()
        payload = {"hostname": hostname, "events": live_events}

        try:
            resp = post(
                f"{SERVER_URL}/api/events",
                json=payload,
                headers=HEADERS,
            )
            resp.raise_for_status()
            log_event(
                "events_sent",
                "sender",
                events_count=len(live_events),
                live_count=len(live_events),
            )
        except Exception as e:
            mark_offline(str(e))
            log_event(
                "events_dropped",
                "sender",
                events_count=len(live_events),
                error=str(e),
            )
            raise

    def _build_fallback_event(self):
        try:
            now = datetime.utcnow()
            started = now - timedelta(seconds=30)
            idle_secs = get_idle_seconds()
            if idle_secs >= IDLE_THRESHOLD:
                return {
                    "hostname": "",
                    "started_at": started.isoformat(),
                    "ended_at": now.isoformat(),
                    "duration_seconds": 30,
                    "process_name": "idle",
                    "window_title": "",
                    "event_type": "idle",
                }

            info = get_active_window_info()
            return {
                "hostname": "",
                "started_at": started.isoformat(),
                "ended_at": now.isoformat(),
                "duration_seconds": 30,
                "process_name": info.get("process_name") or "unknown",
                "window_title": info.get("window_title") or "",
                "event_type": "focus",
            }
        except Exception:
            return None


def _get_local_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
