"""Run synthetic WAVs through the real browser capture and playback path.

The target Companion must already be running with external ASR, native JAWL,
the selected LLM and TTS configured. Edge supplies a fake input device from
each WAV, but the application still owns getUserMedia, gate/VAD, ASR
finalizing, TTS and avatar playback. This harness never posts PCM directly
to an API and never creates a second audio player.
"""

from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError(f"{path.name}: expected mono PCM16 WAV")
        return source.getnframes() / max(1, source.getframerate())


def _driver_options(Options, wav: Path):
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--use-fake-ui-for-media-stream")
    options.add_argument("--use-fake-device-for-media-stream")
    options.add_argument(f"--use-file-for-fake-audio-capture={wav.resolve()}")
    options.add_argument("--window-size=1440,1000")
    return options


def main() -> int:
    parser = argparse.ArgumentParser(description="Live browser capture -> ASR -> JAWL -> TTS E2E")
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--wav", action="append", type=Path, required=True)
    parser.add_argument("--expected", action="append", required=True,
                        help="expected Russian ASR transcript substring, one per WAV")
    parser.add_argument("--allow-single", action="store_true",
                        help="allow one WAV for a focused voice-to-action probe")
    parser.add_argument("--response-timeout", type=int, default=240)
    parser.add_argument("--report", type=Path, default=Path("runtime/browser-voice-e2e.json"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("runtime/browser-evidence/voice"))
    parser.add_argument("--live", action="store_true", help="acknowledge real provider/audio acceptance")
    args = parser.parse_args()
    report = {
        "schema_version": 2,
        "profile": "browser_voice_e2e",
        "status": "refused",
        "mode": "real_browser_capture",
        "url": args.url,
        "turns": [],
        "screenshots": [],
        "failure": None,
    }
    if not args.live:
        report["failure"] = "live_acknowledgement_required"
        return _write(args, report, 2)
    if len(args.wav) < 3 and not (args.allow_single and len(args.wav) == 1):
        report["failure"] = "at_least_three_wav_files_required"
        return _write(args, report, 2)
    if len(args.expected) != len(args.wav):
        report["failure"] = "expected_must_have_one_value_per_wav"
        return _write(args, report, 2)
    durations = []
    try:
        for path in args.wav:
            if not path.is_file():
                raise FileNotFoundError(path)
            duration = _wav_duration(path)
            if duration <= 0 or duration > 60:
                raise ValueError(f"{path.name}: duration must be between 0 and 60 seconds")
            durations.append(duration)
    except (OSError, ValueError, wave.Error) as exc:
        report["failure"] = f"wav_validation:{type(exc).__name__}:{exc}"
        return _write(args, report, 2)

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
    except Exception as exc:
        report["failure"] = f"selenium_import:{type(exc).__name__}"
        return _write(args, report, 1)

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index, (wav_path, expected, duration) in enumerate(
            zip(args.wav, args.expected, durations), 1
        ):
            driver = None
            phase = "create_browser"
            try:
                driver = webdriver.Edge(options=_driver_options(Options, wav_path))
                driver.set_page_load_timeout(30)
                phase = "load_companion_page"
                driver.get(args.url.rstrip("/") + "/")
                wait = WebDriverWait(driver, args.response_timeout)
                phase = "wait_chat_controls"
                wait.until(lambda d: d.find_element(By.ID, "send").is_displayed())
                driver.execute_script(_INSTALL_OBSERVABILITY)
                driver.execute_script("window.__voiceE2E.turn_started_ms = performance.now()")
                baseline = driver.execute_script(
                    "return document.querySelectorAll('#messages .message').length"
                )

                phase = "start_microphone"
                driver.find_element(By.ID, "mic").click()
                phase = "wait_get_user_media"
                wait.until(lambda d: d.execute_script(
                    "return window.__voiceE2E && window.__voiceE2E.get_user_media > 0"
                ))
                # Let the real fake capture feed the AudioWorklet. The extra
                # tail gives the application's upload queue time to flush.
                phase = "capture_audio"
                time.sleep(duration + 0.8)
                phase = "stop_microphone"
                driver.find_element(By.ID, "mic").click()
                phase = "wait_voice_message"
                wait.until(lambda d: d.execute_script(
                    "return document.querySelectorAll('#messages .message').length > arguments[0]",
                    baseline,
                ))
                phase = "wait_voice_end"
                wait.until(lambda d: d.execute_script(
                    "return (window.__voiceE2E?.fetches || []).some(item => "
                    "item.path === '/api/voice/end' && item.status >= 200 && item.status < 300)"
                ))
                phase = "wait_transcript"
                wait.until(lambda d: d.execute_script(
                    "return (window.__voiceE2E?.fetches || []).some(item => "
                    "item.path === '/api/voice/end' && item.transcript !== undefined)"
                ))
                # The штатный TTS owner must have started either streamed
                # AudioBufferSource nodes or its HTMLAudioElement fallback.
                phase = "wait_tts_playback"
                wait.until(lambda d: d.execute_script(
                    "return (window.__voiceE2E?.buffer_source_starts || 0) > 0 || "
                    "(window.__voiceE2E?.media_plays || 0) > 0"
                ))

                phase = "collect_turn"
                result = driver.execute_script(_COLLECT_RESULT, baseline, expected)
                screenshot = args.evidence_dir / f"browser-voice-{index}.png"
                driver.save_screenshot(str(screenshot))
                report["screenshots"].append(str(screenshot))
                result["wav"] = wav_path.name
                result["duration_seconds"] = round(duration, 3)
                result["screenshot"] = str(screenshot)
                report["turns"].append(result)
                if not result["ok"]:
                    raise RuntimeError(f"turn {index} acceptance failed: {result['failure']}")
            except Exception as exc:
                if driver is not None:
                    try:
                        report.setdefault("diagnostics", []).append({
                            "turn": index,
                            "phase": phase,
                            "browser_state": driver.execute_script(
                                "return window.__voiceE2E || null"
                            ),
                            "mic_status": driver.execute_script(
                                "return document.querySelector('#mic-status')?.textContent || ''"
                            ),
                            "gate_status": driver.execute_script(
                                "return document.querySelector('#mic-gate-state')?.textContent || ''"
                            ),
                        })
                    except Exception:
                        pass
                raise RuntimeError(f"turn {index} phase={phase}: {type(exc).__name__}: {exc}") from exc
            finally:
                if driver is not None:
                    driver.quit()
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["failure"] = f"{type(exc).__name__}: {exc}"
    return _write(args, report, 0 if report["status"] == "passed" else 1)


_INSTALL_OBSERVABILITY = r"""
(() => {
  const state = window.__voiceE2E = {
    fetches: [], get_user_media: 0, media_plays: 0, buffer_source_starts: 0,
    buffer_source_start_ms: [], turn_started_ms: null,
    worklet_chunks: 0, last_rms: 0, last_gate_open: false
  };
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const raw = typeof input === 'string' ? input : input?.url || '';
    const path = new URL(raw, location.href).pathname;
    let body = null;
    try { body = typeof init?.body === 'string' ? JSON.parse(init.body) : null; } catch (_) {}
    const item = {path, method: init?.method || 'GET', status: null,
      started_ms: performance.now(), ended_ms: null,
      session_id: body?.session_id || null, correlation_id: body?.correlation_id || null};
    state.fetches.push(item);
    try {
      const response = await nativeFetch(input, init);
      item.status = response.status;
      item.ended_ms = performance.now();
      if (path === '/api/voice/end') {
        response.clone().json().then(data => {
          item.transcript = typeof data.transcript === 'string' ? data.transcript : '';
          item.mode = data.mode || null;
          item.response_ok = data.ok === true;
          item.response_count = Array.isArray(data.responses) ? data.responses.length : 0;
          item.event_types = Array.isArray(data.events) ? data.events.map(event => event.type) : [];
        }).catch(() => { item.response_parse_error = true; });
      }
      return response;
    } catch (error) {
      item.error = error.name || 'fetch_error';
      throw error;
    }
  };
  if (navigator.mediaDevices?.getUserMedia) {
    const nativeGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = constraints => {
      state.get_user_media += 1;
      return nativeGetUserMedia(constraints);
    };
  }
  const nativePlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function(...args) {
    state.media_plays += 1;
    return nativePlay.apply(this, args);
  };
  const nativeStart = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function(...args) {
    state.buffer_source_starts += 1;
    state.buffer_source_start_ms.push(performance.now());
    return nativeStart.apply(this, args);
  };
})();
"""


_COLLECT_RESULT = r"""
return ((baseline, expected) => {
  const state = window.__voiceE2E || {};
  const messages = [...document.querySelectorAll('#messages .message')].slice(baseline)
    .map(item => item.innerText || '');
  const companion = messages.filter(item => /Companion|Компаньон/i.test(item)).join('\n');
  const normalize = value => String(value || '').toLocaleLowerCase('ru-RU')
    .replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const expectedText = normalize(expected);
  const fetches = state.fetches || [];
  const audio = fetches.filter(item => item.path === '/api/voice/audio');
  const ends = fetches.filter(item => item.path === '/api/voice/end');
  const finalEnd = ends[ends.length - 1] || {};
  const firstAudioStart = (state.buffer_source_start_ms || [])[0] ?? null;
  const turnStarted = Number.isFinite(state.turn_started_ms) ? state.turn_started_ms : null;
  const duration = item => Number.isFinite(item?.started_ms) && Number.isFinite(item?.ended_ms)
    ? Math.max(0, item.ended_ms - item.started_ms) : null;
  const endDuration = duration(finalEnd);
  const tts = fetches.filter(item => item.path === '/api/tts/stream' || item.path === '/api/tts/synthesize');
  const firstTts = tts[0] || {};
  const transcript = normalize(finalEnd.transcript);
  const sessions = [...new Set(audio.map(item => item.session_id).filter(Boolean))];
  const endSessions = [...new Set(ends.map(item => item.session_id).filter(Boolean))];
  const correlations = [...new Set(audio.concat(ends).map(item => item.correlation_id).filter(Boolean))];
  const endCorrelation = finalEnd.correlation_id || null;
  const failure = !finalEnd.transcript ? 'no_final_transcript'
    : !transcript.includes(expectedText) ? 'expected_transcript_substring_missing'
    : !companion ? 'no_companion_message'
    : finalEnd.response_ok !== true ? 'voice_end_response_not_ok'
    : finalEnd.response_count < 1 ? 'no_jawl_response'
    : !audio.length ? 'no_audio_upload'
    : !ends.length ? 'no_voice_end'
    : sessions.length !== 1 || endSessions.length !== 1 || sessions[0] !== endSessions[0]
      ? 'voice_session_id_not_consistent'
    : correlations.length !== 1 || endCorrelation !== correlations[0]
      ? 'voice_correlation_id_not_consistent'
    : !tts.length ? 'no_tts_request'
    : null;
  return {
    ok: !failure,
    failure,
    message_count: messages.length,
    expected_transcript_matched: transcript.includes(expectedText),
    transcript_text: finalEnd.transcript || '',
    transcript_length: transcript.length,
    audio_upload_count: audio.length,
    voice_end_count: ends.length,
    tts_request_count: tts.length,
    session_ids: sessions,
    end_session_ids: endSessions,
    correlation_ids: correlations,
    end_correlation_id: endCorrelation,
    event_paths: [...new Set(fetches.map(item => item.path))],
    get_user_media: state.get_user_media || 0,
    media_plays: state.media_plays || 0,
    buffer_source_starts: state.buffer_source_starts || 0,
    user_signal_active: document.querySelector('#user-signal')?.classList.contains('active') || false,
    companion_signal_active: document.querySelector('#companion-signal')?.classList.contains('active') || false,
    voice_end_mode: finalEnd.mode || null,
    response_event_types: finalEnd.event_types || []
    ,timings: {
      turn_to_voice_end_ms: turnStarted !== null && Number.isFinite(finalEnd.ended_ms) ? Math.round(finalEnd.ended_ms - turnStarted) : null,
      voice_end_request_ms: endDuration !== null ? Math.round(endDuration) : null,
      voice_end_to_tts_headers_ms: Number.isFinite(firstTts.ended_ms) && Number.isFinite(finalEnd.ended_ms) ? Math.round(firstTts.ended_ms - finalEnd.ended_ms) : null,
      turn_to_first_audio_ms: turnStarted !== null && firstAudioStart !== null ? Math.round(firstAudioStart - turnStarted) : null,
      first_tts_request_ms: duration(firstTts) !== null ? Math.round(duration(firstTts)) : null,
      total_observed_ms: turnStarted !== null ? Math.round(performance.now() - turnStarted) : null
    }
  };
})(arguments[0], arguments[1]);
"""


def _write(args: argparse.Namespace, report: dict, code: int) -> int:
    path = args.report if args.report.is_absolute() else ROOT / args.report
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
