"""Accept the desktop app's real streamed speech path with synthetic providers.

This runs Selenium Edge against an in-process loopback Companion server.  The
mock brain and tone WAV provider are deterministic; TTS still passes through
the production /api/tts/stream handler and _stream_tts NDJSON serializer.
Browser instrumentation wraps native fetch, decodeAudioData, and
AudioBufferSourceNode methods without replacing playback or microphone APIs.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import tempfile
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.asr import UtteranceBuffer
from jawl_voicecompanion.voicemem_client import VoiceMemProcessClient


def _tone_wav(frequency: float, duration: float = 0.28) -> bytes:
    sample_rate = 24_000
    count = int(sample_rate * duration)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        samples = bytearray()
        for index in range(count):
            value = int(7_000 * math.sin(2 * math.pi * frequency * index / sample_rate))
            samples.extend(value.to_bytes(2, "little", signed=True))
        wav.writeframes(samples)
    return output.getvalue()


class ProgressiveToneTTS:
    """Three valid WAV chunks, with gates to make first-audio timing provable."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._streams: list[dict[str, object]] = []
        self.first_continue = threading.Event()
        self.first_late_chunk = threading.Event()
        self.scoped_cancels: list[str] = []
        self._tones = [_tone_wav(440), _tone_wav(550), _tone_wav(660)]

    def stream(self, text: str, *, voice=None, speed=1.0, emotion=None, request_id=None):
        del voice, speed, emotion
        with self._lock:
            stream_id = len(self._streams) + 1
            entry: dict[str, object] = {
                "stream_id": stream_id,
                "text": str(text)[:160],
                "request_id": request_id,
                "opened_at": time.monotonic(),
                "yielded_chunks": [],
                "completed": False,
                "closed": False,
                "completed_at": None,
                "closed_at": None,
            }
            self._streams.append(entry)
        try:
            for index, audio in enumerate(self._tones):
                if stream_id == 1 and index == 1 and not self.first_continue.wait(8):
                    raise TimeoutError("first stream continuation gate timed out")
                if stream_id == 1 and index == 2 and not self.first_late_chunk.wait(8):
                    raise TimeoutError("first stream late-chunk gate timed out")
                if stream_id > 1 and index:
                    time.sleep(0.16)
                with self._lock:
                    entry["yielded_chunks"].append({"index": index, "at": time.monotonic()})
                yield audio
            with self._lock:
                entry["completed"] = True
                entry["completed_at"] = time.monotonic()
        finally:
            with self._lock:
                entry["closed"] = True
                entry["closed_at"] = time.monotonic()

    def cancel(self, *, request_id=None) -> None:
        if request_id is not None:
            # Deliberately uncooperative fixture: emit late data to prove the
            # real browser's stale-drop. Service cancellation has separate
            # real TTSService/HTTP tests, not this synthetic tone generator.
            with self._lock:
                self.scoped_cancels.append(request_id)
                self.scoped_cancels[:] = self.scoped_cancels[-32:]
            return
        self.first_continue.set()
        self.first_late_chunk.set()

    def set_governor(self, _governor) -> None:
        # The harness runs outside resource contention and never synthesizes
        # through a model-backed provider.
        return None

    def health(self) -> dict[str, object]:
        return {"status": "ready", "provider": "synthetic_tone_wav"}

    def close(self) -> None:
        self.cancel()

    def release_first_chunk(self) -> None:
        self.first_continue.set()

    def release_late_chunk(self) -> None:
        self.first_late_chunk.set()

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return json.loads(json.dumps(self._streams))

    def cancel_snapshot(self) -> list[str]:
        with self._lock:
            return list(self.scoped_cancels)


