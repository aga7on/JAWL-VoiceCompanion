"""Run synthetic WAVs through the real browser audio HTTP path.

The target Companion must already be running with external ASR, native JAWL,
the selected LLM and TTS configured. This harness never starts a mock server.
"""

from __future__ import annotations

import argparse
import base64
import json
import time
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Live browser ASR -> JAWL -> TTS E2E")
    parser.add_argument("--url", default="http://127.0.0.1:2367")
    parser.add_argument("--wav", action="append", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("runtime/browser-voice-e2e.json"))
    parser.add_argument("--evidence-dir", type=Path, default=Path("runtime/browser-evidence/voice"))
    parser.add_argument("--live", action="store_true", help="acknowledge real provider/audio acceptance")
    args = parser.parse_args()
    report = {"schema_version": 1, "profile": "browser_voice_e2e", "status": "refused", "url": args.url, "turns": [], "screenshots": [], "failure": None}
    if not args.live:
        report["failure"] = "live_acknowledgement_required"
        return _write(args, report, 2)
    if len(args.wav) < 3:
        report["failure"] = "at_least_three_wav_files_required"
        return _write(args, report, 2)
    for path in args.wav:
        if not path.is_file():
            report["failure"] = f"missing_wav:{path}"
            return _write(args, report, 2)
    try:
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
        # Local CPU JAWL/LLM turns can legitimately exceed Selenium's default
        # 30-second async-script limit; the application still owns its own
        # bounded turn timeout. Keep the browser harness long enough to record
        # that outcome instead of converting it into a driver artefact.
        driver.set_script_timeout(180)
    except Exception as exc:
        report["failure"] = f"browser_start:{type(exc).__name__}"
        return _write(args, report, 1)
    try:
        driver.get(args.url.rstrip("/") + "/")
        wait = WebDriverWait(driver, 20)
        wait.until(lambda d: d.find_element(By.ID, "send").is_displayed())
        for index, path in enumerate(args.wav, 1):
            with wave.open(str(path), "rb") as source:
                if source.getnchannels() != 1 or source.getsampwidth() != 2:
                    raise ValueError(f"{path.name}: expected mono PCM16 WAV")
                rate = source.getframerate()
                pcm = source.readframes(source.getnframes())
            started = time.perf_counter()
            encoded = base64.b64encode(pcm).decode("ascii")
            result = driver.execute_async_script(_BROWSER_TURN, encoded, rate, f"browser-voice-{index}")
            elapsed = round(time.perf_counter() - started, 3)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise RuntimeError(f"turn {index} failed: {result}")
            result["wav"] = path.name
            result["elapsed_seconds"] = elapsed
            report["turns"].append(result)
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        screenshot = args.evidence_dir / "browser-voice-final.png"
        driver.save_screenshot(str(screenshot))
        report["screenshots"].append(str(screenshot))
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        driver.quit()
    return _write(args, report, 0 if report["status"] == "passed" else 1)


_BROWSER_TURN = r"""
const done = arguments[arguments.length - 1];
(async () => {
  const pcmBase64 = arguments[0], sampleRate = arguments[1], sessionId = arguments[2];
  const bytes = Uint8Array.from(atob(pcmBase64), c => c.charCodeAt(0));
  const sessionResponse = await fetch('/api/session');
  if (!sessionResponse.ok) return done({ok: false, stage: 'session', status: sessionResponse.status});
  const session = await sessionResponse.json();
  const headers = {'Content-Type': 'application/json', 'X-Companion-CSRF': session.csrf_token};
  const encode = value => btoa(String.fromCharCode(...new Uint8Array(value)));
  const chunkBytes = Math.max(256, Math.floor(sampleRate * 2 * 0.12));
  let chunks = 0;
  for (let offset = 0; offset < bytes.length; offset += chunkBytes) {
    const body = {session_id: sessionId, sample_rate: sampleRate, channels: 1,
      pcm16_base64: encode(bytes.slice(offset, Math.min(bytes.length, offset + chunkBytes)))};
    const response = await fetch('/api/voice/audio', {method: 'POST', headers, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok || data.ok !== true) return done({ok: false, stage: 'asr_upload', status: response.status, error: data.error});
    chunks++;
  }
  const ended = await fetch('/api/voice/end', {method: 'POST', headers,
    body: JSON.stringify({session_id: sessionId, correlation_id: sessionId})});
  const result = await ended.json();
  if (!ended.ok || result.ok !== true || result.mode !== 'external_final_utterance' ||
      !Array.isArray(result.responses) || result.responses.length !== 1) {
    return done({ok: false, stage: 'jawl_response', status: ended.status, result});
  }
  const text = result.responses[0].text || '';
  const tts = await fetch('/api/tts/synthesize', {method: 'POST', headers,
    body: JSON.stringify({text, voice: 'ru_f1', speed: 1.0})});
  if (!tts.ok) return done({ok: false, stage: 'tts', status: tts.status, error: (await tts.text()).slice(0, 300)});
  const audio = new Audio(URL.createObjectURL(await tts.blob()));
  await new Promise((resolve, reject) => {audio.onended = resolve; audio.onerror = reject; audio.play().catch(reject);});
  done({ok: true, chunks, response_count: result.responses.length, response_text_chars: text.length,
    event_types: (result.events || []).map(event => event.type), playback_completed: true});
})().catch(error => done({ok: false, stage: 'browser', error: String(error)}));
"""


def _write(args: argparse.Namespace, report: dict, code: int) -> int:
    path = args.report if args.report.is_absolute() else ROOT / args.report
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
