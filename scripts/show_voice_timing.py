"""Print the per-turn latency breakdown from a voice E2E report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else
            "runtime/instances/daily/data/voice_e2e_report.json")
data = json.loads(path.read_text(encoding="utf-8"))
keys = (
    "first_tts_request_ms",
    "voice_end_request_ms",
    "voice_end_to_tts_headers_ms",
    "turn_to_voice_end_ms",
    "turn_to_first_audio_ms",
    "total_observed_ms",
)
for index, turn in enumerate(data.get("turns") or [], start=1):
    text = str(turn.get("transcript_text", ""))[:50]
    print(f"turn {index}: {text}")
    timings = turn.get("timings") or {}
    for key in keys:
        print(f"   {key:30} {timings.get(key)}")
    drafts = (turn.get("draft_lane") or {}).get("fetches") or []
    if drafts:
        print(f"   draft_first_nonempty_ms         {next((d.get('ended_ms') for d in drafts if d.get('draft')), None)}")
    print()