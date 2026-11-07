"""Test seeking and replay capability in browser for Video 2 (Infographics)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_youtube_multimodal_watcher import BrowserVideoSession


def test_replay_v2():
    url = "https://www.youtube.com/watch?v=YsupgLm_Pt4"
    session = BrowserVideoSession(url)
    try:
        session.start()
        time.sleep(2)
        print("Initial time:", session.get_current_time())

        # Seek to 11s (infographics transition)
        session.seek_to(11.0)
        time.sleep(2)
        t_after = session.get_current_time()
        print(f"Seeked to 11.0s -> Current time: {t_after:.2f}s")
        assert 10.0 <= t_after <= 15.0, f"Expected ~11s, got {t_after}"

        # Seek to 24s (100s to 5s speedup chart)
        session.seek_to(24.0)
        time.sleep(2)
        t_chart = session.get_current_time()
        print(f"Seeked to 24.0s -> Current time: {t_chart:.2f}s")
        assert 23.0 <= t_chart <= 28.0, f"Expected ~24s, got {t_chart}"

        print("Video 2 Replay and seek capability VERIFIED!")
    finally:
        session.close()


if __name__ == "__main__":
    test_replay_v2()
