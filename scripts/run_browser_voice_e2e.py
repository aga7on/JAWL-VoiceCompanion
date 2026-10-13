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
import math
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
_DRAFT_PREVIEW_PREFIX = "Слышу (предварительно): "


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError(f"{path.name}: expected mono PCM16 WAV")
        return source.getnframes() / max(1, source.getframerate())


def _normalize_target_url(value: str, ui: str) -> str:
    """Keep explicit local paths while selecting the requested UI at the root."""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "127.0.0.1", "localhost", "::1"
    }:
        raise ValueError("url_must_target_local_companion")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("url_credentials_not_allowed")
    if parsed.query or parsed.fragment:
        raise ValueError("url_query_or_fragment_not_allowed")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("url_port_invalid") from exc
    path = parsed.path.rstrip("/") or "/"
    if ui == "app" and path == "/":
        path = "/app"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _validate_navigation_url(actual: str, expected: str) -> None:
    """Refuse redirects to foreign hosts, login pages, or unexpected routes."""
    actual_parts = urlsplit(actual)
    expected_parts = urlsplit(expected)
    if actual_parts.username is not None or actual_parts.password is not None:
        raise ValueError("navigation_credentials_not_allowed")
    if (actual_parts.scheme, actual_parts.netloc, actual_parts.path) != (
        expected_parts.scheme, expected_parts.netloc, expected_parts.path
    ) or actual_parts.query or actual_parts.fragment:
        raise ValueError("unexpected_navigation_target")


def _normalize_draft_text(value: str) -> str:
    return " ".join("".join(char.casefold() if char.isalnum() else " " for char in value).split())


def _classify_draft_preview(
    dom_samples: list[dict],
    draft_fetches: list[dict],
    *,
    session_id: str | None,
    correlation_id: str | None,
    voice_end_ms: float | None,
) -> dict:
    """Classify bounded /app preview evidence for one finalized voice utterance."""
    valid_end = (
        isinstance(voice_end_ms, (int, float)) and not isinstance(voice_end_ms, bool)
        and math.isfinite(voice_end_ms)
    )
    valid_requests = [
        row for row in draft_fetches
        if isinstance(row, dict)
        and isinstance(row.get("status"), int) and not isinstance(row.get("status"), bool)
        and 200 <= row["status"] < 300 and row.get("ok") is True
        and row.get("mode") == "streaming"
        and row.get("session_id") == session_id and bool(session_id)
        and row.get("correlation_id") == correlation_id and bool(correlation_id)
        and valid_end
        and isinstance(row.get("started_ms"), (int, float))
        and not isinstance(row.get("started_ms"), bool)
        and math.isfinite(row["started_ms"]) and row["started_ms"] <= voice_end_ms
        and isinstance(row.get("draft"), str) and row["draft"].strip()
    ]
    streamed_texts = [row["draft"].strip() for row in valid_requests]
    base = {
        "dom_sample_count": len(dom_samples),
        "draft_request_count": len(draft_fetches),
        "scoped_streaming_request_count": len(valid_requests),
        "streamed_nonempty_count": len(streamed_texts),
        "preview_sample_count": 0,
        "preview_max_content_len": 0,
        "cleared_after_end": False,
        "preview_after_end": False,
        "failure": None,
    }
    if not valid_end:
        base["failure"] = "voice_end_timestamp_unavailable"
        return base

    before_end_previews = []
    after_end_clear_samples = []
    preview_after_end = False
    oversized = False
    max_raw_content_len = 0
    for sample in dom_samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("text"), str):
            continue
        timestamp = sample.get("t")
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool) or not math.isfinite(timestamp):
            continue
        text = sample["text"]
        has_prefix = text.startswith(_DRAFT_PREVIEW_PREFIX)
        if timestamp > voice_end_ms:
            if has_prefix:
                preview_after_end = True
            else:
                after_end_clear_samples.append(sample)
        if has_prefix:
            raw_content = text[len(_DRAFT_PREVIEW_PREFIX):]
            max_raw_content_len = max(max_raw_content_len, len(raw_content))
            if len(raw_content) > 160:
                oversized = True
                continue
            content = raw_content.strip()
            if content and timestamp <= voice_end_ms:
                before_end_previews.append((sample, content))

    base["preview_sample_count"] = len(before_end_previews)
    base["preview_max_content_len"] = max_raw_content_len
    base["preview_after_end"] = preview_after_end
    base["cleared_after_end"] = bool(after_end_clear_samples) and not preview_after_end
    if oversized:
        base["failure"] = "draft_preview_content_over_160"
        return base
    if preview_after_end:
        base["failure"] = "draft_preview_present_after_voice_end"
        return base
    if not valid_requests:
        if any(isinstance(row, dict) and row.get("mode") == "unavailable" for row in draft_fetches):
            base["failure"] = "draft_lane_unavailable"
        elif any(
            isinstance(row, dict) and row.get("mode") == "streaming"
            and row.get("session_id") == session_id and row.get("correlation_id") == correlation_id
            and isinstance(row.get("status"), int) and not isinstance(row.get("status"), bool)
            and 200 <= row["status"] < 300 and row.get("ok") is True
            for row in draft_fetches
        ):
            base["failure"] = "streamed_draft_empty"
        elif any(isinstance(row, dict) and row.get("mode") == "streaming" for row in draft_fetches):
            base["failure"] = "no_successful_scoped_streaming_draft"
        else:
            base["failure"] = "no_scoped_streaming_draft_request"
        return base
    if not before_end_previews:
        base["failure"] = "draft_preview_not_seen"
        return base

    normalized_drafts = [_normalize_draft_text(text) for text in streamed_texts]
    matched = False
    for _, content in before_end_previews:
        normalized_content = _normalize_draft_text(content)
        if normalized_content and any(
            normalized_content.startswith(draft) or draft.startswith(normalized_content)
            for draft in normalized_drafts if draft
        ):
            matched = True
            break
    if not matched:
        base["failure"] = "draft_preview_text_mismatch"
    elif not base["cleared_after_end"]:
        base["failure"] = "draft_preview_not_cleared_after_voice_end"
    return base


