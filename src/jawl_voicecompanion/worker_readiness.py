"""Bounded loopback readiness checks for owned model workers."""

from __future__ import annotations

import json
import socket
from urllib.request import urlopen


def require_free_ports(ports: list[int]) -> None:
    """Preflight only: never attach to, stop, or adopt another listener."""
    if len(set(ports)) != len(ports):
        raise ValueError("supervised worker ports collide")
    for port in ports:
        if type(port) is not int or not 1 <= port <= 65535 or port == 8765:
            raise ValueError("supervised worker port is invalid or reserved")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise ValueError(f"supervised worker port {port} is unavailable; listener left untouched") from exc


def model_ready(port: int, model: str | None = None) -> bool:
    """Health is necessary; LLM readiness also requires the expected alias."""
    base = f"http://127.0.0.1:{port}"
    with urlopen(base + "/health", timeout=2) as response:
        if response.status != 200:
            return False
    if model is None:
        return True
    with urlopen(base + "/v1/models", timeout=2) as response:
        if response.status != 200:
            return False
        payload = response.read(65537)
    if len(payload) > 65536:
        return False
    try:
        data = json.loads(payload)
    except (ValueError, RecursionError):
        return False
    return (
        isinstance(data, dict)
        and isinstance(data.get("data"), list)
        and any(isinstance(item, dict) and item.get("id") == model for item in data["data"])
    )
