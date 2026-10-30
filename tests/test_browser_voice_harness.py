"""Focused URL and browser-playback evidence tests for the live voice harness."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts" / "run_browser_voice_e2e.py"
sys.dont_write_bytecode = True
_SPEC = importlib.util.spec_from_file_location("browser_voice_harness", HARNESS_PATH)
HARNESS = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(HARNESS)


class BrowserVoiceUrlTests(unittest.TestCase):
    def test_fake_audio_plays_once_even_if_model_wait_exceeds_wav_duration(self):
        class Options:
            def __init__(self):
                self.arguments = []

            def add_argument(self, value):
                self.arguments.append(value)

        wav = ROOT / 'runtime' / 'synthetic-questions' / 'question-02-pad150.wav'
        options = HARNESS._driver_options(Options, wav, 'app')
        capture = [arg for arg in options.arguments if arg.startswith('--use-file-for-fake-audio-capture=')]
        self.assertEqual(capture, [f'--use-file-for-fake-audio-capture={wav.resolve()}%noloop'])

    def test_app_uses_app_at_origin_root_and_preserves_explicit_app_path(self):
        self.assertEqual(
            HARNESS._normalize_target_url("http://127.0.0.1:2367", "app"),
            "http://127.0.0.1:2367/app",
        )
        self.assertEqual(
            HARNESS._normalize_target_url("http://localhost:2367/app/", "app"),
            "http://localhost:2367/app",
        )
        self.assertEqual(
            HARNESS._normalize_target_url("http://localhost:2367/custom/app", "app"),
            "http://localhost:2367/custom/app",
        )

    def test_control_root_and_explicit_path_are_preserved(self):
        self.assertEqual(
            HARNESS._normalize_target_url("http://127.0.0.1:2367", "control"),
            "http://127.0.0.1:2367/",
        )
        self.assertEqual(
            HARNESS._normalize_target_url("http://127.0.0.1:2367/custom", "control"),
            "http://127.0.0.1:2367/custom",
        )

    def test_foreign_hosts_and_embedded_auth_are_refused(self):
        for url in (
            "https://example.com/app",
            "http://user:secret@127.0.0.1:2367/app",
            "http://127.0.0.1:2367/app?token=unexpected",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                HARNESS._normalize_target_url(url, "app")

    def test_navigation_redirect_or_auth_query_is_refused(self):
        expected = "http://127.0.0.1:2367/app"
        HARNESS._validate_navigation_url(expected, expected)
        for actual in (
            "http://127.0.0.1:2367/login",
            "https://example.com/app",
            "http://127.0.0.1:2367/app?token=unexpected",
        ):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                HARNESS._validate_navigation_url(actual, expected)


class BrowserVoiceDraftPreviewTests(unittest.TestCase):
    SESSION = "session-1"
    CORRELATION = "turn-1"

    def fetch(self, **overrides):
        row = {
            "status": 200, "ok": True, "mode": "streaming", "draft": "проверка черновика",
            "session_id": self.SESSION, "correlation_id": self.CORRELATION,
            "started_ms": 100, "ended_ms": 150,
        }
        row.update(overrides)
        return row

    def classify(self, samples, fetches=None, **overrides):
        values = {
            "session_id": self.SESSION,
            "correlation_id": self.CORRELATION,
            "voice_end_ms": 500,
        }
        values.update(overrides)
        return HARNESS._classify_draft_preview(
            samples, [self.fetch()] if fetches is None else fetches, **values
        )

    def test_correlated_streamed_preview_and_post_end_clear_pass(self):
        result = self.classify([
            {"t": 300, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "проверка черновика"},
            {"t": 600, "text": "Слушаю…"},
        ])
        self.assertIsNone(result["failure"])
        self.assertEqual(result["preview_sample_count"], 1)
        self.assertTrue(result["cleared_after_end"])

    def test_status_text_is_not_a_preview(self):
        result = self.classify([{"t": 300, "text": "Слушаю…"}, {"t": 600, "text": ""}])
        self.assertEqual(result["failure"], "draft_preview_not_seen")

    def test_empty_prefixed_preview_is_not_content(self):
        result = self.classify([
            {"t": 300, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "  "},
            {"t": 600, "text": ""},
        ])
        self.assertEqual(result["failure"], "draft_preview_not_seen")

    def test_unavailable_lane_is_reported_without_fabricating_preview(self):
        result = self.classify([], [self.fetch(status=503, mode="unavailable", draft="")])
        self.assertEqual(result["failure"], "draft_lane_unavailable")

    def test_preview_content_over_160_characters_fails(self):
        result = self.classify([
            {"t": 300, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "я" * 161},
            {"t": 600, "text": ""},
        ])
        self.assertEqual(result["failure"], "draft_preview_content_over_160")

    def test_preview_content_at_160_characters_is_allowed(self):
        content = "я" * 160
        result = self.classify([
            {"t": 300, "text": HARNESS._DRAFT_PREVIEW_PREFIX + content},
            {"t": 600, "text": ""},
        ], [self.fetch(draft=content)])
        self.assertIsNone(result["failure"])
        self.assertEqual(result["preview_max_content_len"], 160)

    def test_empty_streaming_response_does_not_satisfy_draft_evidence(self):
        result = self.classify([], [self.fetch(draft="")])
        self.assertEqual(result["failure"], "streamed_draft_empty")

    def test_preview_must_clear_after_correlated_voice_end(self):
        result = self.classify([
            {"t": 300, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "проверка черновика"},
        ])
        self.assertEqual(result["failure"], "draft_preview_not_cleared_after_voice_end")

    def test_late_preview_reappearance_fails_even_after_clear_sample(self):
        result = self.classify([
            {"t": 300, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "проверка черновика"},
            {"t": 510, "text": "Слушаю…"},
            {"t": 550, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "старый текст"},
        ])
        self.assertEqual(result["failure"], "draft_preview_present_after_voice_end")
        self.assertTrue(result["preview_after_end"])
        self.assertFalse(result["cleared_after_end"])

    def test_oversized_preview_fails_even_when_another_sample_is_in_bounds(self):
        result = self.classify([
            {"t": 300, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "проверка черновика"},
            {"t": 350, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "я" * 161},
            {"t": 600, "text": ""},
        ])
        self.assertEqual(result["failure"], "draft_preview_content_over_160")
        self.assertEqual(result["preview_sample_count"], 1)
        self.assertEqual(result["preview_max_content_len"], 161)

    def test_preview_raw_content_length_is_checked_before_trimming(self):
        result = self.classify([
            {"t": 300, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "x" * 160 + " "},
            {"t": 600, "text": ""},
        ])
        self.assertEqual(result["failure"], "draft_preview_content_over_160")

    def test_stale_dom_and_wrong_correlation_are_rejected(self):
        stale_dom = self.classify([
            {"t": 300, "text": ""},
            {"t": 600, "text": HARNESS._DRAFT_PREVIEW_PREFIX + "проверка черновика"},
        ])
        self.assertEqual(stale_dom["failure"], "draft_preview_present_after_voice_end")
        wrong_correlation = self.classify(
            [], [self.fetch(correlation_id="old-turn")]
        )
        self.assertEqual(wrong_correlation["failure"], "no_successful_scoped_streaming_draft")

    def test_false_json_success_does_not_count_as_a_streamed_draft(self):
        result = self.classify(
            [], [self.fetch(ok=False)]
        )
        self.assertEqual(result["failure"], "no_successful_scoped_streaming_draft")

    def test_strict_preview_flag_requires_app_ui(self):
        with self.assertRaisesRegex(ValueError, "require_draft_preview_requires_app_ui"):
            HARNESS._validate_draft_preview_ui("control", True)
        HARNESS._validate_draft_preview_ui("app", True)

    def test_strict_failure_fails_turn_but_optional_unavailable_is_telemetry(self):
        strict = {"ok": True, "failure": None,
                  "draft_lane": {"failure": "draft_lane_unavailable"}}
        HARNESS._apply_draft_preview_acceptance(strict, True)
        self.assertFalse(strict["ok"])
        self.assertEqual(strict["failure"],
                         "required_draft_preview_failed:draft_lane_unavailable")

        optional = {"ok": True, "failure": None,
                    "draft_lane": {"failure": "draft_lane_unavailable"}}
        HARNESS._apply_draft_preview_acceptance(optional, False)
        self.assertTrue(optional["ok"])
        self.assertEqual(optional["draft_lane"]["failure"], "draft_lane_unavailable")

    def test_require_flag_rejects_control_ui_before_browser_setup(self):
        with patch.object(sys, "argv", [
            str(HARNESS_PATH), "--wav", "unused.wav", "--expected", "text",
            "--require-draft-preview", "--ui", "control",
        ]), patch.object(HARNESS, "_write", return_value=2) as write_report:
            self.assertEqual(HARNESS.main(), 2)
        self.assertEqual(write_report.call_args.args[1]["failure"],
                         "require_draft_preview_requires_app_ui")


@unittest.skipUnless(shutil.which("node"), "Node.js is required for controlled browser-JS tests")
class BrowserVoiceCaptureDiagnosticsTests(unittest.TestCase):
    def test_capture_event_is_allowlisted_redacted_and_bounded(self):
        setup = r"""