def _validate_draft_preview_ui(ui: str, required: bool) -> None:
    if required and ui != "app":
        raise ValueError("require_draft_preview_requires_app_ui")


def _apply_draft_preview_acceptance(result: dict, required: bool) -> None:
    lane = result.setdefault("draft_lane", {})
    lane["required"] = required
    lane["passed"] = lane.get("failure") is None
    if required and not lane["passed"]:
        if result.get("failure"):
            result["voice_acceptance_failure"] = result["failure"]
        result["failure"] = "required_draft_preview_failed:" + str(lane["failure"])
        result["ok"] = False


_PLAYBACK_EVIDENCE = r"""(state => {
  const fetches = state?.fetches || [];
  const ends = fetches.filter(item => item.path === '/api/voice/end');
  const finalEnd = ends[ends.length - 1] || {};
  const allTts = fetches.filter(item => item.path === '/api/tts/stream' || item.path === '/api/tts/synthesize');
  const tts = allTts.filter(item => Number.isFinite(finalEnd.ended_ms) &&
    Number.isFinite(item.started_ms) && item.started_ms >= finalEnd.ended_ms);
  const bodyTerminal = tts.length > 0 && tts.every(item => item.body_eof === true ||
    item.body_error || item.body_cancelled || item.error);
  const bodyOk = tts.length > 0 && tts.every(item => item.body_eof === true &&
    !item.body_error && !item.body_cancelled && !item.error);
  const firstTts = tts[0] || {};
  const turnStarted = Number.isFinite(state?.turn_started_ms) ? state.turn_started_ms : null;
  const playback = (state?.playback || []).filter(item => item.current_turn &&
    Number.isFinite(finalEnd.ended_ms) && Number.isFinite(firstTts.started_ms) &&
    item.started_ms >= Math.max(turnStarted || 0, finalEnd.ended_ms, firstTts.started_ms));
  const playbackTerminal = playback.length === 0 ? bodyTerminal : playback.every(item =>
    item.ended_ms !== null || item.error);
  const lastActivity = Math.max(0,
    ...tts.map(item => item.body_ended_ms || item.body_error_ms || item.body_cancelled_ms || item.started_ms || 0),
    ...playback.map(item => item.ended_ms || item.started_ms || 0));
  const quiet = performance.now() - lastActivity >= 750;
  const settled = bodyTerminal && playbackTerminal && quiet;
  const playbackDuration = playback.filter(item => item.completed && item.non_silent)
    .reduce((total, item) => total + (Number(item.duration_seconds) || 0), 0);
  const failure = !tts.length ? 'no_current_turn_tts_request'
    : tts.some(item => item.error || item.body_error) ? 'tts_response_body_error'
    : tts.some(item => item.body_cancelled) ? 'tts_response_body_cancelled'
    : !bodyOk ? 'tts_response_body_incomplete'
    : !playback.length ? 'tts_playback_not_observed'
    : playback.some(item => item.error) ? 'tts_playback_error'
    : playback.some(item => !item.non_silent) ? 'tts_playback_silent'
    : playback.some(item => item.timing_unknown) ? 'tts_playback_timing_unknown'
    : playback.some(item => item.interrupted || !item.completed) ? 'tts_playback_interrupted'
    : !settled ? 'tts_playback_not_settled'
    : playbackDuration < 0.08 ? 'tts_playback_silent_or_too_short'
    : null;
  return {
    tts, playback, body_terminal: bodyTerminal, body_ok: bodyOk,
    playback_terminal: playbackTerminal, settled, ready: settled && !failure,
    failure, playback_duration_seconds: playbackDuration,
    method: 'existing TTS response consumer EOF/error/cancel plus sampled PCM RMS and source/media completion events; AudioContext clock and source stop checked when available',
    playback_rate_basis: 'sampled playbackRate.value and detune.value; scheduled AudioParam automation is not observable',
    turn_correlation_id: finalEnd.correlation_id || null,
    tts_correlation_available: tts.some(item => Boolean(item.correlation_id)),
    hardware_audibility_verified: false
  };
})"""