def _install_observability() -> str:
    return r"""
(() => {
  const state = window.__desktopVoiceE2E = {
    fetches: [], speech: [], decoded: [], sources: [], active: {},
    overlaps: [], timeline: [], nextTtsId: 0, currentTtsId: 0,
  };
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const input = args[0];
    const url = typeof input === 'string' ? input : input?.url || '';
    const path = new URL(url, location.href).pathname;
    let ttsId = null;
    if (path === '/api/tts/stream') {
      ttsId = ++state.nextTtsId;
      state.currentTtsId = ttsId;
    }
    let payload = null;
    try { payload = typeof args[1]?.body === 'string' ? JSON.parse(args[1].body) : null; } catch {}
    const item = {path, ttsId, startedAt: performance.now(), status: null};
    if (payload && path === '/api/voice/capture') {
      item.action = payload.action;
      item.owner = payload.owner;
      item.capture_id = payload.capture_id;
      item.settings = payload.settings || null;
      item.expected_revision = payload.expected_revision || null;
    } else if (payload && path === '/api/voice/audio') {
      item.owner = payload.owner;
      item.capture_id = payload.capture_id;
      item.session_id = payload.session_id;
      item.pcm16_bytes = Math.floor((payload.pcm16_base64?.length || 0) * 3 / 4);
    } else if (payload && path === '/api/voice/end') {
      item.owner = payload.owner;
      item.capture_id = payload.capture_id;
      item.session_id = payload.session_id;
    }
    const timelineEvent = {kind: 'fetch', path, action: item.action || null, owner: item.owner || null,
      capture_id: item.capture_id || null, startedAt: item.startedAt};
    state.timeline.push(timelineEvent);
    state.fetches.push(item);
    let response;
    try {
      response = await nativeFetch(...args);
    } catch (error) {
      item.error = {
        name: String(error?.name || 'Error').slice(0, 256),
        message: String(error?.message || error || '').slice(0, 256),
      };
      item.failedAt = performance.now();
      timelineEvent.error = item.error;
      timelineEvent.failedAt = item.failedAt;
      throw error;
    }
    item.status = response.status;
    timelineEvent.status = response.status;
    item.headersAt = performance.now();
    if (path === '/api/voice/end') {
      const result = await response.clone().json().catch(() => ({}));
      item.transcript = result.transcript || '';
      item.response_count = Array.isArray(result.responses) ? result.responses.length : 0;
      item.capture_ok = result.ok === true;
    } else if (path === '/api/voice/capture') {
      item.result = await response.clone().json().catch(() => ({}));
    }
    return response;
  };

  const nativeDecode = AudioContext.prototype.decodeAudioData;
  AudioContext.prototype.decodeAudioData = function(...args) {
    const decoded = nativeDecode.apply(this, args);
    if (!decoded?.then) return decoded;
    return decoded.then(buffer => {
      let sum = 0, count = 0;
      for (let channel = 0; channel < buffer.numberOfChannels; channel++) {
        const samples = buffer.getChannelData(channel);
        for (let i = 0; i < samples.length; i++) { sum += samples[i] * samples[i]; count++; }
      }
      state.decoded.push({ttsId: state.currentTtsId, duration: buffer.duration,
        rms: count ? Math.sqrt(sum / count) : 0, at: performance.now()});
      return buffer;
    });
  };

  const records = new WeakMap();
  const finish = (record, reason) => {
    if (!record || !record.active) return;
    record.active = false;
    record.endedAt = performance.now();
    record.endReason = reason;
    state.active[record.ttsId] = Math.max(0, (state.active[record.ttsId] || 1) - 1);
  };
  const nativeCreate = AudioContext.prototype.createBufferSource;
  AudioContext.prototype.createBufferSource = function(...args) {
    const source = nativeCreate.apply(this, args);
    const record = {ttsId: null, active: false, scheduledAt: null, startAt: null};
    records.set(source, record);
    source.addEventListener('ended', () => finish(record, 'ended'), {once: true});
    return source;
  };
  const nativeStart = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function(...args) {
    const record = records.get(this);
    const buffer = this.buffer;
    if (record && buffer) {
      record.ttsId = state.currentTtsId;
      record.startAt = Number(args[0]) || 0;
      record.scheduledAt = performance.now();
      let sum = 0, count = 0;
      for (let channel = 0; channel < buffer.numberOfChannels; channel++) {
        const samples = buffer.getChannelData(channel);
        for (let i = 0; i < samples.length; i++) { sum += samples[i] * samples[i]; count++; }
      }
      record.rms = count ? Math.sqrt(sum / count) : 0;
      record.duration = buffer.duration;
      record.active = true;
      const otherActive = Object.entries(state.active)
        .some(([id, active]) => Number(id) !== record.ttsId && active > 0);
      if (otherActive) state.overlaps.push({ttsId: record.ttsId, at: record.scheduledAt});
      state.active[record.ttsId] = (state.active[record.ttsId] || 0) + 1;
      state.sources.push(record);
    }
    return nativeStart.apply(this, args);
  };
  const nativeStop = AudioBufferSourceNode.prototype.stop;
  AudioBufferSourceNode.prototype.stop = function(...args) {
    const result = nativeStop.apply(this, args);
    finish(records.get(this), 'stop');
    return result;
  };
  window.addEventListener('jawl-speech-state', event => {
    state.speech.push({...event.detail, ttsId: state.currentTtsId, at: performance.now()});
  });
})();
"""


def _inject_synthetic_microphone() -> str:
    """Feed a generated WebAudio stream through the app's normal mic API path."""
    return r"""
(() => {
  const state = window.__desktopVoiceE2E;
  const devices = navigator.mediaDevices;
  state.nativeGetUserMediaCalls = 0;
  state.syntheticMediaInjected = false;
  state.timeline.push({kind: 'install_synthetic_source'});
  Object.defineProperty(devices, 'getUserMedia', {
    configurable: true,
    value: async constraints => {
      state.timeline.push({kind: 'getUserMedia'});
      state.lastMediaConstraints = {
        audio: Boolean(constraints?.audio),
        requestedDevice: Boolean(constraints?.audio?.deviceId),
      };
      if (state.failNextGetUserMedia) {
        state.failNextGetUserMedia = false;
        state.timeline.push({kind: 'getUserMedia_denied'});
        throw new DOMException('synthetic permission denial', 'NotAllowedError');
      }
      const context = new AudioContext();
      await context.resume();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const destination = context.createMediaStreamDestination();
      oscillator.frequency.value = 440;
      gain.gain.value = 0;
      oscillator.connect(gain).connect(destination);
      oscillator.start();
      window.__desktopSyntheticMic = {context, oscillator, gain, destination};
      state.syntheticMediaInjected = true;
      return destination.stream;
    },
  });
  window.setSyntheticMicLevel = level => {
    const mic = window.__desktopSyntheticMic;
    if (!mic) throw new Error('synthetic microphone is not initialized');
    mic.gain.gain.setValueAtTime(Number(level), mic.context.currentTime);
    state.timeline.push({kind: 'synthetic_level', level: Number(level)});
  };
})();
"""