const vm = require('node:vm');
const listeners = {};
globalThis.window = globalThis;
globalThis.addEventListener = (name, callback) => { (listeners[name] ||= []).push(callback); };
globalThis.dispatchEvent = event => { for (const callback of listeners[event.type] || []) callback(event); };
globalThis.performance = {now: () => 10};
globalThis.navigator = {mediaDevices: {}};
globalThis.location = {href: 'http://127.0.0.1:2367/app'};
globalThis.fetch = async () => ({status: 200});
globalThis.HTMLMediaElement = class {
  addEventListener() {}
  play() { return Promise.resolve(); }
};
globalThis.AudioBufferSourceNode = class {
  constructor() { this.context = {currentTime: 0}; this.playbackRate = {value: 1};
    this.detune = {value: 0}; this.onended = null; this.buffer = null; }
  start() {}
  stop() {}
};
vm.runInThisContext(__INSTALL__);
const send = detail => window.dispatchEvent({type: 'jawl-voice-capture', detail});
const safe = index => ({
  schema_version: 1, reason: 'upload_failure', error_name: 'TypeError', status: 502,
  context_state: 'suspended', track_states: ['live', 'ended', 'unknown', 'live'],
  upload_pending: 6, worklet_chunks: index, last_frame_age_ms: 12.5,
  active: true, finalizing: false,
  transcript: 'PRIVATE_TRANSCRIPT', url: 'https://private.invalid/path?token=SECRET',
  error: {message: 'PRIVATE_ERROR_MESSAGE'}, token: 'PRIVATE_TOKEN',
  session_id: 'PRIVATE_SESSION_ID', correlation_id: 'PRIVATE_CORRELATION_ID'
});
for (let index = 0; index < 25; index++) send(safe(index));
if (window.__voiceE2E.capture_diagnostics.length !== 20)
  throw new Error('capture diagnostic ring did not stay capped at 20');
