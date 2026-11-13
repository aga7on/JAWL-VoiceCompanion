"""Verify that a turn_id survives the Companion -> JAWL terminal transport.

The kernel takes its fast conversation lane only when the event payload carries
_companion_turn_id. That id originates in this transport, so this probe sends one
message with a known id and reports whether JAWL recognised it.

It sends through the same TCP terminal protocol the live profile uses, so a
success here proves the id is not being dropped on the wire.
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT_FILE = (
    ROOT / "runtime" / "instances" / "daily" / "data" / "interfaces"
    / "host" / "terminal" / "terminal.port"
)
HANDSHAKE = b"JAWL_HANDSHAKE\n"


def main() -> int:
    if not PORT_FILE.exists():
        print(f"terminal port file missing: {PORT_FILE}")
        return 2
    port = int(PORT_FILE.read_text(encoding="utf-8").strip())
    print(f"terminal port: {port}")

    turn_id = f"probe-turnid-{int(time.time())}"
    message = {"text": "Скажи одно слово: работаю", "turn_id": turn_id}
    payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
    print(f"sending turn_id={turn_id}")

    began = time.perf_counter()
    reply = b""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=180) as connection:
            connection.settimeout(180)
            connection.sendall(HANDSHAKE + payload)
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                reply += chunk
                if b"\n" in reply:
                    break
    except Exception as exc:  # noqa: BLE001 - diagnostic probe
        print("transport error:", type(exc).__name__, exc)
        return 1

    elapsed = time.perf_counter() - began
    print(f"reply in {elapsed:.2f}s, {len(reply)} bytes")
    print("reply:", reply.decode("utf-8", errors="replace")[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())