"""
Вычисление статуса связи и сериализация карточек ПК.

Online/Unstable/Offline — только из возраста last_seen (heartbeat).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

ONLINE_THRESHOLD_SEC = int(os.getenv("ONLINE_THRESHOLD_SEC", "90"))
UNSTABLE_THRESHOLD_SEC = int(os.getenv("UNSTABLE_THRESHOLD_SEC", "180"))


def connection_status(last_seen: Optional[datetime], now: Optional[datetime] = None) -> str:
    if not last_seen:
        return "offline"
    now = now or datetime.utcnow()
    age_sec = (now - last_seen).total_seconds()
    if age_sec < ONLINE_THRESHOLD_SEC:
        return "online"
    if age_sec < UNSTABLE_THRESHOLD_SEC:
        return "unstable"
    return "offline"


def last_seen_age_seconds(last_seen: Optional[datetime], now: Optional[datetime] = None) -> Optional[int]:
    if not last_seen:
        return None
    now = now or datetime.utcnow()
    return max(0, int((now - last_seen).total_seconds()))


def is_connection_online(last_seen: Optional[datetime], now: Optional[datetime] = None) -> bool:
    return connection_status(last_seen, now) == "online"


def serialize_computer(computer, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.utcnow()
    status = connection_status(computer.last_seen, now)
    age = last_seen_age_seconds(computer.last_seen, now)
    monitoring_state = getattr(computer, "monitoring_state", None) or "active"
    return {
        "id": computer.id,
        "hostname": computer.hostname,
        "ip_address": computer.ip_address,
        "username": computer.username,
        "agent_version": computer.agent_version,
        "agent_ram_mb": getattr(computer, "agent_ram_mb", None),
        "screenshots_enabled": getattr(computer, "screenshots_enabled", None),
        "last_seen": computer.last_seen.isoformat() if computer.last_seen else None,
        "last_seen_seconds": age,
        "connection_status": status,
        "is_online": status == "online",
        "monitoring_state": monitoring_state,
    }
