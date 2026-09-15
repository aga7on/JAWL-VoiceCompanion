"""Exercise real browser microphone barge-in and the single TTS owner.

The fake capture device is fed one WAV containing two utterances.  The first
utterance is separated from the second by a configurable silence window so the
first response can start speaking.  This is intentionally stricter than the
chat-stream cancellation probe: it observes the real mic/VAD, voice/end,
TTS-cancel and browser audio-buffer path together.
"""

from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_wav(path: Path) -> tuple[wave._wave_params, bytes]:
    with wave.open(str(path), "rb") as source:
        params = source.getparams()
        if params.nchannels != 1 or params.sampwidth != 2:
            raise ValueError(f"{path}: expected mono PCM16 WAV")
        return params, source.readframes(source.getnframes())


def _compose(first: Path, second: Path, gap_seconds: float, target: Path) -> float:
    params, first_data = _read_wav(first)
    second_params, second_data = _read_wav(second)
    if (params.nchannels, params.sampwidth, params.framerate) != (
        second_params.nchannels, second_params.sampwidth, second_params.framerate
    ):
        raise ValueError("input WAV formats must match")
    silence = b"\x00\x00" * int(params.framerate * gap_seconds)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as output:
        output.setparams(params)
        output.writeframes(first_data + silence + second_data)
    return (len(first_data) + len(silence) + len(second_data)) / (params.framerate * 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Real browser microphone barge-in acceptance")
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--expected-first", required=True)
    parser.add_argument("--expected-second", required=True)
    parser.add_argument("--gap-seconds", type=float, default=20.0)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--report", type=Path, default=Path("runtime/browser-barge-in-e2e.json"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("runtime/browser-evidence/barge-in"))
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    report: dict[str, object] = {
        "schema_version": 1,
        "profile": "browser_barge_in_e2e",
        "status": "refused" if not args.live else "failed",
        "mode": "real_browser_capture",
        "url": args.url,
        "failure": None,
        "gap_seconds": args.gap_seconds,
    }
    if not args.live:
        report["failure"] = "live_acknowledgement_required"
        return _write(args.report, report, 2)
    if args.gap_seconds < 2 or args.gap_seconds > 240:
        report["failure"] = "gap_seconds_out_of_bounds"
        return _write(args.report, report, 2)

    capture = ROOT / "runtime" / "barge-in-capture.wav"
    try:
        duration = _compose(args.first, args.second, args.gap_seconds, capture)
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.support.ui import WebDriverWait

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--autoplay-policy=no-user-gesture-required")
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument("--use-fake-device-for-media-stream")
        options.add_argument(f"--use-file-for-fake-audio-capture={capture.resolve()}")
        options.add_argument("--window-size=1440,1000")
        driver = webdriver.Edge(options=options)
        failure_state: dict[str, object] = {}
        try:
            driver.set_script_timeout(args.timeout + 30)
            phase = "load_companion_page"
            driver.get(args.url.rstrip("/") + "/")
            wait = WebDriverWait(driver, args.timeout)
            phase = "wait_chat_controls"
            wait.until(lambda d: d.find_element(By.ID, "send").is_displayed())
            phase = "install_observability"
            driver.execute_script(_OBSERVE)
            driver.execute_script("window.__barge.started_ms=performance.now()")
            phase = "enable_hands_free"
            hands_free = driver.find_element(By.ID, "hands-free")
            if not hands_free.is_selected():
                driver.execute_script(
                    "const e=document.querySelector('#hands-free'); e.click();"
                )
            phase = "start_microphone"
            driver.find_element(By.ID, "mic").click()
            phase = "wait_get_user_media"
            wait.until(lambda d: d.execute_script("return window.__barge.get_user_media > 0"))
            # Let the complete capture finish.  Voice VAD performs both phrase
            # boundaries; no PCM is posted by the harness.
            phase = "capture_audio"
            time.sleep(duration + 1.5)
            phase = "stop_microphone"
            driver.find_element(By.ID, "mic").click()
            phase = "wait_voice_ends"
            wait.until(lambda d: d.execute_script("return window.__barge.voice_ends >= 2"))
            # The second /api/tts/stream response can arrive before its WAV is
            # decoded and scheduled. Snapshot only after bounded playback
            # starts, otherwise a valid cancellation/restart is reported as a
            # false single-buffer failure. A missing second buffer still fails
            # the acceptance after this explicit wait.
            phase = "wait_second_playback"
            playback_wait = min(30, max(5, args.timeout))
            WebDriverWait(driver, playback_wait).until(
                lambda d: d.execute_script(
                    "return window.__barge.buffer_source_starts >= 2"
                )
            )
            state = driver.execute_script("return window.__barge")
            report["browser_state"] = state
            report["screenshot"] = str(args.evidence_dir / "browser-barge-in.png")
            args.evidence_dir.mkdir(parents=True, exist_ok=True)
            driver.save_screenshot(str(args.evidence_dir / "browser-barge-in.png"))
            fetches = state.get("fetches", []) if isinstance(state, dict) else []
            ends = [item for item in fetches if item.get("path") == "/api/voice/end" and item.get("status") == 200]
            cancels = [item for item in fetches if item.get("path") == "/api/tts/cancel" and item.get("status") == 200]
            audio_starts = state.get("buffer_source_starts", 0) if isinstance(state, dict) else 0
            tts = [item for item in fetches if item.get("path") == "/api/tts/stream"]
            first_tts = tts[0] if tts else None
            second_end_start = ends[1].get("started_ms", float("inf")) if len(ends) >= 2 else float("inf")
            cancel_during_first_speech = bool(first_tts and any(
                first_tts.get("started_ms", float("inf")) < item.get("started_ms", 0) < second_end_start
                for item in cancels
            ))
            report["acceptance"] = {
                "two_voice_turns": len(ends) >= 2,
                "tts_cancel_during_first_speech": cancel_during_first_speech,
                "audio_buffers_started": int(audio_starts or 0),
                "two_tts_streams": len(tts) >= 2,
                "first_transcript_matched": any(args.expected_first.casefold() in str(item.get("transcript", "")).casefold() for item in ends),
                "second_transcript_matched": any(args.expected_second.casefold() in str(item.get("transcript", "")).casefold() for item in ends),
            }
            acceptance = report["acceptance"]
            if all(bool(acceptance[key]) for key in (
                "two_voice_turns", "tts_cancel_during_first_speech", "two_tts_streams",
                "first_transcript_matched", "second_transcript_matched",
            )) and int(audio_starts or 0) >= 2:
                report["status"] = "passed"
            else:
                report["failure"] = "barge_in_acceptance_conditions_not_met"
        finally:
            # Snapshot diagnostics before the driver is torn down: a timeout
            # without state is not debuggable.
            if report["status"] != "passed":
                try:
                    report["failure_phase"] = phase
                    report["browser_state_on_failure"] = driver.execute_script("return window.__barge")
                    args.evidence_dir.mkdir(parents=True, exist_ok=True)
                    driver.save_screenshot(str(args.evidence_dir / "browser-barge-in-failure.png"))
                except Exception:
                    pass
            driver.quit()
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}:{exc}"
    return _write(args.report, report, 0 if report["status"] == "passed" else 1)


def _write(path: Path, report: dict[str, object], code: int) -> int:
    target = path if path.is_absolute() else ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return code


_OBSERVE = r"""
(() => {
  window.__barge = {fetches: [], get_user_media: 0, voice_ends: 0,
    buffer_source_starts: 0, started_ms: null};
  const state = window.__barge, nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const raw = typeof input === 'string' ? input : input?.url || '';
    const path = new URL(raw, location.href).pathname;
    let body = null; try { body = typeof init?.body === 'string' ? JSON.parse(init.body) : null; } catch (_) {}
    const item = {path, method: init?.method || 'GET', started_ms: performance.now(), ended_ms: null,
      status: null, transcript: null, session_id: body?.session_id || null};
    state.fetches.push(item);
    const response = await nativeFetch(input, init);
    item.status = response.status; item.ended_ms = performance.now();
    if (path === '/api/voice/end') {
      state.voice_ends += 1;
      response.clone().json().then(x => item.transcript = x.transcript || '').catch(() => {});
    }
    return response;
  };
  const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = c => { state.get_user_media++; return gum(c); };
  const start = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function(...x) { state.buffer_source_starts++; return start.apply(this, x); };
})();
"""


if __name__ == "__main__":
    raise SystemExit(main())
