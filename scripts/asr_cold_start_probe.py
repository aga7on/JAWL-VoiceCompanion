"""Measure the cold-process cost of the streaming ASR bridge (idle restart).

The bridge starts crispasr lazily inside the first feed() after a pause, so the
first phrase after silence pays for process startup. This measures that cost
directly against the real binary, without the HTTP layer.
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"G:\AI\JAWL-VoiceCompanion")
sys.path.insert(0, str(ROOT / "src"))

CRISPASR = r"G:\AI\crispasr\crispasr-windows-x86_64-cpu\crispasr.exe"
GIGAAM = r"G:\AI\JAWL-VoiceCompanion\runtime\models\asr\gigaam-v3-e2e-rnnt-q8_0.gguf"


def spawn_once() -> float:
    began = time.perf_counter()
    process = subprocess.Popen(
        [CRISPASR, "--backend", "gigaam", "-m", GIGAAM, "--stream", "--stream-json",
         "--stream-step", "200", "--stream-final-on-silence-ms", "600"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
    )
    elapsed = time.perf_counter() - began
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    return elapsed


def main() -> int:
    from jawl_voicecompanion.streaming_asr import StreamingASRBridge

    chunk = b"\x00\x01" * 3200  # 200 ms of quiet 16 kHz PCM16

    spawns = [spawn_once() for _ in range(3)]
    print(
        f"crispasr spawn: p50={statistics.median(spawns):.3f} s, max={max(spawns):.3f} s",
        flush=True,
    )

    bridge = StreamingASRBridge(CRISPASR, GIGAAM, step_ms=200)
    began = time.perf_counter()
    bridge.feed(chunk, sample_rate=16000, channels=1)
    cold_feed = time.perf_counter() - began
    warm_feeds = []
    for _ in range(10):
        began = time.perf_counter()
        bridge.feed(chunk, sample_rate=16000, channels=1)
        warm_feeds.append(time.perf_counter() - began)
    bridge.close()
    print(f"bridge cold feed: {cold_feed:.3f} s", flush=True)
    print(
        f"bridge warm feed: p50={statistics.median(warm_feeds):.4f} s, "
        f"max={max(warm_feeds):.4f} s",
        flush=True,
    )

    bridge2 = StreamingASRBridge(CRISPASR, GIGAAM, step_ms=200)
    began = time.perf_counter()
    bridge2.feed(chunk, sample_rate=16000, channels=1)
    resumed = time.perf_counter() - began
    bridge2.close()
    print(f"first feed after idle restart: {resumed:.3f} s", flush=True)

    budget = 6.0
    worst = max(cold_feed, resumed)
    print(
        f"\nverdict: cold-feed {cold_feed:.3f} s and resume {resumed:.3f} s are "
        f"{100 * worst / budget:.1f}% of the {budget:.0f} s turn budget",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())