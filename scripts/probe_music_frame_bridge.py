"""Replay local five-case audio fixtures through the production soundscape lane.

CPU-only YAMNet is run through AmbientAudioASRBridge's independent 3-second
segmenter, MusicFrame, and PerceptionFusion. No capture devices, live services,
raw PCM, or transcript text are persisted; the final artifact is scalar telemetry.
"""
from __future__ import annotations

import json
import sys
import time
import wave
from pathlib import Path
from typing import Any

import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.ambient_audio import AmbientAudioASRBridge  # noqa: E402
from jawl_voicecompanion.ambient_memory import AmbientMemoryBuffer  # noqa: E402
from jawl_voicecompanion.perception_fusion import PerceptionFusion  # noqa: E402
from jawl_voicecompanion.yamnet_soundscape import YamnetSoundscapeDetector  # noqa: E402


CLIP_DIR = ROOT / "runtime/multimodal-realclips-20261024/probes/lowrate"
CASE_IDS = (
    "01_ru_trailer", "02_anime", "03_gameplay", "04_coding_ui", "05_aqua_song",
)


class NoopASR:
    def feed_audio(self, pcm16: bytes, **kwargs: Any) -> dict[str, Any]:
        return {"status": "buffered"}

    def end_audio(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def finish(self, session_id: str) -> dict[str, Any]:
        return {"status": "transcribed", "text": ""}


class RecordingDetector:
    name = "yamnet-onnx-cpu"

    def __init__(self, detector: YamnetSoundscapeDetector) -> None:
        self.detector = detector
        self.results: list[dict[str, Any]] = []

    def describe(self, pcm16: bytes, **kwargs: Any) -> dict[str, Any]:
        started = time.perf_counter()
        result = self.detector.describe(pcm16, **kwargs)
        record = {
            key: result.get(key)
            for key in (
                "kind", "duration_seconds", "windows", "music_windows",
                "music_score_max", "music_score_median", "calibrated", "tags",
            )
        }
        record["inference_ms"] = round((time.perf_counter() - started) * 1000, 2)
        record["segment_id"] = kwargs.get("clip_id")
        self.results.append(record)
        return result


def _read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise ValueError(f"expected mono 16 kHz PCM16: {path.name}")
        return wav.readframes(wav.getnframes())


def main() -> int:
    missing = [str(CLIP_DIR / f"{case}.wav") for case in CASE_IDS if not (CLIP_DIR / f"{case}.wav").is_file()]
    if missing:
        raise FileNotFoundError("missing local audio fixtures: " + ", ".join(missing))
    detector = RecordingDetector(YamnetSoundscapeDetector())
    bridge = AmbientAudioASRBridge(
        NoopASR(), AmbientMemoryBuffer(enabled=True), final_asr=NoopASR(),
        soundscape_detector=detector, perception_fusion=PerceptionFusion(),
        soundscape_source="local_fixture_replay",
        segment_max_seconds=15.0, soundscape_segment_max_seconds=4.0,
    )
    cases = []
    started = time.perf_counter()
    for case_id in CASE_IDS:
        session = f"music-frame-replay:{case_id}"
        detector_start = len(detector.results)
        pcm = _read_pcm(CLIP_DIR / f"{case_id}.wav")
        bridge.start(session)
        # Pace half-second chunks at source duration to exercise segment capture
        # timestamps and worker freshness without accessing a capture device.
        chunk_bytes = 16000
        for offset in range(0, len(pcm), chunk_bytes):
            chunk = pcm[offset:offset + chunk_bytes]
            bridge.consume(chunk, 16000, 1, session)
            time.sleep(len(chunk) / 32000.0)
        bridge.flush(session)
        state = bridge.state()
        results = detector.results[detector_start:]
        frame = state.get("soundscape_last_music_frame") or {}
        cases.append({
            "case_id": case_id,
            "source_duration_seconds": round(len(pcm) / 32000, 2),
            "frames": results,
            "last_music_frame": frame,
            "queue_dropped": state["soundscape_dropped"],
            "queue_stale": state["soundscape_stale"],
            "worker_errors": state["soundscape_errors"],
            "asr_lane_segment_seconds": state["segmenter"]["max_segment_seconds"],
            "music_lane_segment_seconds": state["soundscape_segmenter"]["max_segment_seconds"],
        })
    report = {
        "schema_version": 1,
        "cpu_only": True,
        "yamnet_threads": {"intra": 1, "inter": 1},
        "onnxruntime_version": ort.__version__,
        "onnx_providers": detector.detector.session.get_providers(),
        "model": str(detector.detector.model_dir.relative_to(ROOT)),
        "production_bridge": True,
        "capture_semantics": "local_wav_paced_at_source_duration_through_consume",
        "asr_text_persisted": False,
        "pcm_persisted": False,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "cases": cases,
    }
    out = ROOT / "runtime/audio-path-replay/out/music-frame-bridge-five-case-20261024.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(out.relative_to(ROOT)),
        "elapsed_seconds": report["elapsed_seconds"],
        "cases": [{
            "case_id": case["case_id"],
            "frames": len(case["frames"]),
            "music_segments": sum(frame["kind"] == "music" for frame in case["frames"]),
            "states": [case["last_music_frame"].get("state")],
            "drops": case["queue_dropped"],
            "errors": case["worker_errors"],
        } for case in cases],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
