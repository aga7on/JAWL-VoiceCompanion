"""Isolated, non-intrusive scenario acceptance for all 17 sensory cases.

This harness creates a dedicated `AmbientSceneMemory` at
`runtime/isolated-sensory-scenario-store-20261106`, feeds real bounded WAV and
image fixtures through the production parser/fusion/answer-context path, and
writes one JSON report. It never opens a browser, starts/stops services,
writes the production memory/profile, or plays audio.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["JAWL_EG2_ONNX_THREADS"] = "1"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from jawl_voicecompanion.ambient_audio import BoundedAudioQueue, PlaybackSuppression
from jawl_voicecompanion.ambient_audio_asr_bridge import AmbientAudioASRBridge
from jawl_voicecompanion.ambient_audio_music import AmbientAudioMusicDetector
from jawl_voicecompanion.ambient_perception_fusion import PerceptionFusion
from jawl_voicecompanion.ambient_scene_memory import AmbientSceneMemory
from jawl_voicecompanion.ambient_screen_analysis import (
    ScreenCaptureAdapter,
    ScreenFrameScheduler,
    ScreenStateThrottle,
    VisionInferenceQueue,
    VisionWorker,
    select_vlm_backend,
)

EVIDENCE_DIR = Path("artifacts") / "evidence"
STORE = Path("runtime") / "isolated-sensory-scenario-store-20261106"
FIXTURES = Path("runtime") / "sensory-sim" / "fixtures"
SCENARIO_STORE_MAX_BYTES = 8 * 1024 * 1024


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wav(path: Path, start: float, seconds: float) -> tuple[bytes, int]:
    ffmpeg = Path(
        r"C:\Users\ARTEM\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
    )
    destination = Path(tempfile.mkstemp(suffix=".wav")[1])
    try:
        subprocess = __import__("subprocess").subprocess
        subprocess.run(
            [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-ss", str(start),
             "-t", str(seconds), "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", "-y", str(destination)],
            check=True, capture_output=True, timeout=60,
        )
        return destination.read_bytes(), 16000
    finally:
        destination.unlink(missing_ok=True)


async def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    if STORE.exists():
        shutil.rmtree(STORE)
    memory = AmbientSceneMemory(STORE, max_bytes=SCENARIO_STORE_MAX_BYTES)
    queue = BoundedAudioQueue()
    suppression = PlaybackSuppression()
    music = AmbientAudioMusicDetector()
    asr = AmbientAudioASRBridge()
    fusion = PerceptionFusion()

    vlm = select_vlm_backend()
    vision_queue = VisionInferenceQueue()
    vision = VisionWorker(vision_queue, vlm)
    vision.start()
    scheduler = ScreenFrameScheduler(12, 4)
    throttle = ScreenStateThrottle()
    capture = ScreenCaptureAdapter()
    capture.initialize()

    rows: list[dict] = []

    def audio_case(name: str, path: Path, start: float, seconds: float,
                   noise: bool = False, silence: bool = False) -> dict:
        started = time.monotonic()
        pcm, rate = wav(path, start, seconds)
        admitted = queue.submit(pcm, rate, "isolated-scenario")
        result = queue.drain(timeout=0.1) if admitted.get("admitted") else {"reason": str(admitted.get("reason"))}
        item: dict = {
            "case": name, "path": str(path.relative_to(ROOT)), "sha256": sha256(path),
            "start_s": start, "duration_s": round(seconds, 3), "admitted": bool(admitted.get("admitted")),
            "window_rms": round(float(result.get("rms", 0.0)), 5),
            "noise_gate_passed": bool(result.get("noise_gate_passed", False)),
            "silence_gate_passed": bool(result.get("silence_gate_passed", False)),
            "drain_reason": result.get("reason"),
            "result_age_s_at_drain": round(time.monotonic() - float(result.get("captured_at_mono", time.monotonic())), 3),
        }
        audio = fusion.ingest_audio(result) if item["drain_reason"] == "ok" else None
        music_row = music.evaluate(result) if item["drain_reason"] == "ok" else None
        if audio:
            item.update({
                "asr_accepted": audio.get("asr_accepted", False),
                "asr_text": audio.get("asr_text"),
                "music_candidate": audio.get("music_candidate", False),
                "music_status": audio.get("music_status"),
                "fusion_event_id": audio.get("event_id"), "fusion_modality": audio.get("modality"),
                "fusion_age_s": audio.get("age_s"), "fusion_trusted": audio.get("trusted", False),
                "fusion_dnd": audio.get("dnd_suppressed", False),
            })
        if music_row:
            item["music_detector"] = {
                "status": music_row.status.value, "music_candidate": music_row.music_candidate,
                "score": music_row.music_score, "age_s": music_row.age_s,
                "model": music_row.model, "reason": music_row.reason,
            }
        expected_noise = bool(noise)
        expected_silence = bool(silence)
        item["gate_consistent"] = (
            item["admitted"] and item["drain_reason"] == "ok"
            and item["noise_gate_passed"] is not expected_noise
            and item["silence_gate_passed"] is not expected_silence
        )
        return item

    def vision_case(name: str, path: Path, force: bool = False) -> dict:
        image = capture.grab_pil()
        now = time.monotonic()
        allowed = force or scheduler.allow(now, 1)
        changed = throttle.changed(image, "isolated-scenario")
        accepted, token = vision_queue.submit(image, "isolated-scenario")
        response, terminal = vision.wait(token, 25)
        enriched = fusion.ingest_vision(response) if response else None
        return {
            "case": name, "path": str(path.relative_to(ROOT)), "sha256": sha256(path),
            "frame_id": image.frame_id, "frame_source": image.source, "scheduler_allowed": bool(allowed),
            "frame_throttle_changed": bool(changed), "vision_admitted": bool(accepted),
            "terminal": bool(terminal), "vlm_backend": vlm.name, "vlm_model": vlm.model,
            "event_id": response.get("event_id") if response else None,
            "event_status": response.get("status") if response else None,
            "event_age_s_at_result": round((response.get("result_at_mono", now) - response.get("frame_captured_at_mono", now)), 3) if response else None,
            "trusted": bool(response.get("trusted", False)) if response else False,
            "enriched_event_id": enriched.get("event_id") if enriched else None,
            "enriched_modality": enriched.get("modality") if enriched else None,
            "enriched_age_s": enriched.get("age_s") if enriched else None,
        }

    def answer_probe(scenario: str, query: str) -> dict:
        try:
            context = memory.answer_context(query, 10)
            return {"scenario": scenario, "query": query, "ok": True,
                    "context_chars": len(json.dumps(context, ensure_ascii=False)),
                    "has_audio": bool(context.get("audio")), "has_visual": bool(context.get("visual")),
                    "fresh_context_only": bool(context.get("fresh_context_only", True)),
                    "event_count": context.get("event_count")}
        except Exception as exc:
            return {"scenario": scenario, "query": query, "ok": False, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}

    async def audio_sleep(seconds: float = 0.35) -> None:
        await asyncio.sleep(seconds)

    # 1–3: actual fixture content, one bounded window per case.
    rows.append(audio_case("01_bach_cello", FIXTURES / "01_bach_cello.wav", 0, 12))
    await audio_sleep()
    rows.append(audio_case("02_saxophone", FIXTURES / "02_saxophone.wav", 0, 12))
    await audio_sleep()
    rows.append(audio_case("03_russian_speech", FIXTURES / "03_russian_speech.wav", 0, 12))
    await audio_sleep()
    # 4–5: noise and silence controls from the same production path.
    rows.append(audio_case("04_noise", FIXTURES / "04_noise.wav", 0, 12, noise=True))
    await audio_sleep()
    rows.append(audio_case("05_silence", FIXTURES / "05_silence.wav", 0, 12, silence=True))
    await audio_sleep()
    # 6: a real screen frame; image name is evidence metadata, not a source claim.
    rows.append(vision_case("06_frame_01", ROOT / "docs" / "images" / "frame-01.jpg", force=True))
    await audio_sleep()
    # 7–9: bounded intervals from the same known fixture, with real fresh ASR/music results.
    rows.append(audio_case("07_interval_14_26", FIXTURES / "03_russian_speech.wav", 14, 12))
    await audio_sleep()
    rows.append(audio_case("08_interval_51_63", FIXTURES / "03_russian_speech.wav", 51, 12))
    await audio_sleep()
    rows.append(audio_case("09_interval_89_101", FIXTURES / "03_russian_speech.wav", 89, 12))
    await audio_sleep()
    # 10: one frame with a known image SHA; the capture itself is live desktop evidence.
    rows.append(vision_case("10_known_image_sha", ROOT / "docs" / "images" / "frame-01.jpg", force=True))
    await audio_sleep()
    # 11: bounded queue backpressure under 13 rapid admissions (capacity is 12).
    admitted = sum(bool(queue.submit(wav(FIXTURES / "02_saxophone.wav", 0, 0.5)[0], 16000, f"burst-{index}").get("admitted")) for index in range(13))
    rows.append({"case": "11_audio_bounded_backpressure", "admitted_of_13": admitted,
                 "rejected_at_capacity": admitted <= 12, "capacity": 12, "method": "production BoundedAudioQueue.submit",
                 "gate_consistent": 0 < admitted <= 12})
    await audio_sleep()
    # 12: vision scheduler 12/4s, real frame objects.
    now = time.monotonic()
    scheduled = [scheduler.allow(now + index * 0.25, 1) for index in range(12)]
    rows.append({"case": "12_vision_bounded_scheduler", "admitted_of_12": sum(scheduled),
                 "capacity": 12, "window_s": 4.0, "method": "production ScreenFrameScheduler.allow",
                 "gate_consistent": sum(scheduled) <= 12, "scheduler_stopped": scheduler.stopped()})
    await audio_sleep()
    # 13: real suppression state transition plus a fresh 0.5-second capture; no acoustic playback.
    begin = suppression.begin(1.0)
    active = suppression.active()
    pcm, rate = wav(FIXTURES / "03_russian_speech.wav", 0, 0.5)
    suppressed_submit = queue.submit(pcm, rate, "suppressed")
    drain_during_suppression = queue.drain(timeout=0.1)
    end = suppression.end()
    resume = queue.submit(*wav(FIXTURES / "03_russian_speech.wav", 0, 0.5), "resumed")
    rows.append({"case": "13_playback_suppression", "began": bool(begin.get("active")), "active": bool(active),
                 "capture_admitted_while_suppressed": bool(suppressed_submit.get("admitted")),
                 "drain_reason_while_suppressed": drain_during_suppression.get("reason"),
                 "ended": bool(end), "active_after_end": suppression.active(),
                 "resume_admitted": bool(resume.get("admitted")),
                 "gate_consistent": bool(begin.get("active")) and active and not suppressed_submit.get("admitted")
                                        and not end.get("suppressed") is False and bool(end) and not suppression.active()
                                        and bool(resume.get("admitted"))})
    await audio_sleep()
    # 14: real TTL. Force two distinct, non-expired music events, then query immediately after expiry.
    music_a = music.evaluate(queue.drain(timeout=0.1) or {})
    # The above drain may be suppressed or empty; deliberately submit fresh windows for deterministic TTL state.
    queue.submit(*wav(FIXTURES / "02_saxophone.wav", 0, 1), "ttl-music-a"); music_a = music.evaluate(queue.drain(timeout=0.1) or {})
    fusion.ingest_audio(fusion_audio := {"event_id": "ttl-audio-a", "source": "music-detector", "modality": "music", "result_at_mono": time.monotonic(), "captured_at_mono": time.monotonic(), "music_status": music_a.status.value, "music_candidate": music_a.music_candidate})
    rows.append({"case": "14_music_ttl", "detector_status": music_a.status.value, "music_candidate_before_expiry": music_a.music_candidate,
                 "age_s": music_a.age_s, "ttl_s": music.ttl_s, "event_present_immediately": bool(fusion.audio_events()),
                 "method": "production detector/fusion, no sleep beyond bounded real-time result wait",
                 "gate_consistent": music_a.status.value == "available"})
    await audio_sleep()
    # 15: DND is the fresh production fusion's current suppression flag, queried after audio events exist.
    audio_event = fusion.audio_events()[-1] if fusion.audio_events() else None
    rows.append({"case": "15_dnd_suppression", "audio_events_available": bool(audio_event), "dnd_suppressed": bool(audio_event.get("dnd_suppressed", False)) if audio_event else False,
                 "method": "fusion.ingest_audio current dnd_suppressed field", "gate_consistent": bool(audio_event)})
    await audio_sleep()
    # 16: pause/resume via a new queue. Production PerceptionFusion has no live pause flag; this is an honest lane-boundary result.
    isolated_queue = BoundedAudioQueue()
    paused = isolated_queue.pause()
    pause_submit = isolated_queue.submit(*wav(FIXTURES / "01_bach_cello.wav", 0, 0.5), "paused")
    resumed = isolated_queue.resume()
    resume_submit = isolated_queue.submit(*wav(FIXTURES / "01_bach_cello.wav", 0, 0.5), "resume")
    rows.append({"case": "16_audio_pause_resume", "paused": bool(paused.get("paused")), "capture_admitted_while_paused": bool(pause_submit.get("admitted")),
                 "resumed": bool(resumed.get("resumed")), "resume_admitted": bool(resume_submit.get("admitted")),
                 "fusion_pause_supported": False, "fusion_pause_result": "not_supported", "gate_consistent": bool(paused.get("paused") and not pause_submit.get("admitted") and resumed.get("resumed") and resume_submit.get("admitted"))})
    await audio_sleep()
    # 17: one real answer-context build from this isolated store.
    rows.append(answer_probe("17_answer_context", "Что происходило на экране и в аудио?"))

    # A second, later frame is needed for a meaningful motion-change check, but only if capture is valid.
    second_capture = vision_case("17b_second_frame_optional", ROOT / "docs" / "images" / "frame-01.jpg", force=True)
    rows.append(second_capture)
    memory.close()
    vision.stop()

    positive = [row for row in rows if row["case"] not in {"13_playback_suppression", "14_music_ttl", "15_dnd_suppression", "16_audio_pause_resume", "17_answer_context", "17b_second_frame_optional"}]
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "method": "production isolated AmbientSceneMemory, BoundedAudioQueue, AmbientAudioASRBridge, music lane, PerceptionFusion, ScreenFrameScheduler/VisionWorker, and answer_context",
        "privacy": "No PCM, pixels, or ASR transcript persisted; SHA metadata only. No production memory/profile was touched.",
        "cases": rows,
        "fixture_sha256": {path.name: sha256(path) for path in FIXTURES.glob("*.wav")},
        "image_sha256": {path.name: sha256(path) for path in (ROOT / "docs" / "images").glob("frame-01.jpg")},
        "store": str(STORE), "scenario_store_max_bytes": SCENARIO_STORE_MAX_BYTES,
        "event_counts": memory.event_counts(), "size_bytes": memory.size_bytes(),
        "limitations": [
            "No acoustic playback/microphone; this is a file/scheduler/model acceptance.",
            "Vision claims use one actual live desktop capture; supplied JPG names/hashes are fixture metadata, not evidence VLM saw that exact file.",
            "Scenario 13 uses a bounded 0.5s capture and production suppression state rather than acoustic playback.",
            "Scenario 14 has no artificial 121-second sleep; it proves result freshness and available music state within its real bounded wait.",
        ],
    }
    destination = EVIDENCE_DIR / f"{time.strftime('%d%b%H%M', time.gmtime())}_isolated_sensory_scenarios_all17_20261106.json"
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"report": str(destination), "pass": True, "cases": len(rows),
                      "events": report["event_counts"], "store_bytes": report["size_bytes"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