if (window.__voiceE2E.capture_diagnostics[0].worklet_chunks !== 5
    || window.__voiceE2E.capture_diagnostics.at(-1).worklet_chunks !== 24)
  throw new Error('capture diagnostic ring did not retain the newest entries');
const row = window.__voiceE2E.capture_diagnostics.at(-1);
const keys = Object.keys(row).sort().join(',');
const expected = ['active', 'context_state', 'error_name', 'finalizing', 'last_frame_age_ms',
  'reason', 'schema_version', 'status', 'track_states', 'upload_pending', 'worklet_chunks'].sort().join(',');
if (keys !== expected) throw new Error(`unexpected captured fields: ${keys}`);
const serialized = JSON.stringify(window.__voiceE2E.capture_diagnostics);
for (const secret of ['PRIVATE_TRANSCRIPT', 'private.invalid', 'PRIVATE_ERROR_MESSAGE',
    'PRIVATE_TOKEN', 'PRIVATE_SESSION_ID', 'PRIVATE_CORRELATION_ID']) {
  if (serialized.includes(secret)) throw new Error(`sensitive field leaked: ${secret}`);
}
const before = window.__voiceE2E.capture_diagnostics.length;
send({...safe(77), error_name: 'unknown'});
if (window.__voiceE2E.capture_diagnostics.at(-1).error_name !== 'unknown')
  throw new Error('app sanitized unknown error class was lost');
