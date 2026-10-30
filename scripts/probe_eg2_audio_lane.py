"""Audit the active EG2/YAMNet audio lane on the local licensed FMA probe set.

The probe stores only model labels/scores and timing. Decoded PCM is transient;
no audio samples or transcripts are written to the report.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.eg2_describer import (  # noqa: E402
    DetailedSensoryDescriber,
    Eg2AudioDescriptionProvider,
)
from jawl_voicecompanion.eg2_sensory import (  # noqa: E402
    DEFAULT_EG2_ONNX_ROOT,
    EmbeddingGemmaSensoryCortex,
)
from jawl_voicecompanion.yamnet_soundscape import (  # noqa: E402
    MUSIC_THRESHOLD,
    YamnetSoundscapeDetector,
)


DEFAULT_MANIFEST = ROOT / "runtime/audio-path-replay/data/fma-medium-selected/manifest.json"
DEFAULT_OUTPUT = ROOT / "runtime/audio-path-replay/out/eg2-audio-lane-audit-20261029.json"
DEFAULT_FFMPEG = Path(
    r"C:\Users\ARTEM\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
)
GENRE_TO_EG2 = {
    "Classical": {"classical_piano", "cinematic_orchestral"},
    "Electronic": {"electronic_ambient"},
    "Folk": {"folk_acoustic"},
    "Hip-Hop": {"hip_hop_beat"},
    "Jazz": {"jazz_smooth"},
    "Rock": {"rock_energetic"},
}


def _decode(ffmpeg: Path, media: Path, *, start: float, seconds: float) -> bytes:
    result = subprocess.run(
        [str(ffmpeg), "-v", "error", "-ss", str(start), "-i", str(media),
         "-t", str(seconds), "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1"],
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode or not result.stdout:
        raise RuntimeError(f"audio decode failed for track {media.name}")
    return result.stdout


def _top_items(values: Any, limit: int = 3) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [
        {
            "label": str(item.get("label") or "")[:80],
            "similarity": round(float(item.get("similarity", 0.0)), 4),
        }
        for item in values[:limit]
        if isinstance(item, dict)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ffmpeg", type=Path, default=DEFAULT_FFMPEG)
    parser.add_argument("--start-seconds", type=float, default=8.0)
    parser.add_argument("--clip-seconds", type=float, default=8.0)
    parser.add_argument("--limit", type=int, default=18)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()
    if not args.ffmpeg.is_file():
        parser.error(f"ffmpeg not found: {args.ffmpeg}")
    if args.start_seconds < 0 or not 2 <= args.clip_seconds <= 20:
        parser.error("start must be nonnegative and clip must be 2..20 seconds")
    if not 1 <= args.limit <= 18:
        parser.error("limit must be 1..18")
    if not 1 <= args.threads <= 16:
        parser.error("threads must be 1..16")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or len(tracks) < args.limit:
        raise RuntimeError("manifest has fewer tracks than requested")
    tracks = tracks[: args.limit]

    cortex = EmbeddingGemmaSensoryCortex(
        DEFAULT_EG2_ONNX_ROOT,
        load_vision=False,
        load_audio=True,
        intra_op_num_threads=args.threads,
    )
    describer = DetailedSensoryDescriber(cortex)
    provider = Eg2AudioDescriptionProvider(describer)
    yamnet = YamnetSoundscapeDetector()
    if cortex.audio_session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("EG2 did not use CPUExecutionProvider only")
    if yamnet.session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("YAMNet did not use CPUExecutionProvider only")

    rows: list[dict[str, Any]] = []
    for track in tracks:
        media = ROOT / str(track["local_file"])
        pcm = _decode(
            args.ffmpeg, media, start=args.start_seconds, seconds=args.clip_seconds
        )
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        observation = describer.describe_audio_pcm16(
            pcm, sample_rate=16000, channels=1
        )
        eg2_wall_ms = (time.perf_counter() - wall_start) * 1000.0
        eg2_cpu_ms = (time.process_time() - cpu_start) * 1000.0
        safe = provider.describe(
            pcm, sample_rate=16000, channels=1,
            clip_id=str(track["track_id"]),
        )
        soundscape = yamnet.describe(
            pcm, sample_rate=16000, channels=1,
            clip_id=str(track["track_id"]),
        )
        specialist = observation.level2.get("specialist_candidates", {})
        genre_rank = _top_items(specialist.get("music_genre"), limit=3)
        expected = GENRE_TO_EG2.get(str(track["genre"]), set())
        rows.append({
            "track_id": track["track_id"],
            "artist_id": track["artist_id"],
            "genre_proxy": track["genre"],
            "license": track["license"],
            "audio_scene_top": observation.level1.get("audio_scene"),
            "dsp": {
                key: observation.level2.get("dsp", {}).get(key)
                for key in ("rms_dbfs", "is_speech_likely", "is_music_likely", "speech_modulation")
            },
            "eg2_music_genre_candidates": genre_rank,
            "eg2_expected_genre_in_top3_proxy": any(
                row["label"] in expected for row in genre_rank
            ),
            "eg2_specialist_candidates": {
                key: _top_items(specialist.get(key), limit=2)
                for key in ("music_mood", "music_vocals", "music_drums", "music_bass", "music_electronic")
            },
            "eg2_safe_adapter_output": safe,
            "yamnet": {
                "kind": soundscape.get("kind"),
                "tags": list(soundscape.get("tags") or [])[:4],
                "confidence": soundscape.get("confidence"),
                "windows": soundscape.get("windows"),
                "music_windows": soundscape.get("music_windows"),
            },
            "latency_ms": {
                "eg2_wall": round(eg2_wall_ms, 2),
                "eg2_process_cpu": round(eg2_cpu_ms, 2),
            },
        })

    try:
        import psutil
        rss = int(psutil.Process().memory_info().rss)
    except Exception:  # noqa: BLE001 - optional research telemetry
        rss = None
    summary = {
        "track_count": len(rows),
        "unique_artists": len({str(row["artist_id"]) for row in rows}),
        "yamnet_music_detected": sum(row["yamnet"]["kind"] == "music" for row in rows),
        "eg2_safe_adapter_music_claims": sum(row["eg2_safe_adapter_output"]["kind"] == "music" for row in rows),
        "eg2_useful_music_claims": sum(
            row["eg2_safe_adapter_output"]["kind"] == "music"
            and (row["eg2_safe_adapter_output"]["tags"] or row["eg2_safe_adapter_output"]["mood"])
            for row in rows
        ),
        "eg2_expected_genre_top3_proxy": sum(row["eg2_expected_genre_in_top3_proxy"] for row in rows),
        "eg2_safe_adapter_outputs": sorted({row["eg2_safe_adapter_output"]["description"] for row in rows}),
    }
    report = {
        "schema_version": 1,
        "model": "EmbeddingGemma 2 audio ONNX q4 + YAMNet ONNX",
        "providers": {
            "eg2": cortex.audio_session.get_providers(),
            "yamnet": yamnet.session.get_providers(),
        },
        "threads": {
            "eg2_intra_op": cortex.intra_op_num_threads,
            "eg2_inter_op": 1,
            "yamnet_intra_op": 1,
            "yamnet_music_score_threshold": MUSIC_THRESHOLD,
            "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
        },
        "dataset": {
            "name": "local FMA Medium selected artist-disjoint positive music clips",
            "license_scope": "per-track attribution/CC0 only; see manifest",
            "start_seconds": args.start_seconds,
            "clip_seconds": args.clip_seconds,
            "raw_audio_persisted": False,
            "transcript_persisted": False,
        },
        "summary": summary,
        "rss_bytes_after_inference": rss,
        "rows": rows,
        "limitations": [
            "FMA catalog genre is a weak proxy, not human-verified interval annotation.",
            "EmbeddingGemma similarities are rankings, not calibrated probabilities.",
            "Positive music clips do not measure false-positive rates on speech/noise/silence.",
            "This direct CPU replay does not prove capture, queue, brain delivery, or live freshness.",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "rss_bytes_after_inference": rss}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
