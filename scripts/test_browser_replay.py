"""Test seeking and replay capability in browser for Video 1."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_youtube_multimodal_watcher import BrowserVideoSession


def test_replay():
    url = "https://www.youtube.com/watch?v=GXe8XEFA9Pc"
    session = BrowserVideoSession(url)
    try:
        session.start()
        time.sleep(2)
        print("Initial time:", session.get_current_time())

        # Seek to dialogue start (8s)
        session.seek_to(8.0)
        time.sleep(2)
        t_after = session.get_current_time()
        print(f"Seeked to 8.0s -> Current time: {t_after:.2f}s")
        assert 7.0 <= t_after <= 12.0, f"Expected ~8s, got {t_after}"

        # Seek to punchline (36s)
        session.seek_to(36.0)
        time.sleep(2)
        t_punch = session.get_current_time()
        print(f"Seeked to 36.0s -> Current time: {t_punch:.2f}s")
        assert 35.0 <= t_punch <= 40.0, f"Expected ~36s, got {t_punch}"

        print("Replay and seek capability VERIFIED!")
    finally:
        session.close()


if __name__ == "__main__":
    test_replay()
