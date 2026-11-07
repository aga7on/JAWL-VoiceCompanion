"""YouTube Multimodal Watching Orchestrator for JAWL.

Watches YouTube videos end-to-end starting at t=0s:
- Visual: DXGI Desktop Duplication -> SceneDeltaDetector -> StoryboardGrid -> FoveatedVision -> LanceDB
- Audio: WASAPI Loopback -> DSP Affective Engine (Centroid, HNR, RMS) -> GigaAM v3 RNN-T ASR
- Synthesis: NarrativeConsolidator (episodes, character cards, timeline)
- Control: Replay, seek, verify
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import logging
import os
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import psutil

from jawl_voicecompanion.affective_engine import AffectiveEngine
from jawl_voicecompanion.episodic_visual_memory import EpisodicVisualMemory
from jawl_voicecompanion.giga_final import CrispASRFileTranscriber, GigaAMBatchError
from jawl_voicecompanion.narrative_consolidator import NarrativeConsolidator
from jawl_voicecompanion.process_loopback import ProcessLoopbackBridge
from jawl_voicecompanion.scene_state import (
    HypothesisDrivenEntityTracker,
    NarrativeSpeechEvent,
    SceneState,
)
from jawl_voicecompanion.system_audio import SystemAudioLoopback
from jawl_voicecompanion.visual_stream import (
    AsyncVisualRingBuffer,
    DXGIScreenCapture,
    FoveatedVisionProcessor,
    IncrementalSpatialMatrix,
    SceneDeltaDetector,
    StoryboardGridAssembler,
)

logger = logging.getLogger("youtube_watcher")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ROOT = Path(__file__).resolve().parent.parent
CRISP_EXE = ROOT / "runtime/bin/crispasr/crispasr.exe"
GIGAAM_GGUF = ROOT / "runtime/models/asr/gigaam-v3-e2e-rnnt-q8_0.gguf"


class BrowserVideoSession:
    """Manages Chrome browser session playing YouTube video."""

    def __init__(self, url: str) -> None:
        url_str = str(url)
        if not url_str.startswith(("http://", "https://", "file://")):
            p = Path(url_str).resolve()
            if p.exists():
                url_str = p.as_uri()
        self.url = url_str
        self.driver: webdriver.Chrome | None = None

    def start(self) -> None:
        opts = Options()
        opts.add_argument("--autoplay-policy=no-user-gesture-required")
        opts.add_argument("--start-maximized")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--disable-search-engine-choice-screen")

        logger.info("Starting Chrome browser for: %s", self.url)
        self.driver = webdriver.Chrome(options=opts)
        self.driver.get(self.url)
        time.sleep(3)

        # Ensure video is playing from 0.0s, unmuted, volume 1.0
        js_init = """
        var skipBtn = document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-ad-overlay-close-button');
        if (skipBtn) {
            try { skipBtn.click(); } catch(e) {}
        }
        var playBtn = document.querySelector('.ytp-play-button');
        var v = document.querySelector('video');
        if (v) {
            v.currentTime = 0.0;
            v.muted = false;
            v.volume = 1.0;
            var p = v.play();
            if (p && p.catch) { p.catch(function(e) { if (playBtn) playBtn.click(); }); }
            return {found: true, duration: v.duration, currentTime: v.currentTime, paused: v.paused};
        }
        return {found: false};
        """
        res = self.driver.execute_script(js_init)
        logger.info("Video initialized: %s", res)

    def bring_to_front(self) -> None:
        """Reliably maximizes and raises Chrome window to foreground using Win32 API."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            target_hwnd = None
            if self.driver and hasattr(self.driver, "service"):
                drv_pid = self.driver.service.process.pid
                proc = psutil.Process(drv_pid)
                pids = {c.pid for c in proc.children(recursive=True)} | {drv_pid}

                def enum_cb(h, _):
                    nonlocal target_hwnd
                    if user32.IsWindowVisible(h):
                        w_pid = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(h, ctypes.byref(w_pid))
                        if w_pid.value in pids:
                            length = user32.GetWindowTextLengthW(h)
                            if length > 0:
                                target_hwnd = h
                                return False
                    return True

                user32.EnumWindows(
                    ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(enum_cb),
                    0,
                )

            if target_hwnd:
                user32.ShowWindow(target_hwnd, 3)  # SW_MAXIMIZE
                user32.SwitchToThisWindow(target_hwnd, True)
                logger.info("Raised Chrome window (HWND %s) to foreground", target_hwnd)
        except Exception as exc:
            logger.warning("Foreground window activation skipped: %s", exc)

    def get_current_time(self) -> float:
        if not self.driver:
            return 0.0
        try:
            val = self.driver.execute_script("var v = document.querySelector('video'); return v ? v.currentTime : 0.0;")
            return float(val or 0.0)
        except Exception:
            return 0.0

    def get_duration(self) -> float:
        if not self.driver:
            return 0.0
        try:
            val = self.driver.execute_script("var v = document.querySelector('video'); return v ? v.duration : 0.0;")
            return float(val or 0.0)
        except Exception:
            return 0.0

    def is_playing(self) -> bool:
        if not self.driver:
            return False
        try:
            val = self.driver.execute_script("var v = document.querySelector('video'); return v ? (!v.paused && !v.ended) : False;")
            return bool(val)
        except Exception:
            return False

    def seek_to(self, seconds: float) -> None:
        if not self.driver:
            return
        logger.info("Seeking video to %.1f s", seconds)
        self.driver.execute_script(f"var v = document.querySelector('video'); if (v) {{ v.currentTime = {float(seconds)}; v.play(); }}")

    def pause(self) -> None:
        if not self.driver:
            return
        self.driver.execute_script("var v = document.querySelector('video'); if (v) v.pause();")

    def play(self) -> None:
        if not self.driver:
            return
        self.driver.execute_script("var v = document.querySelector('video'); if (v) v.play();")

    def check_and_keep_playing(self) -> None:
        if not self.driver:
            return
        js_keep = """
        var skipBtn = document.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-ad-overlay-close-button');
        if (skipBtn) {
            try { skipBtn.click(); } catch(e) {}
        }
        var v = document.querySelector('video');
        if (v) {
            if (v.muted) v.muted = false;
            if (v.paused && !v.ended) v.play();
        }
        """
        try:
            self.driver.execute_script(js_keep)
        except Exception:
            pass

    def close(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


class MultimodalWatcherSession:
    """Full multimodal capture session for YouTube video."""

    def __init__(
        self,
        url: str,
        *,
        output_dir: Path | None = None,
        max_duration_sec: float = 60.0,
    ) -> None:
        self.url = url
        self.max_duration_sec = max_duration_sec
        self.output_dir = output_dir or (ROOT / "runtime/instances/daily/data/sensory/youtube_watch")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.browser = BrowserVideoSession(url)
        self.transcriber = CrispASRFileTranscriber(str(CRISP_EXE), str(GIGAAM_GGUF))
        self.transcriber.prefetch()

        self.affective = AffectiveEngine()
        self.delta_detector = SceneDeltaDetector(grid_size=64, change_threshold=0.08)
        self.spatial_matrix = IncrementalSpatialMatrix(grid_shape=(21, 30), feature_dim=64, keyframe_interval=60)
        self.storyboard = StoryboardGridAssembler(quadrant_size=512)
        self.fovea = FoveatedVisionProcessor(coarse_resolution=(640, 360), foveal_crop_size=512)
        self.ring_buffer = AsyncVisualRingBuffer(maxlen=8)

        # Episodic memory in session directory
        self.mem_dir = self.output_dir / "visual_memory"
        self.visual_memory = EpisodicVisualMemory(
            db_path=self.mem_dir / "lancedb",
            image_cache_dir=self.mem_dir / "keyframes",
        )
        self.consolidator = NarrativeConsolidator(
            episodic_memory=self.visual_memory,
            consolidation_interval_sec=10.0,
            storage_path=self.output_dir / "narrative_state.json",
        )

        # Raw audio buffer for slices
        self._audio_lock = threading.Lock()
        self._raw_pcm_chunks: list[bytes] = []
        self._pcm_sample_rate = 48000
        self._pcm_channels = 2

        # Ledgers
        self.visual_events: list[dict[str, Any]] = []
        self.audio_events: list[dict[str, Any]] = []
        self.speech_events: list[dict[str, Any]] = []

        # Level 2 & 3: SceneState and Hypothesis-Driven Tracking
        self.tracker = HypothesisDrivenEntityTracker(
            iou_match_threshold=0.30,
            reid_hypothesis_threshold=0.70,
            reid_confirm_threshold=0.85,
            track_retention_sec=15.0,
        )
        self._latest_speech_event: NarrativeSpeechEvent | None = None
        self._prev_scene_state: Any | None = None
        self.semantic_diffs: list[dict[str, Any]] = []
        self.scene_state_snapshots: list[dict[str, Any]] = []

        self._running = False
        self._capture: DXGIScreenCapture | None = None
        self._loopback: SystemAudioLoopback | None = None
        self._proc_loopback: ProcessLoopbackBridge | None = None

    def _on_pcm(self, data: bytes, rate: int, channels: int, _sid: str = "") -> None:
        with self._audio_lock:
            self._raw_pcm_chunks.append(data)
            self._pcm_sample_rate = rate
            self._pcm_channels = channels

    def run_session(self) -> dict[str, Any]:
        """Runs the multimodal watching session."""
        self._running = True
        logger.info("=== STARTING MULTIMODAL WATCHING SESSION ===")
        logger.info("Video URL: %s", self.url)

        self.browser.start()
        time.sleep(2.0)

        # Bring Chrome window to front to guarantee active DWM desktop duplication
        self.browser.bring_to_front()

        # 1. Attach Audio Capture: prefer ProcessLoopbackBridge (isolated Chrome audio), fallback to WASAPI
        attached_audio = False
        try:
            if self.browser.driver and hasattr(self.browser.driver, "service"):
                srv_pid = self.browser.driver.service.process.pid
                driver_proc = psutil.Process(srv_pid)
                children = driver_proc.children(recursive=True)
                target_pid = children[0].pid if children else srv_pid
                bridge = ProcessLoopbackBridge()
                bridge.start(target_pid, consumer=lambda d, r, c: self._on_pcm(d, r, c))
                self._proc_loopback = bridge
                attached_audio = True
                logger.info("Attached native ProcessLoopbackBridge to Chrome PID %d", target_pid)
        except Exception as exc:
            logger.warning("Native ProcessLoopbackBridge attach failed: %s", exc)

        if not attached_audio:
            try:
                self._loopback = SystemAudioLoopback(
                    consumer=self._on_pcm,
                    output_device_name="Game-Audeze Maxwell",
                )
                self._loopback.start()
                logger.info("WASAPI Loopback started on Game-Audeze Maxwell")
            except Exception as exc:
                logger.warning("Preferred Maxwell loopback not active (%s), falling back to system default loopback", exc)
                self._loopback = SystemAudioLoopback(
                    consumer=self._on_pcm,
                    output_device_name=None,
                )
                self._loopback.start()
                logger.info("WASAPI Loopback started on default loopback device")

        # Start DXGI capture
        self._capture = DXGIScreenCapture()

        start_mono = time.monotonic()
        last_audio_drain = time.monotonic()
        last_checkpoint = time.monotonic()
        last_vid_time = 0.0

        try:
            while self._running:
                now_mono = time.monotonic()
                elapsed = now_mono - start_mono
                if elapsed >= self.max_duration_sec:
                    logger.info("Reached target duration limit: %.1f s", elapsed)
                    break

                vid_time = self.browser.get_current_time()
                vid_dur = self.browser.get_duration()
                if vid_dur > 0 and vid_time >= (vid_dur - 1.0):
                    logger.info("Video reached end (%.1f / %.1f s)", vid_time, vid_dur)
                    break

                if int(elapsed) % 3 == 0:
                    self.browser.check_and_keep_playing()
                if int(elapsed) % 15 == 0:
                    self.browser.bring_to_front()

                # 1. Video Processing Step
                frame = self._capture.grab()
                if frame is not None:
                    # Spatial Matrix Update (21x30 Language-Out-of-the-Loop with Opponent Color)
                    matrix_changed, dirty_count, matrix_bbox = self.spatial_matrix.update(frame, commit=True)
                    delta, changed, sid = self.delta_detector.compute_delta(frame, commit=True)

                    # Update Level 2 Entity Tracker & Level 3 Narrative
                    det_boxes = []
                    if matrix_bbox is not None and dirty_count >= 4:
                        det_boxes.append({
                            "bbox": matrix_bbox,
                            "label": "персонаж" if (matrix_bbox[2] - matrix_bbox[0]) > 0.12 else "деталь",
                            "conf": 0.88,
                        })

                    active_sp = self._latest_speech_event
                    self._latest_speech_event = None

                    scene_state = self.tracker.update_frame(
                        frame,
                        timestamp_ms=vid_time * 1000.0,
                        detected_boxes=det_boxes,
                        spatial_delta_bbox=matrix_bbox,
                        dirty_ratio=dirty_count / 630.0,
                        dirty_count=dirty_count,
                        active_speech=active_sp,
                    )

                    # Check semantic diff
                    if self._prev_scene_state is not None:
                        sem_diff = scene_state.compute_semantic_diff(self._prev_scene_state)
                        if sem_diff.get("has_change"):
                            self.semantic_diffs.append({
                                "vid_time_sec": round(vid_time, 2),
                                "diff": sem_diff,
                            })
                    self._prev_scene_state = scene_state

                    if changed or (matrix_changed and dirty_count >= 15):
                        vid_ts_str = f"{int(vid_time // 60):02d}:{int(vid_time % 60):02d}"
                        sal_delta = self.delta_detector.last_saliency_delta
                        c_bbox = self.delta_detector.last_change_bbox or matrix_bbox
                        self.scene_state_snapshots.append(scene_state.to_dict())

                        # Foveated dual-stream
                        fov_res = self.fovea.process(frame, saliency_bbox=c_bbox)
                        foveal_path = None
                        if sal_delta > 0 or matrix_bbox is not None:
                            fov_name = f"foveal_{sid}_{int(vid_time)}.webp"
                            fov_file = self.output_dir / "foveal_crops" / fov_name
                            fov_file.parent.mkdir(parents=True, exist_ok=True)
                            fov_res["foveal_crop"].save(fov_file, format="WEBP", quality=90)
                            foveal_path = str(fov_file)

                        # Storyboard 2x2 assembly
                        self.storyboard.add_keyframe(frame, f"{sid}_{vid_ts_str}", time.monotonic())
                        collage_path = None
                        if self.storyboard.ready:
                            collage = self.storyboard.assemble()
                            if collage is not None:
                                c_name = f"collage_{sid}_{int(vid_time)}.webp"
                                c_file = self.output_dir / "collages" / c_name
                                c_file.parent.mkdir(parents=True, exist_ok=True)
                                collage.save(c_file, format="WEBP", quality=80)
                                collage_path = str(c_file)
                                self.storyboard.clear()

                        # Ingest to Episodic Visual Memory
                        summary_txt = f"[{vid_ts_str}] Сцена {sid}, дельта {delta:.2f}, dirty-тайлы {dirty_count}"
                        if sal_delta > 0:
                            summary_txt += f", салиентность {sal_delta:.2f} (bbox {c_bbox})"
                        
                        ingest_res = self.visual_memory.ingest_keyframe(
                            frame,
                            scene_id=sid,
                            summary=summary_txt,
                            app_name="YouTube",
                            window_title=f"Video @ {vid_ts_str}",
                            extra_metadata={
                                "video_time_sec": round(vid_time, 2),
                                "timestamp_str": vid_ts_str,
                                "saliency_delta": sal_delta,
                                "change_bbox": c_bbox,
                                "matrix_dirty_count": dirty_count,
                                "matrix_bbox": matrix_bbox,
                                "collage_path": collage_path,
                                "foveal_path": foveal_path,
                            },
                        )

                        self.consolidator.feed_keyframe(
                            scene_id=sid,
                            webp_path=ingest_res.get("image_path", ""),
                            summary=summary_txt,
                            timestamp=vid_time,
                        )

                        self.visual_events.append({
                            "time_sec": round(vid_time, 2),
                            "timestamp": vid_ts_str,
                            "scene_id": sid,
                            "delta": delta,
                            "saliency_delta": sal_delta,
                            "change_bbox": c_bbox,
                            "matrix_dirty_count": dirty_count,
                            "matrix_bbox": matrix_bbox,
                            "summary": summary_txt,
                            "image_path": ingest_res.get("image_path", ""),
                            "collage_path": collage_path,
                            "foveal_path": foveal_path,
                        })
                        logger.info("Visual keyframe [%s] %s (delta=%.3f, sal=%.3f, dirty=%d)", vid_ts_str, sid, delta, sal_delta, dirty_count)

                # 2. Audio Processing Step (Every 3.0 seconds drain & transcribe)
                if now_mono - last_audio_drain >= 3.0:
                    with self._audio_lock:
                        chunks_to_process = list(self._raw_pcm_chunks)
                        self._raw_pcm_chunks.clear()
                        srate = self._pcm_sample_rate
                        channels = self._pcm_channels

                    last_audio_drain = now_mono
                    if chunks_to_process:
                        raw_bytes = b"".join(chunks_to_process)
                        if len(raw_bytes) >= 16000:
                            self._process_audio_slice(raw_bytes, srate, channels, last_vid_time, vid_time)

                    last_vid_time = vid_time

                # 3. Checkpoint ledger every 30 seconds
                if now_mono - last_checkpoint >= 30.0:
                    last_checkpoint = now_mono
                    self._save_ledger(start_mono, is_checkpoint=True)

                # Small sleep to cap loop cadence ~ 5-10 Hz
                time.sleep(0.15)

        finally:
            self._running = False
            if self._proc_loopback:
                try:
                    self._proc_loopback.stop()
                except Exception:
                    pass
            if self._capture:
                self._capture.stop()
            if self._loopback:
                self._loopback.stop()
            self.browser.pause()

        # Final consolidation pass
        logger.info("Finalizing narrative consolidation...")
        self.consolidator.consolidate(force=True)

        return self._save_ledger(start_mono, is_checkpoint=False)

    def _save_ledger(self, start_mono: float, is_checkpoint: bool = False) -> dict[str, Any]:
        """Builds and serializes session ledger."""
        ledger = {
            "url": self.url,
            "duration_watched_sec": round(time.monotonic() - start_mono, 2),
            "is_checkpoint": is_checkpoint,
            "spatial_matrix_state": self.spatial_matrix.state(),
            "visual_events": self.visual_events,
            "audio_events": self.audio_events,
            "speech_events": self.speech_events,
            "entity_tracker_summary": {
                "active_entities": [e.to_dict() for e in self.tracker.current_state.entities.values()],
                "total_hypotheses": len(self.tracker._hypotheses_history),
                "confirmed_hypotheses": sum(1 for h in self.tracker._hypotheses_history if h.status == "confirmed"),
                "proposed_hypotheses": sum(1 for h in self.tracker._hypotheses_history if h.status == "proposed"),
                "hypotheses_log": [h.to_dict() for h in self.tracker._hypotheses_history],
            },
            "semantic_diffs": self.semantic_diffs[:80],
            "scene_state_snapshots": self.scene_state_snapshots,
            "episode_logs": list(self.consolidator._episode_logs),
            "character_cards": self.consolidator.get_character_cards(),
        }

        ledger_path = self.output_dir / "multimodal_session_ledger.json"
        tmp_path = self.output_dir / "multimodal_session_ledger.json.tmp"
        tmp_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(ledger_path)
        if not is_checkpoint:
            logger.info("Session complete. Ledger saved to: %s", ledger_path)
        else:
            logger.debug("Ledger checkpoint saved to: %s", ledger_path)

        return ledger

    def _process_audio_slice(
        self,
        raw_pcm: bytes,
        srate: int,
        channels: int,
        start_vid_t: float,
        end_vid_t: float,
    ) -> None:
        """Processes an audio slice: DSP descriptors + GigaAM ASR."""
        # Convert stereo to mono 16kHz
        try:
            arr = np.frombuffer(raw_pcm, dtype=np.int16)
            if channels > 1:
                arr = arr.reshape(-1, channels).mean(axis=1).astype(np.int16)

            # Resample to 16000 if needed
            if srate != 16000:
                # Linear interpolation resample
                num_samples_16k = int(len(arr) * 16000 / srate)
                arr_16k = np.interp(
                    np.linspace(0, len(arr), num_samples_16k, endpoint=False),
                    np.arange(len(arr)),
                    arr,
                ).astype(np.int16)
            else:
                arr_16k = arr

            # DSP Affective analysis
            desc = self.affective.process_pcm_chunk(arr_16k.tobytes(), sample_rate=16000, channels=1)
            rms = float(desc.get("rms", 0.0))
            centroid = float(desc.get("centroid_hz", 0.0))
            hnr = float(desc.get("hnr", 0.0))
            valence = float(desc.get("valence", 0.0))
            arousal = float(desc.get("arousal", 0.0))

            t_start_str = f"{int(start_vid_t // 60):02d}:{int(start_vid_t % 60):02d}"
            t_end_str = f"{int(end_vid_t // 60):02d}:{int(end_vid_t % 60):02d}"

            # Classify soundtrack character:
            # High centroid + high energy -> Action / Dramatic Music / Percussion
            # Low centroid + high HNR -> Melodic Sound / Ambient Pad / Speech
            soundtrack_type = "тишина/фон"
            if rms > 0.03:
                if centroid > 2200:
                    soundtrack_type = "динамичный саундтрек / перкуссия / SFX"
                elif hnr > 5.0:
                    soundtrack_type = "мелодичный саундтрек / вокал / гармония"
                else:
                    soundtrack_type = "напряженный амбиент / шум"

            self.audio_events.append({
                "time_range": f"{t_start_str} - {t_end_str}",
                "start_sec": round(float(start_vid_t), 2),
                "end_sec": round(float(end_vid_t), 2),
                "rms": round(rms, 4),
                "centroid_hz": round(centroid, 1),
                "hnr_db": round(hnr, 2),
                "valence": round(valence, 3),
                "arousal": round(arousal, 3),
                "soundtrack_character": soundtrack_type,
            })

            # If energy indicates speech, run GigaAM ASR
            if rms > 0.02:
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(arr_16k.tobytes())
                wav_bytes = buf.getvalue()

                try:
                    transcript = self.transcriber.transcribe(wav_bytes)
                    if transcript and transcript.strip():
                        text = transcript.strip()
                        speech_ev = NarrativeSpeechEvent(
                            text=text,
                            start_ms=float(start_vid_t) * 1000.0,
                            end_ms=float(end_vid_t) * 1000.0,
                        )
                        self._latest_speech_event = speech_ev
                        self.speech_events.append({
                            "time_range": f"{t_start_str} - {t_end_str}",
                            "start_sec": round(start_vid_t, 2),
                            "end_sec": round(end_vid_t, 2),
                            "text": text,
                        })
                        self.consolidator.feed_subtitle(text, timestamp=start_vid_t)
                        logger.info("ASR [%s - %s]: '%s'", t_start_str, t_end_str, text)
                except GigaAMBatchError:
                    pass  # Empty / silence / noise
                except Exception as e:
                    logger.debug("ASR error on slice: %s", e)

        except Exception as e:
            logger.warning("Audio slice processing failed: %s", e)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--duration", type=float, default=60.0, help="Max duration to watch in seconds")
    parser.add_argument("--output", type=Path, default=None, help="Output directory for ledger and memories")
    args = parser.parse_args()

    session = MultimodalWatcherSession(
        url=args.url,
        max_duration_sec=args.duration,
        output_dir=args.output,
    )
    session.run_session()


if __name__ == "__main__":
    main()