# Selectors differ between the 2D control panel ('/') and the main /app scene.
SELECTORS = {
    "control": {"send": "#send", "mic": "#mic", "messages": "#messages .message",
                "mic_status": "#mic-status", "mic_gate": "#mic-gate-state", "url_suffix": "/"},
    "app": {"send": "#chat-send", "mic": "#chat-mic", "messages": "#chat-log .msg",
            "mic_status": "#mic-state", "mic_gate": "#mic-gate-state", "url_suffix": ""},
}


def _driver_options(Options, wav: Path, ui: str = "control"):
    options = Options()
    options.add_argument("--headless=new")
    if ui == "app":
        # /app renders the VRM scene with WebGL; SwiftShader keeps it available headless.
        options.add_argument("--enable-unsafe-swiftshader")
        options.add_argument("--use-angle=swiftshader")
    else:
        options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--autoplay-policy=no-user-gesture-required")
    options.add_argument("--use-fake-ui-for-media-stream")
    options.add_argument("--use-fake-device-for-media-stream")
    # Chromium otherwise loops the file, creating another user turn during a
    # long model/TTS wait. Single-pass input is essential for correlation.
    options.add_argument(f"--use-file-for-fake-audio-capture={wav.resolve()}%noloop")
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
    parser.add_argument("--ui", choices=sorted(SELECTORS), default="control",
                        help="control = 2D web panel at '/'; app = main /app scene with VRM")
    parser.add_argument("--require-draft-preview", action="store_true",
                        help="fail acceptance unless /app shows a correlated streaming draft preview")
    args = parser.parse_args()
    try:
        _validate_draft_preview_ui(args.ui, args.require_draft_preview)
    except ValueError as exc:
        report = {
            "schema_version": 2, "profile": "browser_voice_e2e", "status": "refused",
            "mode": "real_browser_capture", "url": args.url, "turns": [],
            "screenshots": [], "failure": str(exc),
        }
        return _write(args, report, 2)
    try:
        target_url = _normalize_target_url(args.url, args.ui)
    except ValueError as exc:
        report = {
            "schema_version": 2, "profile": "browser_voice_e2e", "status": "refused",
            "mode": "real_browser_capture", "url": "[rejected]", "turns": [],
            "screenshots": [], "failure": str(exc),
        }
        return _write(args, report, 2)
    report = {
        "schema_version": 2,
        "profile": "browser_voice_e2e",
        "status": "refused",
        "mode": "real_browser_capture",
        "url": target_url,
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
            if duration <= 0 or duration > 300:
                raise ValueError(f"{path.name}: duration must be between 0 and 300 seconds")
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
    sel = SELECTORS[args.ui]
    try:
        for index, (wav_path, expected, duration) in enumerate(
            zip(args.wav, args.expected, durations), 1
        ):
            driver = None
            phase = "create_browser"
            try:
                driver = webdriver.Edge(options=_driver_options(Options, wav_path, args.ui))
                driver.set_page_load_timeout(30)
                phase = "load_companion_page"
                driver.get(target_url)
                _validate_navigation_url(driver.current_url, target_url)
                wait = WebDriverWait(driver, args.response_timeout)
                phase = "wait_chat_controls"
                wait.until(lambda d: d.find_element(By.CSS_SELECTOR, sel["send"]).is_displayed())
                driver.execute_script(_INSTALL_OBSERVABILITY)
                driver.execute_script("window.__voiceE2E.turn_started_ms = performance.now()")
                baseline = driver.execute_script(
                    "return document.querySelectorAll('" + sel["messages"] + "').length"
                )

                phase = "start_microphone"
                driver.find_element(By.CSS_SELECTOR, sel["mic"]).click()
                phase = "wait_get_user_media"
                wait.until(lambda d: d.execute_script(
                    "return window.__voiceE2E && window.__voiceE2E.get_user_media > 0"
                ))
                if args.ui == "app":
                    # /app finalizes on its own silence endpoint and reports it through the
                    # fetch waits below; a fixed sleep would land after the fake device's
                    # loop restart and open a second utterance. Stay event-driven.
                    # Sample the mic-status element to capture the transient draft preview.
                    driver.execute_script(
                        "window.__voiceE2E.draft_dom_samples = [];"
                        "window.__voiceE2E._draftDomTimer = setInterval(() => {"
                        "  const el = document.querySelector('" + sel["mic_status"] + "');"
                        "  const text = el ? (el.textContent || '').trim() : '';"
                        "  window.__voiceE2E.draft_dom_samples.push({t: performance.now(), text});"
                        "  if (window.__voiceE2E.draft_dom_samples.length > 300)"
                        "    window.__voiceE2E.draft_dom_samples.shift();"
                        "}, 350);"
                    )
                else:
                    # Let the real fake capture feed the AudioWorklet. The extra
                    # tail gives the application's upload queue time to flush.
                    phase = "capture_audio"
                    time.sleep(duration + 0.8)
                    phase = "stop_microphone"
                    driver.find_element(By.CSS_SELECTOR, sel["mic"]).click()
                phase = "wait_voice_message"
                wait.until(lambda d: d.execute_script(
                    "return document.querySelectorAll('" + sel["messages"] + "').length > arguments[0]",
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
                # A turn passes only after its current-turn TTS sources finish
                # with measurable, non-silent audio. A start/play attempt is not enough.
                phase = "wait_tts_playback"
                wait.until(lambda d: d.execute_script(
                    "return (" + _PLAYBACK_EVIDENCE + ")(window.__voiceE2E).settled"
                ))

                phase = "collect_turn"
                collect_js = _COLLECT_RESULT
                if args.ui == "app":
                    # /app renders role as a CSS class on .msg nodes, not as a text label.
                    collect_js = collect_js.replace(
                        "  const messages = [...document.querySelectorAll('#messages .message')].slice(baseline)\n"
                        "    .map(item => item.innerText || '');\n"
                        "  const companion = messages.filter(item => /Companion|Компаньон/i.test(item)).join('\\n');",
                        "  const nodes = [...document.querySelectorAll('" + sel["messages"] + "')].slice(baseline);\n"
                        "  const messages = nodes.map(item => item.innerText || '');\n"
                        "  const companion = nodes.filter(item => item.classList.contains('assistant'))\n"
                        "    .map(item => item.innerText || '').join('\\n');",
                    )
                    if "classList.contains('assistant')" not in collect_js:
                        raise RuntimeError("app collect replacement did not apply")
                else:
                    collect_js = collect_js.replace("'#messages .message'", repr(sel["messages"]))
                collect_js = collect_js.replace(
                    "const playbackEvidence = null;",
                    "const playbackEvidence = (" + _PLAYBACK_EVIDENCE + ")(state);",
                )
                result = driver.execute_script(collect_js, baseline, expected)
                if args.ui == "app":
                    draft_dom = driver.execute_script(
                        "return window.__voiceE2E?.draft_dom_samples || []"
                    )
                    draft_fetch = driver.execute_script(
                        "return (window.__voiceE2E?.fetches || []).filter(f => f.path === '/api/voice/draft')"
                        ".map(f => ({status: f.status, mode: f.draft_mode || null, draft: f.draft || '',"
                        " ok: f.draft_ok === true,"
                        " session_id: f.session_id || null, correlation_id: f.correlation_id || null,"
                        " started_ms: f.started_ms, ended_ms: f.ended_ms, error: f.error || null}))"
                    )
                    matching_session = result["session_ids"][0] if len(result["session_ids"]) == 1 else None
                    result["draft_lane"] = _classify_draft_preview(
                        draft_dom, draft_fetch,
                        session_id=matching_session,
                        correlation_id=result.get("end_correlation_id"),
                        voice_end_ms=result.get("voice_end_ended_ms"),
                    )
                    result["draft_lane"]["fetches"] = draft_fetch
                else:
                    result["draft_lane"] = {
                        "observed": False,
                        "failure": "not_observed_on_control_ui",
                    }
                _apply_draft_preview_acceptance(result, args.require_draft_preview)
                screenshot = args.evidence_dir / f"browser-voice-{index}.png"
                driver.save_screenshot(str(screenshot))
                if args.ui == "app":
                    # A successful /app turn leaves the mic armed; stop it so the capture
                    # lease is released before the next turn starts (otherwise capture_busy).
                    driver.find_element(By.CSS_SELECTOR, sel["mic"]).click()
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
                                "const s = window.__voiceE2E; if (!s) return null; "
                                "return {...s, playback: (s.playback || []).map("
                                "({element, cleanup_energy, energy_timer, ...row}) => row)};"
                            ),
                            "mic_status": driver.execute_script(
                                "return document.querySelector('" + sel["mic_status"] + "')?.textContent || ''"
                            ),
                            "gate_status": driver.execute_script(
                                "return document.querySelector('" + sel["mic_gate"] + "')?.textContent || ''"
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
    playback: [],
    buffer_source_start_ms: [], turn_started_ms: null,
    worklet_chunks: 0, last_rms: 0, last_gate_open: false,
    capture_diagnostics: []
  };
  const captureReasons = new Set([
    'upload_backpressure', 'http_failure', 'transport_failure', 'upload_failure'
  ]);
  const errorNames = new Set([
    'AbortError', 'Error', 'InvalidStateError', 'NetworkError', 'NotAllowedError',
    'NotReadableError', 'OperationError', 'QuotaExceededError', 'SecurityError',
    'TimeoutError', 'TypeError', 'UnknownError', 'unknown'
  ]);
  const contextStates = new Set(['running', 'suspended', 'closed', 'unknown']);
  const trackStates = new Set(['live', 'ended', 'unknown']);
  const captureDiagnostic = event => {
    const detail = event?.detail;
    if (!detail || typeof detail !== 'object' || Array.isArray(detail)
        || detail.schema_version !== 1 || !captureReasons.has(detail.reason)
        || !(detail.error_name === null || errorNames.has(detail.error_name))
        || !(detail.status === null || (Number.isInteger(detail.status)
          && detail.status >= 100 && detail.status <= 599))
        || !contextStates.has(detail.context_state)
        || !Array.isArray(detail.track_states) || detail.track_states.length > 4
        || detail.track_states.some(value => !trackStates.has(value))
        || !Number.isInteger(detail.upload_pending) || detail.upload_pending < 0
        || detail.upload_pending > 6
        || !Number.isSafeInteger(detail.worklet_chunks) || detail.worklet_chunks < 0
        || !(detail.last_frame_age_ms === null || (Number.isFinite(detail.last_frame_age_ms)
          && detail.last_frame_age_ms >= 0 && detail.last_frame_age_ms <= 86400000))
        || typeof detail.active !== 'boolean' || typeof detail.finalizing !== 'boolean') return;
    state.capture_diagnostics.push({
      schema_version: 1,
      reason: detail.reason,
      error_name: detail.error_name,
      status: detail.status,
      context_state: detail.context_state,
      track_states: detail.track_states.slice(0, 4),
      upload_pending: detail.upload_pending,
      worklet_chunks: detail.worklet_chunks,
      last_frame_age_ms: detail.last_frame_age_ms,
      active: detail.active,
      finalizing: detail.finalizing
    });
    if (state.capture_diagnostics.length > 20) state.capture_diagnostics.shift();
  };
  window.addEventListener('jawl-voice-capture', captureDiagnostic);
  const currentTurn = started => Number.isFinite(state.turn_started_ms) && started >= state.turn_started_ms;
  const bufferLevel = buffer => {
    let sum = 0, count = 0, peak = 0;
    if (!buffer || typeof buffer.getChannelData !== 'function') return {rms: 0, peak: 0};
    for (let channel = 0; channel < (buffer.numberOfChannels || 0); channel++) {
      const samples = buffer.getChannelData(channel);
      const stride = Math.max(1, Math.ceil(samples.length / 4096));
      for (let i = 0; i < samples.length; i += stride) {
        const value = Number(samples[i]) || 0;
        sum += value * value; count += 1; peak = Math.max(peak, Math.abs(value));
      }
    }
    return {rms: count ? Math.sqrt(sum / count) : 0, peak};
  };
  const watchMediaEnergy = record => {
    const element = record.element;
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!element || typeof element.captureStream !== 'function' || !AudioContextCtor) return;
    try {
      const context = new AudioContextCtor();
      const source = context.createMediaStreamSource(element.captureStream());
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const samples = new Float32Array(analyser.fftSize);
      record.media_energy_available = true;
      record.media_rms = 0;
      record.energy_timer = window.setInterval(() => {
        try {
          analyser.getFloatTimeDomainData(samples);
          let sum = 0;
          for (const value of samples) sum += value * value;
          record.media_rms = Math.max(record.media_rms, Math.sqrt(sum / samples.length));
        } catch (_) {}
      }, 50);
      record.cleanup_energy = () => {
        window.clearInterval(record.energy_timer);
        try { source.disconnect(); } catch (_) {}
        try { context.close(); } catch (_) {}
      };
    } catch (_) { record.media_energy_available = false; }
  };
  const nativeFetch = window.fetch.bind(window);
  const observeTtsBody = (response, item) => {
    const markEof = () => { item.body_eof = true; item.body_ended_ms = performance.now(); };
    const markError = error => {
      item.body_error = error?.name || 'body_read_error';
      item.body_error_ms = performance.now();
    };
    const stream = response.body;
    if (stream && typeof stream.getReader === 'function') {
      try {
        const nativeGetReader = stream.getReader.bind(stream);
        stream.getReader = (...args) => {
          const reader = nativeGetReader(...args);
          const nativeRead = reader.read.bind(reader);
          reader.read = (...readArgs) => nativeRead(...readArgs).then(result => {
            if (result?.done) markEof();
            return result;
          }, error => { markError(error); throw error; });
          const nativeCancel = reader.cancel?.bind(reader);
          if (nativeCancel) reader.cancel = (...cancelArgs) => {
            item.body_cancelled = true;
            item.body_cancelled_ms = performance.now();
            return nativeCancel(...cancelArgs);
          };
          return reader;
        };
      } catch (_) { item.body_observation_error = 'reader_wrapper_unavailable'; }
    }
    for (const method of ['blob', 'arrayBuffer', 'text', 'json', 'formData']) {
      const nativeConsume = response[method];
      if (typeof nativeConsume !== 'function') continue;
      try {
        response[method] = function(...args) {
          return nativeConsume.apply(this, args).then(value => { markEof(); return value; }, error => {
            markError(error); throw error;
          });
        };
      } catch (_) { item.body_observation_error = 'consumer_wrapper_unavailable'; }
    }
  };
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
      if (path === '/api/tts/stream' || path === '/api/tts/synthesize') {
        observeTtsBody(response, item);
      }
      if (path === '/api/voice/end') {
        response.clone().json().then(data => {
          item.transcript = typeof data.transcript === 'string' ? data.transcript : '';
          item.mode = data.mode || null;
          item.response_ok = data.ok === true;
          item.response_count = Array.isArray(data.responses) ? data.responses.length : 0;
          item.event_types = Array.isArray(data.events) ? data.events.map(event => event.type) : [];
        }).catch(() => { item.response_parse_error = true; });
      }
      if (path === '/api/voice/draft') {
        response.clone().json().then(data => {
          item.draft_mode = data.mode || null;
          item.draft = typeof data.draft === 'string' ? data.draft.slice(0, 4000) : '';
          item.draft_ok = data.ok === true;
          item.draft_response_ms = performance.now();
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
    const record = {
      kind: 'media', started_ms: performance.now(), ended_ms: null,
      current_turn: currentTurn(performance.now()), play_resolved: false,
      completed: false, non_silent: false, error: null, element: this
    };
    state.playback.push(record);
    watchMediaEnergy(record);
    const finish = (event, error) => {
      if (record.ended_ms !== null) return;
      record.ended_ms = performance.now();
      record.duration_seconds = Number.isFinite(this.duration) ? this.duration : null;
      record.current_time_seconds = Number.isFinite(this.currentTime) ? this.currentTime : null;
      record.error = error || null;
      record.non_silent = record.media_energy_available === true && record.media_rms > 0.00001;
      record.completed = !record.error && record.play_resolved &&
        record.duration_seconds > 0 &&
        record.current_time_seconds >= Math.max(0.02, record.duration_seconds * 0.9) &&
        record.non_silent;
      record.interrupted = !record.error && !record.completed;
      record.element = null;
      record.cleanup_energy?.();
    };
    this.addEventListener('ended', event => finish(event, null), {once: true});
    this.addEventListener('error', event => finish(event, 'media_error'), {once: true});
    let promise;
    try { promise = nativePlay.apply(this, args); }
    catch (error) { record.error = error?.name || 'play_error'; record.ended_ms = performance.now(); throw error; }
    if (promise && typeof promise.then === 'function') {
      promise.then(() => { record.play_resolved = true; }, error => {
        record.error = error?.name || 'play_rejected';
        record.ended_ms = performance.now();
        record.cleanup_energy?.();
      });
    }
    return promise;
  };
  const sourceRecords = new WeakMap();
  const nativeStart = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function(...args) {
    const started = performance.now();
    state.buffer_source_starts += 1;
    state.buffer_source_start_ms.push(started);
    const buffer = this.buffer;
    const energy = bufferLevel(buffer);
    const contextTime = Number(this.context?.currentTime) || 0;
    const scheduledDelay = Number.isFinite(args[0]) ? Math.max(0, args[0] - contextTime) : 0;
    const offset = Number.isFinite(args[1]) ? Math.max(0, args[1]) : 0;
    const audioDuration = Number.isFinite(args[2]) ? Math.max(0, args[2])
      : Math.max(0, (Number(buffer?.duration) || 0) - offset);
    const playbackRate = Number(this.playbackRate?.value);
    const detune = Number(this.detune?.value);
    const rateKnown = Number.isFinite(playbackRate) && playbackRate > 0 && Number.isFinite(detune);
    const effectiveRate = rateKnown ? playbackRate * Math.pow(2, detune / 1200) : NaN;
    const startContextTime = contextTime + scheduledDelay;
    const expectedContextDuration = rateKnown && effectiveRate > 0 ? audioDuration / effectiveRate : null;
    const expectedContextEnd = expectedContextDuration === null ? null : startContextTime + expectedContextDuration;
    const record = {
      kind: 'buffer_source', started_ms: started, ended_ms: null,
      current_turn: currentTurn(started), duration_seconds: audioDuration,
      scheduled_delay_seconds: scheduledDelay, scheduled_duration_ms: audioDuration * 1000,
      timing_unknown: !rateKnown, playback_rate: rateKnown ? playbackRate : null,
      detune_cents: rateKnown ? detune : null,
      start_context_time: startContextTime, expected_context_end: expectedContextEnd,
      rms: energy.rms, peak: energy.peak,
      non_silent: energy.rms > 0.00001 && energy.peak > 0.0001,
      completed: false, interrupted: false, error: null
    };
    state.playback.push(record);
    sourceRecords.set(this, record);
    const priorEnded = this.onended;
    this.onended = function(event) {
      record.ended_ms = performance.now();
      const elapsed = record.ended_ms - record.started_ms;
      record.elapsed_ms = elapsed;
      record.ended_context_time = Number(this.context?.currentTime);
      const endTolerance = Math.min(60, Math.max(20, audioDuration * 100));
      const contextTolerance = Math.min(0.06, Math.max(0.02, (expectedContextDuration || 0) * 0.1));
      const contextReachedEnd = Number.isFinite(record.ended_context_time) &&
        expectedContextEnd !== null && record.ended_context_time + contextTolerance >= expectedContextEnd;
      const wallReachedEnd = elapsed + endTolerance >= scheduledDelay * 1000 + audioDuration * 1000;
      record.completed = !record.timing_unknown && !record.stopped_early && record.non_silent &&
        audioDuration > 0 && wallReachedEnd && contextReachedEnd;
      record.interrupted = !record.completed;
      try { if (typeof priorEnded === 'function') priorEnded.call(this, event); }
      finally { this.onended = priorEnded; }
    };
    try { return nativeStart.apply(this, args); }
    catch (error) {
      record.error = error?.name || 'source_start_error';
      record.ended_ms = performance.now();
      throw error;
    }
  };
  const nativeStop = AudioBufferSourceNode.prototype.stop;
  if (typeof nativeStop === 'function') {
    AudioBufferSourceNode.prototype.stop = function(...args) {
      const record = sourceRecords.get(this);
      if (record && record.ended_ms === null) {
        const contextNow = Number(this.context?.currentTime);
        const requested = Number.isFinite(args[0]) && Number.isFinite(contextNow)
          ? Math.max(contextNow, args[0]) : contextNow;
        record.stop_requested_ms = performance.now();
        record.stop_context_time = Number.isFinite(requested) ? requested : null;
        record.stopped_early = record.expected_context_end === null ||
          !Number.isFinite(requested) || requested + 0.02 < record.expected_context_end;
        if (record.stopped_early) record.interrupt_reason = 'source_stopped_before_scheduled_end';
      }
      return nativeStop.apply(this, args);
    };
  }
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
  const playbackEvidence = null;
  const playback = playbackEvidence.playback;
  const playbackDuration = playbackEvidence.playback_duration_seconds;
  const playbackFailure = playbackEvidence.failure;
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
    : playbackFailure;
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
    buffer_source_scheduled_count: state.buffer_source_starts || 0,
    playback_evidence: playback.map(({element, cleanup_energy, energy_timer, ...item}) => item),
    playback_completed_nonsilent_seconds: Math.round(playbackDuration * 1000) / 1000,
    playback_failure: playbackFailure,
    playback_evidence_method: playbackEvidence.method,
    playback_rate_basis: playbackEvidence.playback_rate_basis,
    playback_turn_correlation_id: playbackEvidence.turn_correlation_id,
    tts_correlation_available: playbackEvidence.tts_correlation_available,
    hardware_audibility_verified: playbackEvidence.hardware_audibility_verified,
    tts_response_bodies_reached_eof: playbackEvidence.body_ok,
    user_signal_active: document.querySelector('#user-signal')?.classList.contains('active') || false,
    companion_signal_active: document.querySelector('#companion-signal')?.classList.contains('active') || false,
    voice_end_mode: finalEnd.mode || null,
    voice_end_ended_ms: Number.isFinite(finalEnd.ended_ms) ? finalEnd.ended_ms : null,
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