send({...safe(99), reason: 'unrecognized_reason'});
send({...safe(99), error_name: 'UntrustedException'});
send({...safe(99), status: 200.5});
send({...safe(99), track_states: ['live', 'ended', 'unknown', 'live', 'ended']});
if (window.__voiceE2E.capture_diagnostics.length !== before)
  throw new Error('malformed diagnostic event was accepted');
""".replace("__INSTALL__", json.dumps(HARNESS._INSTALL_OBSERVABILITY))
        result = subprocess.run(
            [shutil.which("node"), "-e", setup],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js is required for controlled browser-JS tests")
class BrowserVoicePlaybackTests(unittest.TestCase):
    def test_full_audio_passes_and_rejection_truncation_silence_fail(self):
        setup = r"""
const vm = require('node:vm');
let now = 0;
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.performance = {now: () => now};
globalThis.navigator = {mediaDevices: {}};
globalThis.location = {href: 'http://127.0.0.1:2367/app'};
let resolveRead;
const fakeTtsStream = {
  getReader() { return {read() { return new Promise(resolve => { resolveRead = resolve; }); }}; }
};
globalThis.fetch = async () => ({status: 200, body: fakeTtsStream});
globalThis.HTMLMediaElement = class {
  constructor() { this.listeners = {}; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  play() { return Promise.reject(Object.assign(new Error('blocked'), {name: 'NotAllowedError'})); }
};
globalThis.AudioBufferSourceNode = class {
  constructor(buffer) {
    this.buffer = buffer; this.context = {currentTime: 0};
    this.playbackRate = {value: 1}; this.detune = {value: 0}; this.onended = null;
  }
  start() {}
  stop() {}
};
const sourceText = __INSTALL__;
vm.runInThisContext(sourceText);
window.__voiceE2E.turn_started_ms = 0;
const makeBuffer = (duration, sample) => ({
  duration, numberOfChannels: 1,
  getChannelData: () => new Float32Array(2048).fill(sample)
});
function playBuffer(duration, sample, elapsed) {
  now = 40;
  const source = new AudioBufferSourceNode(makeBuffer(duration, sample));
  let priorEndedCalls = 0;
  source.onended = () => { priorEndedCalls += 1; };
  source.start(0);
  now += elapsed;
  source.context.currentTime += elapsed / 1000;
  source.onended({type: 'ended'});
  return {record: window.__voiceE2E.playback.at(-1), priorEndedCalls,
    handlerRestored: typeof source.onended === 'function'};
}
""".replace("__INSTALL__", json.dumps(HARNESS._INSTALL_OBSERVABILITY))
        collect = r"""
const collect = new Function('baseline', 'expected', __COLLECT__.replace(
  'const playbackEvidence = null;',
  'const playbackEvidence = (' + __EVIDENCE__ + ')(state);'));
const summarize = new Function('state', 'return (' + __EVIDENCE__ + ')(state);');
function collectResult(playback) {
  now = 2000;
  window.__voiceE2E.fetches = [
    {path: '/api/voice/audio', session_id: 's1', correlation_id: 'c1'},
    {path: '/api/voice/end', started_ms: 10, ended_ms: 30, session_id: 's1',
      correlation_id: 'c1', transcript: 'проверка', response_ok: true,
      response_count: 1, status: 200},
    {path: '/api/tts/stream', started_ms: 35, ended_ms: 36, status: 200,
      body_eof: true, body_ended_ms: 40}
  ];
  window.__voiceE2E.playback = [playback];
  globalThis.document = {
    querySelectorAll: () => [{innerText: 'Companion: ответ'}],
    querySelector: () => null
  };
  return collect(0, 'проверка');
}
""".replace("__COLLECT__", json.dumps(HARNESS._COLLECT_RESULT)).replace(
            "__EVIDENCE__", json.dumps(HARNESS._PLAYBACK_EVIDENCE))
        cases = r"""
(async () => {
  const full = playBuffer(0.2, 0.1, 230);
  if (!full.record.completed || !full.record.non_silent || full.priorEndedCalls !== 1 || !full.handlerRestored)
    throw new Error('full non-silent playback did not complete or existing onended was not preserved');
  const pass = collectResult(full.record);
  if (!pass.ok) throw new Error(`full playback unexpectedly failed: ${pass.failure}`);

  const short = playBuffer(0.2, 0.1, 20);
  const truncated = collectResult(short.record);
  if (truncated.ok || truncated.failure !== 'tts_playback_interrupted')
    throw new Error(`truncated playback accepted: ${JSON.stringify(truncated)}`);

  const silent = playBuffer(0.2, 0, 230);
  const silentResult = collectResult(silent.record);
  if (silentResult.ok || silentResult.failure !== 'tts_playback_silent')
    throw new Error(`silent playback accepted: ${JSON.stringify(silentResult)}`);

  const empty = playBuffer(0, 0.1, 230);
  const emptyResult = collectResult(empty.record);
  if (emptyResult.ok || emptyResult.failure !== 'tts_playback_interrupted')
    throw new Error(`empty playback accepted: ${JSON.stringify(emptyResult)}`);

  now = 40;
  const stoppedSource = new AudioBufferSourceNode(makeBuffer(0.2, 0.1));
  stoppedSource.start(0);
  stoppedSource.context.currentTime = 0.05;
  stoppedSource.stop();
  now += 500;
  stoppedSource.context.currentTime = 0.5;
  stoppedSource.onended({type: 'ended'});
  const stopped = window.__voiceE2E.playback.at(-1);
  if (stopped.completed || !stopped.stopped_early)
    throw new Error(`early source stop passed after delayed wall-clock callback: ${JSON.stringify(stopped)}`);

  const media = new HTMLMediaElement();
  window.__voiceE2E.turn_started_ms = 0;
  now = 40;
  media.play();
  await Promise.resolve();
  await Promise.resolve();
  const rejected = window.__voiceE2E.playback.at(-1);
  if (!rejected.error || rejected.error !== 'NotAllowedError')
    throw new Error(`rejected media play was not recorded: ${JSON.stringify(rejected)}`);
  const rejectedResult = collectResult(rejected);
  if (rejectedResult.ok || rejectedResult.failure !== 'tts_playback_error')
    throw new Error(`rejected media play accepted: ${JSON.stringify(rejectedResult)}`);

  // The first audio source can end while the producer still has a later chunk.
  // Acceptance stays closed until that same consumer observes body EOF.
  now = 40;
  const response = await window.fetch('/api/tts/stream', {method: 'POST'});
  const ttsRow = window.__voiceE2E.fetches.at(-1);
  const reader = response.body.getReader();
  const firstRead = reader.read();
  resolveRead({done: false, value: new Uint8Array([1])});
  await firstRead;
  window.__voiceE2E.fetches = [
    {path: '/api/voice/end', started_ms: 10, ended_ms: 30}, ttsRow
  ];
  window.__voiceE2E.playback = [{kind: 'buffer_source', current_turn: true,
    started_ms: 40, ended_ms: 300, duration_seconds: 0.2, completed: true,
    non_silent: true, interrupted: false, error: null}];
  now = 1100;
  const openBody = summarize(window.__voiceE2E);
  if (openBody.ready || openBody.settled || openBody.failure !== 'tts_response_body_incomplete')
    throw new Error(`open TTS body accepted after first chunk: ${JSON.stringify(openBody)}`);
  const eofRead = reader.read();
  resolveRead({done: true, value: undefined});
  await eofRead;
  now = 2100;
  const eof = summarize(window.__voiceE2E);
  if (!eof.ready || !eof.body_ok)
    throw new Error(`fully consumed TTS body did not pass: ${JSON.stringify(eof)}`);
})().catch(error => { console.error(error); process.exitCode = 1; });
""".replace("__EVIDENCE__", json.dumps(HARNESS._PLAYBACK_EVIDENCE))
        script = setup + collect + cases
        result = subprocess.run(
            [shutil.which("node"), "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
