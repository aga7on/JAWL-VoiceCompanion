"""Bounded file/PCM acceptance for an explicitly owned live Companion profile.

The fixture is synthesized in memory by the configured TTS, submitted as PCM
to the production GigaAM finalization route, answered by native JAWL, and
rendered through the production TTS stream. No audio device or screen API is
opened by this runner. Reports contain provider identities and measurements,
not fixture, transcript, answer, session, or credential values.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import re
import sys
import threading
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import requests


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_TEXT = "Как называется прибор для измерения температуры?"
SAMPLE_RATE = 16_000
CHUNK_SECONDS = 0.32
MAX_FIXTURE_SECONDS = 12.0
MAX_PCM_BYTES = int(SAMPLE_RATE * 2 * MAX_FIXTURE_SECONDS)
MAX_TTS_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
MAX_TTS_WIRE_BYTES = 12 * 1024 * 1024
MAX_TTS_LINE_BYTES = 11 * 1024 * 1024
MAX_WAV_SECONDS = 30
LEASE_RENEW_INTERVAL_SECONDS = 4.0
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


class AcceptanceFailure(RuntimeError):
    pass


def loopback_url(value: str) -> str:
    parsed = urlsplit(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--url must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("--url must not contain credentials, query parameters or fragments")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("refusing a non-loopback URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _json(response: requests.Response, label: str) -> dict:
    try:
        length = response.headers.get("Content-Length")
        if length is not None and int(length) > MAX_JSON_BYTES:
            raise AcceptanceFailure(f"{label} exceeded the bounded JSON response size")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            if len(chunk) > MAX_JSON_BYTES - len(body):
                raise AcceptanceFailure(f"{label} exceeded the bounded JSON response size")
            body.extend(chunk)
        value = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, requests.RequestException) as exc:
        raise AcceptanceFailure(f"{label} returned invalid JSON (HTTP {response.status_code})") from exc
    finally:
        response.close()
    if not isinstance(value, dict):
        raise AcceptanceFailure(f"{label} returned a non-object payload")
    return value


def _get_json(session: requests.Session, url: str, label: str, *, headers=None, timeout: float):
    response = session.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=False)
    return response.status_code, _json(response, label)


def _post_json(session: requests.Session, url: str, payload: dict, label: str, *,
               headers: dict[str, str], timeout: float):
    response = session.post(url, headers=headers, json=payload, timeout=timeout,
                            stream=True, allow_redirects=False)
    return response.status_code, _json(response, label)


def _pcm_from_wav(payload: bytes, *, max_output_bytes: int = MAX_TTS_BYTES) -> tuple[bytes, int]:
    if not isinstance(payload, bytes) or len(payload) > MAX_TTS_BYTES or len(payload) < 44:
        raise AcceptanceFailure("TTS WAV chunk exceeded bounds or was truncated")
    try:
        with wave.open(io.BytesIO(payload), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            compression = source.getcomptype()
            frame_count = source.getnframes()
            if frame_count > rate * MAX_WAV_SECONDS:
                raise AcceptanceFailure("TTS WAV chunk exceeded the duration bound")
            target_bytes = int(frame_count * SAMPLE_RATE / rate) * 2
            if target_bytes > max_output_bytes:
                raise AcceptanceFailure("TTS WAV chunk exceeded the PCM output bound")
            frames = source.readframes(source.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AcceptanceFailure("TTS returned an invalid WAV chunk") from exc
    if channels not in (1, 2) or width != 2 or not 8_000 <= rate <= 96_000 or compression != "NONE":
        raise AcceptanceFailure("TTS WAV must be mono/stereo PCM16 at a supported rate")
    if len(frames) != frame_count * channels * width:
        raise AcceptanceFailure("TTS WAV frame data is truncated")
    if channels == 2:
        frames = b"".join(
            int((int.from_bytes(frames[i:i + 2], "little", signed=True) +
                 int.from_bytes(frames[i + 2:i + 4], "little", signed=True)) / 2)
            .to_bytes(2, "little", signed=True)
            for i in range(0, len(frames), 4)
        )
    mono_count = len(frames) // 2
    if rate == SAMPLE_RATE:
        return frames, rate
    out_count = int(mono_count * SAMPLE_RATE / rate)
    result = bytearray(out_count * 2)
    for out_index in range(out_count):
        source_pos = out_index * rate / SAMPLE_RATE
        left = min(int(source_pos), max(0, mono_count - 1))
        right = min(left + 1, max(0, mono_count - 1))
        frac = source_pos - left
        a = int.from_bytes(frames[left * 2:left * 2 + 2], "little", signed=True)
        b = int.from_bytes(frames[right * 2:right * 2 + 2], "little", signed=True)
        sample = max(-32768, min(32767, round(a + (b - a) * frac)))
        result[out_index * 2:out_index * 2 + 2] = sample.to_bytes(2, "little", signed=True)
    return bytes(result), SAMPLE_RATE


def _pcm_metrics(pcm: bytes) -> dict[str, float | int]:
    rate = SAMPLE_RATE
    if not pcm:
        raise AcceptanceFailure("TTS returned an empty playable WAV")
    samples = (int.from_bytes(pcm[i:i + 2], "little", signed=True) for i in range(0, len(pcm), 2))
    square_sum = 0
    peak = 0
    count = 0
    for sample in samples:
        square_sum += sample * sample
        peak = max(peak, abs(sample))
        count += 1
    rms = math.sqrt(square_sum / max(1, count))
    if peak < 64 or rms < 16:
        raise AcceptanceFailure("TTS WAV is silent or not meaningfully playable")
    return {"sample_rate": rate, "duration_seconds": round(count / rate, 3), "pcm_bytes": len(pcm),
            "peak": peak, "rms": round(rms, 1)}


def _stream_tts(session: requests.Session, base: str, headers: dict[str, str], text: str,
                correlation_id: str, timeout: float, *, pcm_limit: int = MAX_TTS_BYTES
                ) -> tuple[bytes, dict[str, float | int]]:
    response = session.post(
        base + "/api/tts/stream", headers=headers,
        json={"text": text, "correlation_id": correlation_id},
        timeout=(5, min(timeout, 20.0)), stream=True, allow_redirects=False,
    )
    try:
        if response.status_code != 200:
            raise AcceptanceFailure(f"TTS stream failed (HTTP {response.status_code})")
        if "ndjson" not in response.headers.get("Content-Type", "").casefold():
            raise AcceptanceFailure("TTS stream did not return the production NDJSON media type")
        audio = bytearray()
        done = False
        deadline = time.monotonic() + timeout
        wire_total = 0
        pending = bytearray()

        def accept_line(raw_line: bytes) -> None:
            nonlocal done
            if not raw_line:
                return
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (TypeError, ValueError, UnicodeDecodeError) as exc:
                raise AcceptanceFailure("TTS stream contained invalid NDJSON") from exc
            if not isinstance(event, dict):
                raise AcceptanceFailure("TTS stream contained a non-object event")
            if event.get("type") == "error":
                raise AcceptanceFailure("TTS provider reported a stream error")
            if event.get("type") == "audio":
                encoded = event.get("data_base64")
                if not isinstance(encoded, str):
                    raise AcceptanceFailure("TTS audio event had no WAV data")
                if len(encoded) > ((MAX_TTS_BYTES + 2) // 3) * 4:
                    raise AcceptanceFailure("TTS base64 audio exceeded the encoded-size bound")
                estimated = (len(encoded) // 4) * 3
                if estimated > pcm_limit - len(audio) + 64:
                    raise AcceptanceFailure("TTS output exceeded the bounded audio limit")
                try:
                    chunk = base64.b64decode(encoded, validate=True)
                except ValueError as exc:
                    raise AcceptanceFailure("TTS audio event had invalid base64") from exc
                if len(chunk) > MAX_TTS_BYTES:
                    raise AcceptanceFailure("TTS WAV chunk exceeded the audio bound")
                chunk_pcm, _ = _pcm_from_wav(chunk, max_output_bytes=pcm_limit - len(audio))
                if len(chunk_pcm) > pcm_limit - len(audio):
                    raise AcceptanceFailure("TTS output exceeded the bounded audio limit")
                audio.extend(chunk_pcm)
            elif event.get("type") == "done":
                done = True
        for chunk in response.iter_content(chunk_size=8192):
            if time.monotonic() > deadline:
                raise AcceptanceFailure("TTS stream exceeded its bounded deadline")
            if not chunk:
                continue
            wire_total += len(chunk)
            if wire_total > MAX_TTS_WIRE_BYTES:
                raise AcceptanceFailure("TTS stream exceeded the bounded wire size")
            offset = 0
            while offset < len(chunk):
                newline = chunk.find(b"\n", offset)
                end = len(chunk) if newline < 0 else newline
                segment = chunk[offset:end]
                if len(segment) > MAX_TTS_LINE_BYTES - len(pending):
                    raise AcceptanceFailure("TTS NDJSON event exceeded the line-size bound")
                pending.extend(segment)
                if newline < 0:
                    break
                accept_line(bytes(pending))
                pending.clear()
                offset = newline + 1
        if pending:
            accept_line(bytes(pending))
        if not done or not audio:
            raise AcceptanceFailure("TTS stream did not complete with playable audio")
        pcm = bytes(audio)
        return pcm, _pcm_metrics(pcm)
    finally:
        response.close()


def _provider_preflight(session: requests.Session, base: str, args: argparse.Namespace,
                        report: dict) -> tuple[dict, dict, dict, dict]:
    health_status, health = _get_json(session, base + "/api/health", "Companion health", timeout=args.timeout)
    if health_status != 200:
        raise AcceptanceFailure(f"Companion health failed (HTTP {health_status})")
    instance = health.get("runtime_instance_id")
    if not isinstance(instance, str) or instance != args.expected_instance_id:
        raise AcceptanceFailure("runtime instance ID did not match the explicitly expected instance")
    components = health.get("components")
    if not isinstance(components, dict) or components.get("jawl") not in {"online", "connected"}:
        raise AcceptanceFailure("native JAWL component is not connected")
    if components.get("jawl_web") != "online":
        raise AcceptanceFailure("native JAWL web control is not online")
    mode = str(health.get("mode") or "").casefold()
    if not mode.startswith("jawl_"):
        raise AcceptanceFailure("active brain mode does not identify the native JAWL runtime")

    session_status, session_data = _get_json(session, base + "/api/session", "Companion session",
                                             timeout=args.timeout)
    csrf = session_data.get("csrf_token")
    cookie = session.cookies.get("companion_session")
    if session_status != 200 or not isinstance(csrf, str) or not csrf or not cookie:
        raise AcceptanceFailure("Companion session bootstrap was incomplete")
    headers = {"Origin": base, "Accept": "application/json", "X-Companion-CSRF": csrf,
               "X-Companion-Session": cookie}

    voice_status, voice = _get_json(session, base + "/api/voice/status", "voice status",
                                     headers=headers, timeout=args.timeout)
    asr = voice.get("asr") if isinstance(voice.get("asr"), dict) else {}
    if voice_status != 200 or asr.get("engine") != "gigaam" or asr.get("status") != "ok":
        raise AcceptanceFailure("canonical GigaAM final-ASR provider is not ready")

    tts_status, tts = _get_json(session, base + "/api/tts/status", "TTS status",
                                 headers=headers, timeout=args.timeout)
    provider_blob = " ".join(str(tts.get(key, "")) for key in ("provider", "model", "name", "engine")).casefold()
    if tts_status != 200 or tts.get("configured") is not True or "tera" not in provider_blob:
        raise AcceptanceFailure("configured TTS identity does not confirm TeraTTS")
    if (not getattr(args, "fake_provider_evidence", False)
            and tts.get("provider") != "TeraTTSHttpClient"):
        raise AcceptanceFailure("TTS provider class is not the canonical TeraTTS HTTP client")

    ambient_status, ambient = _get_json(session, base + "/api/ambient-audio", "ambient audio status",
                                        headers=headers, timeout=args.timeout)
    if ambient_status != 200:
        raise AcceptanceFailure("ambient audio state could not be verified")
    capture = ambient.get("capture") if isinstance(ambient.get("capture"), dict) else {}
    if capture.get("running") is True:
        raise AcceptanceFailure("system-audio loopback capture is active")

    memory_status, memory = _get_json(session, base + "/api/ambient-memory", "ambient memory status",
                                      headers=headers, timeout=args.timeout)
    state = memory.get("state") if isinstance(memory.get("state"), dict) else {}
    if memory_status != 200:
        raise AcceptanceFailure("ambient memory state could not be inspected")

    lease_status, lease = _get_json(session, base + "/api/voice/capture", "voice capture state",
                                    headers=headers, timeout=args.timeout)
    if lease_status != 200 or lease.get("owner") is not None:
        raise AcceptanceFailure("voice capture lease is unavailable or already owned")
    lease_ttl = lease.get("lease_ttl_ms")
    if isinstance(lease_ttl, bool) or not isinstance(lease_ttl, int) or lease_ttl < 1_000:
        raise AcceptanceFailure("voice capture lease TTL was not reported within expected bounds")
    sensory = state.get("sensory") if isinstance(state.get("sensory"), dict) else None
    report["readiness"] = {
        "status": "ready",
        "runtime_identity": {
            "operator_profile_label": args.owned_profile_id,
            "runtime_instance_id": instance,
            "instance_id_matches_operator_expected_value": True,
            "profile_ownership_proven_by_instance_id": False,
        },
        "jawl": components.get("jawl"),
        "jawl_web": components.get("jawl_web"),
        "brain_mode": health.get("mode"),
        "asr_engine": asr.get("engine"),
        "asr_status": asr.get("status"),
        "tts_provider": tts.get("provider"),
        "tts_model": tts.get("model") or tts.get("name"),
        "voice_capture_lease_free": True,
        "voice_capture_lease_ttl_ms": lease_ttl,
        "system_audio_capture_running": capture.get("running") if "running" in capture else None,
        "system_audio_state": "configured" if ambient.get("configured") is True else "not_configured",
        "sensory_journal_reader_running": sensory.get("running") if sensory is not None else None,
    }
    if not getattr(args, "confirm_no_capture", False):
        raise AcceptanceFailure("operator no-capture confirmation is required")
    report["capture_attestation"] = {
        "source": "explicit_operator_confirmation",
        "no_physical_mic_system_audio_or_screen_capture_active": True,
        "runner_opens_audio_devices": False,
        "runner_opens_screen_capture": False,
    }
    return headers, health, voice, tts


class _LeaseKeeper:
    """Renew the production 15-second capture lease while HTTP work is pending."""

    def __init__(self, base: str, headers: dict[str, str], capture_id: str, timeout: float):
        self.base = base
        self.headers = headers
        self.capture_id = capture_id
        self.timeout = min(timeout, 8.0)
        self.stopped = threading.Event()
        self.failure: str | None = None
        self.thread = threading.Thread(target=self._run, name="synthetic-voice-lease-renew", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        client = requests.Session()
        client.trust_env = False
        try:
            while not self.stopped.wait(LEASE_RENEW_INTERVAL_SECONDS):
                try:
                    status, payload = _post_json(
                        client, self.base + "/api/voice/capture",
                        {"action": "renew", "owner": "native", "capture_id": self.capture_id},
                        "capture lease renewal", headers=self.headers, timeout=self.timeout,
                    )
                    if status != 200 or payload.get("owner") != "native":
                        self.failure = "capture lease renewal was rejected"
                        return
                except Exception as exc:  # bounded worker reports a type only
                    self.failure = type(exc).__name__
                    return
        finally:
            client.close()

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=min(10.0, self.timeout + 1.0))
        if self.thread.is_alive():
            self.failure = self.failure or "lease renewal thread did not stop"


def run(args: argparse.Namespace) -> dict:
    base = loopback_url(args.url)
    report: dict = {
        "schema_version": 1,
        "profile": "real_voice_synthetic_acceptance",
        "status": "failed",
        "evidence_class": (
            "fake_provider_production_http_contract"
            if getattr(args, "fake_provider_evidence", False)
            else "real_provider_file_pcm_synthetic_input"
        ),
        "profile_label_operator_supplied": args.owned_profile_id,
        "mode": "GigaAM_to_native_JAWL_to_TeraTTS",
        "input_source": "in_memory_TeraTTS_WAV_resampled_to_PCM16_mono_16k",
        "capture_evidence": "pending_preflight",
        "correlation_id": f"synthetic-accept-{uuid4().hex}",
        "steps": [],
        "failure": None,
    }
    session = requests.Session()
    session.trust_env = False
    capture_id = f"synthetic-{uuid4().hex}"
    session_id = f"synthetic-{uuid4().hex}"
    acquire_attempted = False
    keeper: _LeaseKeeper | None = None
    audio_upload_attempted = False
    finalization_complete = False
    finalization_attempted = False
    run_error: Exception | None = None
    try:
        headers, _health, _voice, _tts = _provider_preflight(session, base, args, report)
        report["capture_evidence"] = "preflight_verified_and_operator_attested"
        report["steps"].append("provider_identity_and_no_capture_preflight")
        pcm, fixture_metrics = _stream_tts(
            session, base, headers, FIXTURE_TEXT, report["correlation_id"], args.timeout,
            pcm_limit=MAX_PCM_BYTES,
        )
        if not pcm or len(pcm) > MAX_PCM_BYTES:
            raise AcceptanceFailure("synthetic speech fixture exceeded duration or PCM bounds")
        report["fixture"] = {**fixture_metrics, "duration_seconds": round(len(pcm) / 2 / SAMPLE_RATE, 3),
                              "source": "configured_real_TeraTTS"}
        report["steps"].append("synthetic_ru_fixture_generated_in_memory")

        acquire_attempted = True
        acquire_status, acquired_data = _post_json(
            session, base + "/api/voice/capture",
            {"action": "acquire", "owner": "native", "capture_id": capture_id},
            "synthetic PCM capture lease", headers=headers, timeout=args.timeout,
        )
        if acquire_status != 200 or acquired_data.get("owner") != "native":
            raise AcceptanceFailure("could not acquire the bounded native PCM upload lease")
        keeper = _LeaseKeeper(base, headers, capture_id, args.timeout)
        keeper.start()
        report["steps"].append("synthetic_pcm_lease_acquired")

        chunk_bytes = int(SAMPLE_RATE * 2 * CHUNK_SECONDS)
        upload_started = time.monotonic()
        upload_count = 0
        audio_upload_attempted = True
        for offset in range(0, len(pcm), chunk_bytes):
            if time.monotonic() - upload_started > args.timeout:
                raise AcceptanceFailure("PCM upload exceeded the bounded upload deadline")
            chunk = pcm[offset:offset + chunk_bytes]
            upload_status, result = _post_json(
                session, base + "/api/voice/audio",
                {"owner": "native", "capture_id": capture_id, "session_id": session_id,
                 "correlation_id": report["correlation_id"], "sample_rate": SAMPLE_RATE,
                 "channels": 1, "pcm16_base64": base64.b64encode(chunk).decode("ascii")},
                "production PCM upload", headers=headers, timeout=args.timeout,
            )
            if upload_status != 200 or result.get("ok") is not True:
                raise AcceptanceFailure(f"production PCM upload failed (HTTP {upload_status})")
            upload_count += 1
        report["timings_ms"] = {"pcm_upload": round((time.monotonic() - upload_started) * 1000)}
        report["pcm"] = {"sample_rate": SAMPLE_RATE, "channels": 1, "sample_format": "s16le",
                          "bytes": len(pcm), "chunks": upload_count}
        report["steps"].append("production_pcm_audio_endpoint")

        end_started = time.monotonic()
        finalization_attempted = True
        end_status, result = _post_json(
            session, base + "/api/voice/end",
            {"owner": "native", "capture_id": capture_id, "session_id": session_id,
             "correlation_id": report["correlation_id"]},
            "production voice finalization", headers=headers, timeout=args.timeout,
        )
        finalization_complete = True
        report["timings_ms"]["voice_end_to_jawl"] = round((time.monotonic() - end_started) * 1000)
        transcript = result.get("transcript")
        if end_status != 200 or result.get("ok") is not True or not isinstance(transcript, str):
            raise AcceptanceFailure("GigaAM finalization did not return a successful transcript")
        if result.get("correlation_id") != report["correlation_id"]:
            raise AcceptanceFailure("voice finalization did not preserve the correlation ID")
        transcript_letters = len(CYRILLIC.findall(transcript))
        if transcript_letters < 8:
            raise AcceptanceFailure("GigaAM transcript did not contain meaningful Russian speech")
        if not any(word in transcript.casefold() for word in ("прибор", "температур")):
            raise AcceptanceFailure("GigaAM transcript did not match the synthetic fixture topic")
        report["transcript"] = {"meaningful_ru": True, "cyrillic_letters": transcript_letters,
                                "length": len(transcript), "fixture_topic_matched": True}
        report["steps"].append("canonical_gigaam_transcript")

        responses = result.get("responses")
        if not isinstance(responses, list) or not responses or not isinstance(responses[0], dict):
            raise AcceptanceFailure("voice finalization returned no JAWL response envelope")
        envelope = responses[0]
        answer = envelope.get("text")
        # A correct one-word answer (e.g. "Термометр." = 9 letters) is valid; the topic
        # keyword check below is the content gate, so only near-empty replies are rejected.
        if not isinstance(answer, str) or len(answer) > 1_600 or len(CYRILLIC.findall(answer)) < 5:
            raise AcceptanceFailure("JAWL response was empty or not a meaningful Russian answer")
        if not any(word in answer.casefold() for word in ("термометр", "градусник")):
            raise AcceptanceFailure("JAWL answer did not address the Russian fixture question")
        if envelope.get("speak") is not True:
            raise AcceptanceFailure("JAWL response did not authorize speech")
        report["jawl_answer"] = {"meaningful_ru": True, "cyrillic_letters": len(CYRILLIC.findall(answer)),
                                 "length": len(answer), "speak": True,
                                 "turn_id_present": bool(envelope.get("turn_id"))}
        report["steps"].append("native_jawl_answer")

        tts_started = time.monotonic()
        _spoken_pcm, spoken_metrics = _stream_tts(
            session, base, headers, answer, report["correlation_id"], args.timeout
        )
        report["timings_ms"]["answer_to_playable_tts"] = round((time.monotonic() - tts_started) * 1000)
        report["playable_tts"] = {**spoken_metrics, "verified": True,
                                  "source": "configured_real_TeraTTS_production_stream"}
        report["steps"].append("playable_non_silent_tts_wav_received")
    except (AcceptanceFailure, OSError, ValueError, requests.RequestException, json.JSONDecodeError) as exc:
        run_error = exc
        report["failure"] = str(exc) if isinstance(exc, AcceptanceFailure) else type(exc).__name__
    finally:
        if keeper is not None:
            keeper.close()
            report["lease_renewal_failure"] = keeper.failure
            if keeper.failure and run_error is None:
                run_error = AcceptanceFailure("capture lease renewal failed")
                report["failure"] = str(run_error)
        if acquire_attempted:
            try:
                release_status, release_data = _post_json(
                    session, base + "/api/voice/capture",
                    {"action": "release", "owner": "native", "capture_id": capture_id},
                    "synthetic PCM lease release", headers=headers, timeout=args.timeout,
                )
                released = release_status == 200 and release_data.get("owner") is None
            except Exception as exc:
                released = False
                report["lease_release_error"] = type(exc).__name__
            report["capture_lease_release_attempted"] = True
            report["capture_lease_released"] = released
            if not released and run_error is None:
                run_error = AcceptanceFailure("synthetic PCM capture lease was not released")
                report["failure"] = str(run_error)
            if run_error is not None and audio_upload_attempted:
                report["pending_pcm_cleanup"] = (
                    "finalization_outcome_unknown; bounded_server_session_ttl_120s"
                    if finalization_attempted and not finalization_complete
                    else "bounded_server_session_ttl_120s"
                    if not finalization_complete
                    else "finalization_completed"
                )
        session.close()
    if run_error is None and report.get("capture_lease_released", True) and not report.get("lease_renewal_failure"):
        report["status"] = "passed"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="explicit existing owned loopback Companion URL")
    parser.add_argument("--owned-profile-id", required=True,
                        help="operator-supplied profile label; not verified by runtime instance ID")
    parser.add_argument("--expected-instance-id", required=True, help="instance ID from fresh read-only health check")
    parser.add_argument("--timeout", type=float, default=90.0, help="per-request bound, 10..180 seconds")
    parser.add_argument("--run-synthetic", action="store_true", help="authorize one synthetic file/PCM turn")
    parser.add_argument("--confirm-no-capture", action="store_true",
                        help="confirm no physical mic, system audio, or screen capture is active")
    args = parser.parse_args(argv)
    if not 10 <= args.timeout <= 180:
        parser.error("--timeout must be between 10 and 180 seconds")
    try:
        loopback_url(args.url)
    except ValueError as exc:
        parser.error(str(exc))
    if not args.run_synthetic or not args.confirm_no_capture:
        parser.error("requires --run-synthetic and --confirm-no-capture")
    if not args.owned_profile_id.strip() or not args.expected_instance_id.strip():
        parser.error("owned profile ID and expected runtime instance ID must be non-empty")
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