class SyntheticFinalTranscriber:
    """Deterministic transcript fixture; it does not recognize the generated tone."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turn = 0
        self.calls: list[dict[str, object]] = []

    def transcribe(self, wav_bytes: bytes, *, cancel_event: threading.Event | None = None) -> str:
        with self._lock:
            self._turn += 1
            transcript = f"synthetic utterance {self._turn}"
            self.calls.append({"turn": self._turn, "wav_bytes": len(wav_bytes)})
            return transcript


class SyntheticVoiceMem(VoiceMemProcessClient):
    """VoiceMem transport stub required by the current external-ASR route."""

    def health(self) -> dict[str, str]:
        return {"status": "ready", "mode": "mock"}

    def feed_partial(self, *_args, **_kwargs) -> list[dict[str, object]]:
        return []

    def feed_audio(self, *_args, **_kwargs) -> list[dict[str, object]]:
        return []

    def end_audio(self, *_args, **_kwargs) -> list[dict[str, object]]:
        return []

    def abort(self) -> None:
        return None

    def close(self) -> None:
        return None

    def feed_partial(self, *_args, **_kwargs):
        return []


def _send_chat(driver, text: str) -> None:
    from selenium.webdriver.common.by import By

    box = driver.find_element(By.ID, "chat-input")
    box.clear()
    box.send_keys(text)
    driver.find_element(By.ID, "chat-send").click()


_DIAGNOSTIC_KEYS = (
    "kind", "path", "action", "owner", "capture_id", "session_id", "status", "ttsId",
    "startedAt", "headersAt", "failedAt", "at", "level", "state", "active", "scheduledAt",
    "startAt", "endedAt", "endReason", "rms", "duration", "pcm16_bytes", "error",
)
_DIAGNOSTIC_ARRAYS = ("fetches", "timeline", "speech", "decoded", "sources", "overlaps")


def _redact_diagnostic_text(value: object) -> str:
    text = str(value)[:4096]
    text = re.sub(r"\{.*|\[\s*[\{\"'].*", "[structured data]", text, flags=re.DOTALL)

    def safe_url(match: re.Match[str]) -> str:
        try:
            parsed = urlsplit(match.group())
            host = parsed.hostname
            if host not in {"127.0.0.1", "localhost", "::1"}:
                return "[url]"
            netloc = f"[{host}]" if host == "::1" else host
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        except ValueError:
            return "[url]"

    text = re.sub(r'https?://[^\s<>"\']+', safe_url, text, flags=re.IGNORECASE)
    text = re.sub(r"file://\S+|/(?:Users|home|tmp|var|private)/\S+", "[path]", text)
    text = re.sub(r"\b[A-Za-z]:[\\/][^\s<>\"']+", "[path]", text)
    text = re.sub(r"(?i)\b(?:bearer|basic)\s+\S+", "[credential]", text)
    text = re.sub(
        r"(?is)\b(?:authorization|cookie|set-cookie|api[_-]?key|[a-z0-9_-]*token[a-z0-9_-]*|password|secret|body|headers?)"
        r"\b[\"']?\s*[:=].*", "[redacted]", text,
    )
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return text[:256]


def _diagnostic_row(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, object] = {}
    for key in _DIAGNOSTIC_KEYS:
        item = value.get(key)
        if key == "error" and isinstance(item, dict):
            result[key] = {name: _redact_diagnostic_text(item.get(name, "")) for name in ("name", "message")}
        elif isinstance(item, str):
            result[key] = _redact_diagnostic_text(item)
        elif item is None or isinstance(item, (bool, int)) or isinstance(item, float) and math.isfinite(item):
            if key in value:
                result[key] = item
    return result


def _collect_failure_diagnostics(driver) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    try:
        snapshot = driver.execute_script("""
          const source = window.__desktopVoiceE2E || {};
          const keys = arguments[0], arrays = arguments[1], result = {};
          for (const name of arrays) {
            const rows = Array.isArray(source[name]) ? source[name] : [];
            result[name] = rows.slice(-64).map(row => Object.fromEntries(
              keys.filter(key => key in row && (key === 'error' || row[key] === null ||
                ['string', 'number', 'boolean'].includes(typeof row[key]))).map(key => [key, key === 'error'
                ? {name: String(row.error?.name || '').slice(0, 256),
                   message: String(row.error?.message || '').slice(0, 256)}
                : typeof row[key] === 'string' ? row[key].slice(0, 256) : row[key]])));
            result[name + '_total'] = rows.length;
          }
          result.mic_ui = {
            text: (document.getElementById('mic-state')?.textContent || '').slice(0, 256),
            starting: typeof micStarting !== 'undefined' ? Boolean(micStarting) : null,
            active: typeof state !== 'undefined' ? Boolean(state.micActive) : null,
            button_disabled: document.getElementById('chat-mic')?.disabled ?? null,
          };
          return result;
        """, list(_DIAGNOSTIC_KEYS), list(_DIAGNOSTIC_ARRAYS))
        if isinstance(snapshot, dict):
            for name in _DIAGNOSTIC_ARRAYS:
                rows = snapshot.get(name, [])
                diagnostics[name] = [_diagnostic_row(row) for row in rows[-64:]] if isinstance(rows, list) else []
                total = snapshot.get(name + "_total")
                if isinstance(total, int) and total >= 0:
                    diagnostics[name + "_total"] = total
            ui = snapshot.get("mic_ui", {})
            if isinstance(ui, dict):
                diagnostics["mic_ui"] = {"text": _redact_diagnostic_text(ui.get("text", ""))}
                diagnostics["mic_ui"].update({key: ui[key] for key in ("starting", "active", "button_disabled")
                                              if key in ui and (isinstance(ui[key], bool) or ui[key] is None)})
    except Exception as exc:
        diagnostics["snapshot_error"] = _redact_diagnostic_text(type(exc).__name__)
    try:
        errors = [entry for entry in driver.get_log("browser") if entry.get("level") in {"SEVERE", "ERROR"}]
        diagnostics["console_errors"] = [
            {"level": entry["level"], "message": _redact_diagnostic_text(entry.get("message", "")),
             **({"timestamp": entry["timestamp"]} if isinstance(entry.get("timestamp"), (int, float))
                and math.isfinite(entry["timestamp"]) else {})}
            for entry in errors[-32:]
        ]
        diagnostics["console_errors_total"] = len(errors)
    except Exception as exc:
        diagnostics["console_log_error"] = _redact_diagnostic_text(type(exc).__name__)
    return diagnostics


def _write_report(path: Path, report: dict[str, object]) -> None:
    target = path if path.is_absolute() else ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic-provider Selenium acceptance for desktop streamed voice")
    parser.add_argument("--timeout", type=int, default=30, help="maximum wait per browser acceptance phase")
    parser.add_argument("--report", type=Path, default=Path("runtime/desktop-voice-e2e.json"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("runtime/browser-evidence/desktop-voice"))
    args = parser.parse_args()

    report: dict[str, object] = {
        "schema_version": 1,
        "run_id": uuid4().hex,
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": "desktop_voice_synthetic_browser_acceptance",
        "status": "failed",
        "mode": "selenium_edge_real_app_mockbrain_synthetic_tts",
        "provider_scope": "deterministic in-process responder and generated tone WAVs",
        "claims": {
            "real_companion_backend_stream_handler": True,
            "real_tts_ndjson_serializer": "CompanionRequestHandler._stream_tts",
            "real_browser_audio_pipeline": "app.js + voice-input.js + speech-stream.js + native WebAudio",
            "synthetic_microphone": "browser oscillator -> MediaStreamAudioDestination -> app capture path",
            "asr": "fixed deterministic transcripts; generated tone is not treated as speech recognition",
            "brain": "deterministic mock responder",
            "tts": "generated tone WAV chunks, not a voice model",
            "physical_microphone": False,
            "ambient_capture": False,
            "external_provider_or_model": False,
            "hardware_audio_quality": False,
            "capture_settings_fixture": "temporary ConfigHub files, removed with the harness",
        },
        "checks": [],
        "expected": "progressive native playback, ordered chunks, cancellation/stale-drop, no cross-turn overlap",
        "failure": None,
        "failure_phase": None,
    }
    server = None
    server_thread = None
    driver = None
    config_tmp = None
    tones = ProgressiveToneTTS()
    phase = "construct_isolated_server"
    try:
        from jawl_voicecompanion.gateway import TextGateway
        from jawl_voicecompanion.web import create_server
        from jawl_voicecompanion.config_hub import ConfigHub

        config_tmp = tempfile.TemporaryDirectory(prefix="jawl-desktop-voice-e2e-")
        config_root = Path(config_tmp.name) / "config"
        config_root.mkdir()
        (config_root / "settings.yaml").write_text("{}\n", encoding="utf-8")
        (config_root / "interfaces.yaml").write_text("voice:\n  enabled: true\n", encoding="utf-8")
        config_env = Path(config_tmp.name) / ".env"
        config_env.write_text("", encoding="utf-8")
        config_hub = ConfigHub(config_root, env_file=config_env)

        brain_turns: list[str] = []
        transcriber = SyntheticFinalTranscriber()
        reply = "Ответ mock brain для synthetic voice turn."
        gateway = TextGateway(
            responder=lambda text: brain_turns.append(text) or reply,
            brain_name="desktop_voice_e2e_mockbrain",
        )
        server = create_server(
            host="127.0.0.1",
            port=0,
            frontend_dir=ROOT / "frontend",
            gateway=gateway,
            voice_mem=SyntheticVoiceMem(),
            asr_service=UtteranceBuffer(transcriber=transcriber),
            tts_service=tones,
            config_hub=config_hub,
        )
        server_thread = threading.Thread(target=server.serve_forever, name="desktop-voice-e2e", daemon=True)
        server_thread.start()
        url = f"http://127.0.0.1:{server.server_port}/app"
        report["url"] = url
        report["server"] = {"host": "127.0.0.1", "port": server.server_port, "port_was_ephemeral": True}

        phase = "import_selenium"
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.support.ui import WebDriverWait

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--autoplay-policy=no-user-gesture-required")
        options.add_argument("--window-size=1440,1000")
        driver = webdriver.Edge(options=options)
        driver.set_page_load_timeout(30)
        driver.set_script_timeout(args.timeout + 5)

        phase = "load_real_desktop_app"
        driver.get(url)
        wait = WebDriverWait(driver, args.timeout)
        wait.until(lambda browser: browser.find_element(By.ID, "chat-send").is_displayed())
        driver.execute_script(_install_observability())
        driver.execute_script(_inject_synthetic_microphone())
        report["checks"].append("real_app_loaded")

        phase = "capture_settings_edit_save_and_readback"
        wait.until(lambda browser: browser.execute_script(
            "return micCaptureWritable && Boolean(micCaptureRevision) && !document.querySelector('#mic-capture-fields').disabled"
        ))
        driver.find_element(By.CSS_SELECTOR, '[data-tab="voice"]').click()
        updated_settings = {
            "gate_open": 0.02,
            "gate_close": 0.012,
            "silence_ms": 1200,
            "pre_roll_ms": 160,
        }
        setting_ids = {
            "gate_open": "mic-gate-open",
            "gate_close": "mic-gate-close",
            "silence_ms": "mic-silence-ms",
            "pre_roll_ms": "mic-pre-roll-ms",
        }
        configure_count_before_validation = driver.execute_script(
            "return window.__desktopVoiceE2E.fetches.filter(x => x.path === '/api/voice/capture' && x.action === 'configure').length"
        )
        driver.execute_script(
            "const input = document.getElementById('mic-silence-ms'); input.value = ''; input.dispatchEvent(new Event('input', {bubbles: true}));"
        )
        empty_rejected = driver.execute_script(
            "const input = document.getElementById('mic-silence-ms'); return input.validity.valueMissing && input.getAttribute('aria-invalid') === 'true' && document.getElementById('mic-capture-save').disabled"
        )
        driver.execute_script(
            "const input = document.getElementById('mic-silence-ms'); input.value = '1200'; input.dispatchEvent(new Event('input', {bubbles: true}));"
        )
        driver.execute_script(
            "const input = document.getElementById('mic-gate-close'); input.value = '0.03'; input.dispatchEvent(new Event('input', {bubbles: true}));"
        )
        threshold_rejected = driver.execute_script(
            "return document.getElementById('mic-gate-close').getAttribute('aria-invalid') === 'true' && document.getElementById('mic-capture-save').disabled && document.getElementById('mic-capture-error').textContent.includes('ниже')"
        )
        configure_count_after_validation = driver.execute_script(
            "return window.__desktopVoiceE2E.fetches.filter(x => x.path === '/api/voice/capture' && x.action === 'configure').length"
        )
        for key, element_id in setting_ids.items():
            driver.execute_script(
                "const input = document.getElementById(arguments[0]); input.value = String(arguments[1]); input.dispatchEvent(new Event('input', {bubbles: true}));",
                element_id,
                updated_settings[key],
            )
        report["invalid_input_acceptance"] = {
            "empty_required_number_is_rejected": empty_rejected,
            "gate_hysteresis_is_validated_before_save": threshold_rejected,
            "invalid_edits_never_reach_configure": configure_count_before_validation == configure_count_after_validation,
        }
        if not all(report["invalid_input_acceptance"].values()):
            raise AssertionError("empty or invalid capture setting was not rejected in the UI")
        save_button = driver.find_element(By.ID, "mic-capture-save")
        if not save_button.is_enabled():
            raise AssertionError("valid capture edits did not enable Save")
        save_button.click()
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.some(x => x.path === '/api/voice/capture' && x.action === 'configure' && x.status === 200)"
        ))
        driver.execute_async_script(
            "const done = arguments[arguments.length - 1]; fetch('/api/voice/capture', {credentials: 'include', headers: API.headers()}).then(r => r.json()).then(d => { window.__desktopVoiceE2E.settingsReadback = d; done(d); }).catch(e => done({error: String(e)}));"
        )
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.settingsReadback?.settings?.silence_ms === 1200"
        ))
        settings_readback = driver.execute_script("return window.__desktopVoiceE2E.settingsReadback")
        settings_save = next(
            item for item in driver.execute_script("return window.__desktopVoiceE2E.fetches")
            if item["path"] == "/api/voice/capture" and item.get("action") == "configure"
        )
        report["settings_acceptance"] = {
            "saved_through_configure_contract": settings_save["status"] == 200
            and settings_save.get("expected_revision")
            and settings_save.get("settings") == updated_settings,
            "readback_matches_saved_values": settings_readback.get("settings") == updated_settings
            and settings_readback.get("settings_writable") is True,
            "no_jawl_restart_requested": not any(
                item["path"] == "/api/jawl/restart"
                for item in driver.execute_script("return window.__desktopVoiceE2E.fetches")
            ),
        }
        if not all(report["settings_acceptance"].values()):
            raise AssertionError("capture settings did not save/read back as expected")
        report["checks"].append("capture_settings_saved_read_back_without_restart")

        phase = "capture_settings_revision_conflict_recovery"
        driver.execute_async_script(
            "const done = arguments[arguments.length - 1]; fetch('/api/voice/capture', {method: 'POST', credentials: 'include', headers: API.headers(), body: JSON.stringify({action: 'configure', settings: {pre_roll_ms: 170}, expected_revision: window.__desktopVoiceE2E.settingsReadback.revision})}).then(async r => done({status: r.status, body: await r.json()})).catch(e => done({error: String(e)}));"
        )
        driver.execute_script(
            "const input = document.getElementById('mic-silence-ms'); input.value = '1250'; input.dispatchEvent(new Event('input', {bubbles: true}));"
        )
        driver.find_element(By.ID, "mic-capture-save").click()
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.some(x => x.path === '/api/voice/capture' && x.action === 'configure' && x.status === 409)"
        ))
        conflict_visible = driver.execute_script(
            "return document.getElementById('mic-capture-error').textContent.includes('config changed') && document.getElementById('mic-capture-reload').hidden === false && document.getElementById('mic-silence-ms').value === '1250' && document.getElementById('mic-capture-save').disabled"
        )
        driver.find_element(By.ID, "mic-capture-reload").click()
        wait.until(lambda browser: browser.execute_script(
            "return !micCaptureDirty && !micCaptureNeedsReload && document.getElementById('mic-capture-reload').hidden && document.getElementById('mic-pre-roll-ms').value === '170' && document.getElementById('mic-silence-ms').value === '1200'"
        ))
        updated_settings["pre_roll_ms"] = 170
        report["conflict_recovery_acceptance"] = {
            "conflict_preserves_draft_and_blocks_retry": conflict_visible,
            "reload_fetches_latest_revision_and_values": driver.execute_script(
                "return micCaptureRevision === window.__desktopVoiceE2E.fetches.filter(x => x.path === '/api/voice/capture' && x.action === 'configure' && x.status === 200).at(-1).result?.revision || document.getElementById('mic-pre-roll-ms').value === '170'"
            ),
        }
        if not all(report["conflict_recovery_acceptance"].values()):
            raise AssertionError("capture settings revision conflict recovery failed")
        report["checks"].append("capture_settings_conflict_preserved_draft_and_reloaded")

        phase = "invalid_persisted_capture_config_is_explained"
        config_hub.interfaces_file.write_text(
            "voice:\n  enabled: true\n  capture:\n    gate_open: .nan\n",
            encoding="utf-8",
        )
        driver.execute_async_script(
            "const done = arguments[arguments.length - 1]; Promise.resolve(loadMicCaptureSettings()).then(() => done(true)).catch(e => done(String(e)));"
        )
        invalid_config_visible = driver.execute_script(
            "return document.getElementById('mic-capture-fields').disabled && document.getElementById('mic-capture-error').textContent.includes('gate_open must be a finite number') && !document.getElementById('mic-capture-error').textContent.includes('ConfigHub недоступен')"
        )
        config_hub.interfaces_file.write_text(
            "voice:\n  enabled: true\n  capture:\n    gate_open: 0.02\n    gate_close: 0.012\n    silence_ms: 1200\n    pre_roll_ms: 170\n",
            encoding="utf-8",
        )
        driver.execute_async_script(
            "const done = arguments[arguments.length - 1]; Promise.resolve(loadMicCaptureSettings()).then(() => done(true)).catch(e => done(String(e)));"
        )
        report["invalid_config_acceptance"] = {
            "server_validation_error_is_visible_and_settings_disabled": invalid_config_visible,
            "controls_reenabled_after_valid_config_readback": driver.execute_script(
                "return Boolean(micCaptureWritable && !document.getElementById('mic-capture-fields').disabled && micCaptureRevision)"
            ),
        }
        if not all(report["invalid_config_acceptance"].values()):
            raise AssertionError("invalid persisted config was not reported accurately")
        report["checks"].append("invalid_config_error_visible_then_recovered")

        phase = "busy_owner_rejected_before_media_permission"
        driver.execute_async_script(
            "const done = arguments[arguments.length - 1]; fetch('/api/voice/capture', {method: 'POST', credentials: 'include', headers: API.headers(), body: JSON.stringify({action: 'acquire', owner: 'native', capture_id: 'native-busy-owner'})}).then(async r => done({status: r.status, body: await r.json()})).catch(e => done({error: String(e)}));"
        )
        media_count_before_busy = driver.execute_script(
            "return window.__desktopVoiceE2E.timeline.filter(x => x.kind === 'getUserMedia').length"
        )
        driver.find_element(By.CSS_SELECTOR, '[data-tab="chat"]').click()
        driver.find_element(By.ID, "chat-mic").click()
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.some(x => x.path === '/api/voice/capture' && x.action === 'acquire' && x.owner === 'desktop' && x.status === 409 && x.result?.error === 'capture_busy')"
        ))
        media_count_after_busy = driver.execute_script(
            "return window.__desktopVoiceE2E.timeline.filter(x => x.kind === 'getUserMedia').length"
        )
        driver.execute_async_script(
            "const done = arguments[arguments.length - 1]; fetch('/api/voice/capture', {method: 'POST', credentials: 'include', headers: API.headers(), body: JSON.stringify({action: 'release', owner: 'native', capture_id: 'native-busy-owner'})}).then(r => done(r.status)).catch(e => done(String(e)));"
        )
        report["busy_owner_acceptance"] = {
            "desktop_acquire_rejected_as_busy": any(
                item["path"] == "/api/voice/capture" and item.get("action") == "acquire"
                and item.get("owner") == "desktop" and item["status"] == 409
                and item.get("result", {}).get("error") == "capture_busy"
                for item in driver.execute_script("return window.__desktopVoiceE2E.fetches")
            ),
            "get_user_media_not_called_for_busy_owner": media_count_before_busy == media_count_after_busy == 0,
        }
        if not all(report["busy_owner_acceptance"].values()):
            raise AssertionError("busy capture owner reached the browser media permission path")
        report["checks"].append("busy_capture_owner_rejected_before_get_user_media")

        phase = "denied_capture_releases_lease"
        driver.execute_script("window.__desktopVoiceE2E.failNextGetUserMedia = true")
        driver.find_element(By.ID, "chat-mic").click()
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.timeline.some(x => x.kind === 'getUserMedia_denied')"
        ))
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.some(x => x.path === '/api/voice/capture' && x.action === 'release' && x.status === 200)"
        ))
        driver.find_element(By.ID, "chat-mic").click()
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.syntheticMediaInjected"
        ))
        driver.execute_script("window.setSyntheticMicLevel(0.12)")
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.some(x => x.path === '/api/voice/audio' && x.status === 200 && x.pcm16_bytes > 0)"
        ))
        driver.execute_script("window.setSyntheticMicLevel(0)")

        phase = "first_synthetic_voice_turn_reaches_end_and_tts"
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.some(x => x.path === '/api/voice/end' && x.status === 200 && x.transcript === 'synthetic utterance 1' && x.response_count === 1)"
        ))
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.some(x => x.path === '/api/tts/stream' && x.ttsId === 1)"
        ))

        phase = "first_native_audio_before_provider_done"
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.sources.some(x => x.ttsId === 1)"
        ))
        first_streams = tones.snapshot()
        if not first_streams or first_streams[0]["completed"]:
            raise AssertionError("first native buffer was not scheduled while the provider was still gated")
        report["checks"].append("first_decoded_and_scheduled_before_tts_done")
        tones.release_first_chunk()

        phase = "second_synthetic_utterance_barges_in"
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.sources.filter(x => x.ttsId === 1).length >= 2"
        ))
        driver.execute_script("window.setSyntheticMicLevel(0.12)")
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.speech.some(x => x.state === 'cancel' && x.ttsId === 1)"
        ))
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.filter(x => x.path === '/api/voice/audio' && x.status === 200).length >= 2"
        ))
        time.sleep(0.18)
        driver.execute_script("window.setSyntheticMicLevel(0)")
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.some(x => x.path === '/api/voice/end' && x.status === 200 && x.transcript === 'synthetic utterance 2' && x.response_count === 1)"
        ))
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.fetches.some(x => x.path === '/api/tts/stream' && x.ttsId === 2)"
        ))
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.sources.some(x => x.ttsId === 2)"
        ))
        tones.release_late_chunk()
        report["checks"].append("actual_app_cancel_replaced_active_speech_owner")

        phase = "wait_second_stream_audio_drain"
        wait.until(lambda browser: browser.execute_script(
            "return window.__desktopVoiceE2E.speech.some(x => x.state === 'done' && x.ttsId === 2)"
        ))
        wait.until(lambda _browser: len(tones.snapshot()) >= 2 and bool(tones.snapshot()[1]["completed"]))
        # Allow a disconnected first response to attempt and lose its late
        # chunk before asserting that the real client never decoded/scheduled it.
        wait.until(lambda _browser: len(tones.snapshot()[0]["yielded_chunks"]) >= 3)
        time.sleep(0.2)

        phase = "stop_mic_releases_lease"
        driver.find_element(By.ID, "chat-mic").click()
        wait.until(lambda browser: browser.execute_script(
            "const fetches = window.__desktopVoiceE2E.fetches; const active = fetches.filter(x => x.path === '/api/voice/capture' && x.action === 'acquire' && x.owner === 'desktop' && x.status === 200).at(-1); return Boolean(active && fetches.some(x => x.path === '/api/voice/capture' && x.action === 'release' && x.owner === 'desktop' && x.capture_id === active.capture_id && x.status === 200))"
        ))

        phase = "evaluate_acceptance"
        state = driver.execute_script("return window.__desktopVoiceE2E")
        stream_one = [item for item in state["sources"] if item["ttsId"] == 1]
        stream_two = [item for item in state["sources"] if item["ttsId"] == 2]
        decoded_one = [item for item in state["decoded"] if item["ttsId"] == 1]
        decoded_two = [item for item in state["decoded"] if item["ttsId"] == 2]
        cancel_events = [item for item in state["speech"] if item["state"] == "cancel" and item["ttsId"] == 1]
        acceptance = {
            "first_audio_scheduled_while_provider_blocked": bool(first_streams and not first_streams[0]["completed"]),
            "first_stream_cancelled_after_two_scheduled_chunks": len(stream_one) == 2 and len(decoded_one) == 2 and bool(cancel_events),
            "late_first_stream_chunk_rejected_as_stale": len(tones.snapshot()[0]["yielded_chunks"]) >= 3 and len(stream_one) == 2,
            "scoped_cancel_targets_first_request_not_replacement": (
                bool(tones.snapshot()[0]["request_id"])
                and tones.snapshot()[0]["request_id"] in tones.cancel_snapshot()
                and tones.snapshot()[1]["request_id"] not in tones.cancel_snapshot()
            ),
            "replacement_stream_scheduled_all_three_chunks": len(stream_two) == 3 and len(decoded_two) == 3,
            "chunk_rms_measured_in_native_audio_buffers": all(0.05 <= float(item["rms"]) <= 0.30 for item in stream_two),
            "replacement_chunks_scheduled_in_order": all(
                float(left["startAt"]) < float(right["startAt"])
                for left, right in zip(stream_two, stream_two[1:])
            ),
            "no_cross_turn_audio_source_overlap": not state["overlaps"],
            "no_physical_capture_started": state["syntheticMediaInjected"] and state["nativeGetUserMediaCalls"] == 0,
        }
        capture_acquires = [item for item in state["fetches"] if item["path"] == "/api/voice/capture" and item.get("action") == "acquire" and item.get("owner") == "desktop" and item["status"] == 200]
        capture_releases = [item for item in state["fetches"] if item["path"] == "/api/voice/capture" and item.get("action") == "release" and item.get("owner") == "desktop"]
        media_denied_index = next(i for i, item in enumerate(state["timeline"]) if item["kind"] == "getUserMedia_denied")
        first_release_index = next(i for i, item in enumerate(state["timeline"]) if item["kind"] == "fetch" and item["path"] == "/api/voice/capture" and item["action"] == "release" and item.get("owner") == "desktop" and item.get("status") == 200)
        media_call_indices = [i for i, item in enumerate(state["timeline"]) if item["kind"] == "getUserMedia"]
        acquire_indices = [i for i, item in enumerate(state["timeline"]) if item["kind"] == "fetch" and item["path"] == "/api/voice/capture" and item["action"] == "acquire" and item.get("owner") == "desktop" and item.get("status") == 200]
        voice_audio = [item for item in state["fetches"] if item["path"] == "/api/voice/audio" and item["status"] == 200]
        voice_ends = [item for item in state["fetches"] if item["path"] == "/api/voice/end" and item["status"] == 200]
        capture_acceptance = {
            "lease_acquired_before_media_and_released_after_denial": (
                len(media_call_indices) == 2 and len(acquire_indices) >= 2
                and acquire_indices[0] < media_call_indices[0] < media_denied_index
                < first_release_index < acquire_indices[1] < media_call_indices[1]
                and len(capture_acquires) >= 2 and len(capture_releases) >= 2
                and any(item["capture_id"] == capture_acquires[0]["capture_id"] and item["status"] == 200 for item in capture_releases)
            ),
            "synthetic_pcm_uploaded_with_matching_lease": (
                len(voice_audio) >= 2
                and all(item["pcm16_bytes"] > 0 and item["owner"] == "desktop" for item in voice_audio)
                and all(item["capture_id"] == capture_acquires[1]["capture_id"] for item in voice_audio)
            ),
            "new_capture_uses_saved_settings": any(
                item.get("owner") == "desktop" and item.get("result", {}).get("gate_open") == updated_settings["gate_open"]
                and item.get("result", {}).get("gate_close") == updated_settings["gate_close"]
                and item.get("result", {}).get("silence_ms") == updated_settings["silence_ms"]
                and item.get("result", {}).get("pre_roll_ms") == updated_settings["pre_roll_ms"]
                for item in capture_acquires
            ),
            "voice_end_created_two_mock_turns": (
                len(voice_ends) == 2
                and [item["transcript"] for item in voice_ends] == ["synthetic utterance 1", "synthetic utterance 2"]
                and all(item["response_count"] == 1 and item["capture_ok"] for item in voice_ends)
                and len(brain_turns) == 2 and len(transcriber.calls) == 2
            ),
            "synthetic_barge_in_cancelled_and_started_new_voice_turn": (
                any(item["state"] == "cancel" and item["ttsId"] == 1 for item in state["speech"])
                and len(voice_ends) == 2 and any(item["path"] == "/api/tts/stream" and item["ttsId"] == 2 for item in state["fetches"])
            ),
            "stop_released_current_capture_lease": (
                len(capture_releases) >= 2
                and capture_releases[-1]["capture_id"] == capture_acquires[1]["capture_id"]
                and capture_releases[-1]["status"] == 200
            ),
        }
        report["capture_acceptance"] = capture_acceptance
        report["synthetic_capture"] = {
            "native_get_user_media_calls": state["nativeGetUserMediaCalls"],
            "synthetic_media_injected": state["syntheticMediaInjected"],
            "pcm_upload_count": len(voice_audio),
            "voice_end": [{"status": item["status"], "transcript": item["transcript"], "response_count": item["response_count"]} for item in voice_ends],
            "lease_actions": [{"action": item.get("action"), "status": item["status"]} for item in state["fetches"] if item["path"] == "/api/voice/capture"],
            "mock_asr_turns": len(transcriber.calls),
            "mock_brain_turns": len(brain_turns),
        }
        report["acceptance"] = acceptance
        report["browser_audio"] = {
            "tts_requests": [
                {"ttsId": item["ttsId"], "status": item["status"]}
                for item in state["fetches"] if item["path"] == "/api/tts/stream"
            ],
            "scheduled_chunks": state["sources"],
            "decoded_chunks": state["decoded"],
            "speech_events": state["speech"],
            "overlaps": state["overlaps"],
        }
        report["provider_streams"] = tones.snapshot()
        driver.find_element(By.CSS_SELECTOR, '[data-tab="voice"]').click()
        wait.until(lambda browser: browser.execute_script(
            "return !document.getElementById('mic-capture-fields').disabled && document.getElementById('mic-pre-roll-ms').value === '170'"
        ))
        driver.set_window_size(1440, 1200)
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        screenshot = args.evidence_dir / "desktop-voice-e2e.png"
        driver.save_screenshot(str(screenshot))
        report["screenshot"] = str(screenshot)
        if not all(acceptance.values()) or not all(capture_acceptance.values()):
            failed = [key for key, ok in {**acceptance, **capture_acceptance}.items() if not ok]
            raise AssertionError("acceptance conditions failed: " + ", ".join(failed))
        report["checks"].append("ordered_rms_cancellation_stale_drop_no_overlap")
        report["status"] = "passed"
    except Exception as exc:
        report["failure_phase"] = phase
        report["failure"] = _redact_diagnostic_text(f"{type(exc).__name__}: {exc}")
        if driver is not None:
            report["browser_diagnostics"] = _collect_failure_diagnostics(driver)
            try:
                args.evidence_dir.mkdir(parents=True, exist_ok=True)
                screenshot = args.evidence_dir / "desktop-voice-e2e-failure.png"
                driver.save_screenshot(str(screenshot))
                report["failure_screenshot"] = str(screenshot)
            except Exception:
                pass
        report["provider_streams"] = tones.snapshot()
    finally:
        tones.close()
        if driver is not None:
            driver.quit()
        if server is not None:
            server.shutdown()
            if server_thread is not None:
                server_thread.join(timeout=5)
            server.server_close()
        if config_tmp is not None:
            config_tmp.cleanup()
        report["exit_code"] = 0 if report["status"] == "passed" else 1
        _write_report(args.report, report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
