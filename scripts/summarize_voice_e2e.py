"""Summarize a run_browser_voice_e2e report without dumping raw evidence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))

print("report:", path)
for key in ("ok", "passed", "failure", "ui", "url", "hardware_audibility_verified"):
    if key in data:
        print(f"  {key} = {data[key]!r}")

turns = data.get("turns") or []
print("turns:", len(turns))
for index, turn in enumerate(turns, start=1):
    timings = turn.get("timings") or {}
    print(
        f"  #{index} {turn.get('wav')}: ok={turn.get('ok')} passed={turn.get('passed')} "
        f"asr_match={turn.get('expected_transcript_matched')}"
    )
    print(f"      asr = {turn.get('transcript_text')!r}")
    print(
        "      playback_nonsilent="
        f"{turn.get('playback_completed_nonsilent_seconds')}s "
        f"turn_to_first_audio={timings.get('turn_to_first_audio_ms')}ms "
        f"failure={turn.get('failure')!r}"
    )