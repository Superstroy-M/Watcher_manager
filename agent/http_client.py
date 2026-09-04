"""
Единые HTTP-таймауты для всех запросов агента.

connect: 5 сек, read: 15 сек (probe read: 5 сек).
"""
from __future__ import annotations

import os
from typing import Any, Tuple, Union

import requests
from requests.exceptions import HTTPError, RequestException

Timeout = Union[float, Tuple[float, float]]

CONNECT_TIMEOUT = float(os.environ.get("HTTP_CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.environ.get("HTTP_READ_TIMEOUT", "15"))
PROBE_READ_TIMEOUT = float(os.environ.get("HTTP_PROBE_READ_TIMEOUT", "5"))

DEFAULT_TIMEOUT: Timeout = (CONNECT_TIMEOUT, READ_TIMEOUT)
PROBE_TIMEOUT: Timeout = (CONNECT_TIMEOUT, PROBE_READ_TIMEOUT)


def _resolve_timeout(timeout: Any, default: Timeout) -> Timeout:
    if timeout is None:
        return default
    return timeout


def get(url: str, **kwargs: Any) -> requests.Response:
    kwargs["timeout"] = _resolve_timeout(kwargs.get("timeout"), DEFAULT_TIMEOUT)
    return requests.get(url, **kwargs)


def post(url: str, **kwargs: Any) -> requests.Response:
    kwargs["timeout"] = _resolve_timeout(kwargs.get("timeout"), DEFAULT_TIMEOUT)
    return requests.post(url, **kwargs)


def is_transport_error(exc: BaseException) -> bool:
    """
    True только для сетевых/transport сбоев (нет ответа от сервера).
    HTTP 4xx/5xx означают, что сервер доступен — offline не выставляем.
    """
    if isinstance(exc, HTTPError):
        return False
    if isinstance(exc, RequestException):
        return True
    if isinstance(exc, OSError):
        return True
    return False
