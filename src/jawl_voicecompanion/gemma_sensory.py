"""Experimental CPU-only Gemma 4 E4B sensory describer.

Hikari remains the JAWL brain.  This module only turns a bounded screen frame
and/or a short system-audio window into a small, evidence-tagged observation
for the existing sensor contract.  It never writes raw frames or PCM.
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
import wave
from threading import Event, RLock, Thread
from typing import Any

import requests

OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["scene", "changes", "audio", "uncertainty"],
    "properties": {
        "scene": {"type": "string", "maxLength": 400},
        "changes": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "maxLength": 200},
        },
        "audio": {
            "type": "object",
            "additionalProperties": False,
            "required": ["speech", "speech_lang", "events", "music", "voice_tone", "uncertain"],
            "properties": {
                "speech": {"type": "string", "maxLength": 300},
                "speech_lang": {"type": "string", "enum": ["ru", "en", "other", "unknown"]},
                "events": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {"type": "string", "maxLength": 120},
                },
                "music": {"type": "string", "maxLength": 200},
                "voice_tone": {"type": "string", "maxLength": 200},
                "uncertain": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {"type": "string", "maxLength": 120},
                },
            },
        },
        "uncertainty": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

_SYSTEM_PROMPT = (
    "РўС‹ СЃРµРЅСЃРѕСЂРЅС‹Р№ РѕРїРёСЃР°С‚РµР»СЊ JAWL. РћРїРёС€Рё С‚РѕР»СЊРєРѕ С‚Рѕ, С‡С‚Рѕ РІРёРґРЅРѕ Рё СЃР»С‹С€РЅРѕ РІ "
    "РїРµСЂРµРґР°РЅРЅРѕРј РєР°РґСЂРµ Рё/РёР»Рё Р°СѓРґРёРѕ. Р Р°Р·Р»РёС‡Р°Р№ РЅР°Р±Р»СЋРґРµРЅРёРµ Рё РїСЂРµРґРїРѕР»РѕР¶РµРЅРёРµ. "
    "РќРµ РІС‹РґСѓРјС‹РІР°Р№ СЃСЋР¶РµС‚, РёРјРµРЅР°, СЌРјРѕС†РёРё РёР»Рё РїСЂРёС‡РёРЅСѓ СЃРѕР±С‹С‚РёР№. Р•СЃР»Рё РїСЂРёР·РЅР°Рє "
    "РЅРµСѓРІРµСЂРµРЅРЅС‹Р№, РїРёС€Рё unknown Рё РґРѕР±Р°РІР»СЏР№ РµРіРѕ РІ uncertain. РќРµ РїРµСЂРµСЃРєР°Р·С‹РІР°Р№ "
    "РІРµСЃСЊ РєР°РґСЂ СЃРїРёСЃРєРѕРј; РґР°Р№ РєРѕСЂРѕС‚РєРѕРµ РѕРїРёСЃР°РЅРёРµ СЃС†РµРЅС‹, РёР·РјРµРЅРµРЅРёР№, Р·РІСѓРєРѕРІС‹С… "
    "СЃРѕР±С‹С‚РёР№, РјСѓР·С‹РєР°Р»СЊРЅРѕРіРѕ С„РѕРЅР° Рё СЃР»С‹С€РёРјС‹С… РѕСЃРѕР±РµРЅРЅРѕСЃС‚РµР№ РіРѕР»РѕСЃР°. Р’РµСЂРЅРё РўРћР›Р¬РљРћ "
    "РѕРґРёРЅ JSON-РѕР±СЉРµРєС‚ РїРѕ Р·Р°РґР°РЅРЅРѕР№ СЃС…РµРјРµ, Р±РµР· Markdown, thinking Рё С‚РµРєСЃС‚Р° РїРѕСЃР»Рµ "
    "РЅРµРіРѕ."
)
_USER_PROMPT = (
    "РЎРґРµР»Р°Р№ РѕРґРЅРѕ РєРѕРјРїР°РєС‚РЅРѕРµ РЅР°Р±Р»СЋРґРµРЅРёРµ. Р”Р»СЏ РІРёРґРµРѕ: С‡С‚Рѕ РїСЂРѕРёСЃС…РѕРґРёС‚, РєС‚Рѕ/С‡С‚Рѕ "
    "РІ РєР°РґСЂРµ, С‡С‚Рѕ РёР·РјРµРЅРёР»РѕСЃСЊ. Р”Р»СЏ Р°СѓРґРёРѕ: СЂРµС‡СЊ (РєСЂР°С‚РєРѕ), СЏР·С‹Рє, РЅРµСЂРµС‡РµРІС‹Рµ "
    "СЃРѕР±С‹С‚РёСЏ, РјСѓР·С‹РєР°, РіСЂРѕРјРєРѕСЃС‚СЊ/С‚РµРјРї/С‚РѕРЅ РєР°Рє СЃР»С‹С€РёРјС‹Рµ РїСЂРёР·РЅР°РєРё. "
    "РќРµ Р±РѕР»РµРµ 160 С‚РѕРєРµРЅРѕРІ."
)


def build_request_payload(
    model: str,
    *,
    image_bytes: bytes | None = None,
    audio_wav_bytes: bytes | None = None,
    prompt: str = _USER_PROMPT,
    max_tokens: int = 160,
    temperature: float = 0.2,
    schema: bool = True,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if image_bytes:
        media = "image/jpeg" if image_bytes.startswith(b"\xff\xd8") else "image/png"
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{media};base64,{base64.b64encode(image_bytes).decode('ascii')}"
            },
        })
    if audio_wav_bytes:
        content.append({
            "type": "input_audio",
            "input_audio": {
                "data": base64.b64encode(audio_wav_bytes).decode("ascii"),
                "format": "wav",
            },
        })
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "max_tokens": max(32, min(int(max_tokens), 512)),
        "temperature": max(0.0, min(float(temperature), 1.0)),
        "top_p": 0.9,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "jawl_sensory_observation", "schema": OBSERVATION_SCHEMA},
        }
    return payload


def _bounded(value: Any, limit: int, default: str = "unknown") -> str:
    text = re.sub(r"\s+", " ", str(value or "").replace("\x00", "")).strip()
    return text[:limit] if text else default


def _strict_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("scene"), str) or not isinstance(payload.get("changes"), list):
        return False
    if not isinstance(payload.get("audio"), dict):
        return False
    if not isinstance(payload.get("uncertainty"), (int, float)) or isinstance(payload.get("uncertainty"), bool):
        return False
    return True


def normalize_observation(
    payload: Any,
    *,
    source: str,
    observed_interval: list[float],
    observed_at: float,
    processed_at: float,
    model: str,
    quant: str,
    schema_valid: bool | None = None,
) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    audio = raw.get("audio") if isinstance(raw.get("audio"), dict) else {}
    changes = raw.get("changes") if isinstance(raw.get("changes"), list) else []
    events = audio.get("events") if isinstance(audio.get("events"), list) else []
    uncertain = audio.get("uncertain") if isinstance(audio.get("uncertain"), list) else []
    value = raw.get("uncertainty")
    uncertainty = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.5
    uncertainty = max(0.0, min(uncertainty, 1.0))
    return {
        "schema_version": 1,
        "source": source,
        "observed_interval": [
            round(float(observed_interval[0]), 3),
            round(float(observed_interval[1]), 3),
        ],
        "observed_at": round(float(observed_at), 3),
        "processed_at": round(float(processed_at), 3),
        "age_ms": round(max(0.0, processed_at - observed_at) * 1000.0, 1),
        "scene": _bounded(raw.get("scene"), 400, "unknown scene"),
        "changes": [_bounded(item, 200) for item in changes[:4]],
        "audio": {
            "speech": _bounded(audio.get("speech"), 300, ""),
            "speech_lang": str(audio.get("speech_lang") or "unknown")[:16],
            "events": [_bounded(item, 120) for item in events[:6]],
            "music": _bounded(audio.get("music"), 200),
            "voice_tone": _bounded(audio.get("voice_tone"), 200),
            "uncertain": [_bounded(item, 120) for item in uncertain[:6]],
        },
        "uncertainty": round(uncertainty, 3),
        "model": model,
        "quant": quant,
        "schema_valid": bool(_strict_valid(raw) if schema_valid is None else schema_valid),
        "raw_media_persisted": False,
    }


def _extract_json(text: str) -> Any:
    clean = str(text or "").strip()
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.IGNORECASE)
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object")
    return json.loads(clean[start : end + 1])


class GemmaSensoryClient:
    """Small OpenAI-compatible client for the experimental Gemma server."""

    def __init__(self, base_url: str, *, model: str = "gemma4-e4b", timeout: float = 180.0) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.model = model
        self.timeout = float(timeout)
        self.session = requests.Session()

    def health(self) -> dict[str, Any]:
        response = self.session.get(self.base_url + "/health", timeout=5)
        response.raise_for_status()
        return response.json()

    def describe(
        self,
        *,
        image_bytes: bytes | None = None,
        audio_wav_bytes: bytes | None = None,
        prompt: str = _USER_PROMPT,
        max_tokens: int = 160,
        schema: bool = True,
    ) -> dict[str, Any]:
        payload = build_request_payload(
            self.model,
            image_bytes=image_bytes,
            audio_wav_bytes=audio_wav_bytes,
            prompt=prompt,
            max_tokens=max_tokens,
            schema=schema,
        )
        started = time.perf_counter()
        ttft_ms = None
        text = ""
        reasoning = ""
        usage: dict[str, Any] = {}
        try:
            response = self.session.post(
                self.base_url + "/chat/completions",
                json=payload,
                stream=True,
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                return {
                    "status": "http_error",
                    "http_status": response.status_code,
                    "error": response.text[:500],
                    "ttft_ms": None,
                    "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
                }
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content_piece = delta.get("content")
                reasoning_piece = delta.get("reasoning_content")
                if isinstance(content_piece, str) and content_piece:
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - started) * 1000.0
                    text += content_piece
                elif isinstance(reasoning_piece, str) and reasoning_piece:
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - started) * 1000.0
                    reasoning += reasoning_piece
            total_ms = (time.perf_counter() - started) * 1000.0
            candidates = [text]
            if reasoning and reasoning != text:
                candidates.append(reasoning)
            parsed = None
            parse_error = None
            for candidate in candidates:
                try:
                    parsed = _extract_json(candidate)
                    break
                except Exception as exc:  # noqa: BLE001 - malformed model output is evidence
                    parse_error = exc
            if parsed is not None:
                return {
                    "status": "ok",
                    "payload": parsed,
                    "text": (text or reasoning)[:2000],
                    "reasoning_used": not bool(text),
                    "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
                    "total_ms": round(total_ms, 1),
                    "usage": usage,
                }
            return {
                "status": "invalid_json",
                "error": f"{type(parse_error).__name__}: {parse_error}"[:300],
                "text": (text or reasoning)[:2000],
                "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
                "total_ms": round(total_ms, 1),
                "usage": usage,
            }
        except requests.RequestException as exc:
            return {
                "status": "request_error",
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "ttft_ms": None,
                "total_ms": round((time.perf_counter() - started) * 1000.0, 1),
            }


def pcm16_to_wav(pcm16: bytes, sample_rate: int, channels: int) -> bytes:
    """Convert loopback PCM16 to a bounded 16 kHz mono WAV."""
    if not pcm16:
        return b""
    import numpy as np

    data = np.frombuffer(pcm16, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if sample_rate != 16000 and len(data) > 1:
        target_length = max(1, int(len(data) * 16000 / int(sample_rate)))
        positions = np.linspace(0, len(data) - 1, target_length)
        data = np.interp(positions, np.arange(len(data)), data).astype(np.int16)
    pcm = data.tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(pcm)
    return buffer.getvalue()


class LatestObservation:
    """One running request plus one latest pending observation."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._image: bytes | None = None
        self._image_at = 0.0
        self._audio: bytes | None = None
        self._audio_at = 0.0
        self._image_version = 0
        self._audio_version = 0
        self._last_image_version = 0
        self._last_audio_version = 0
        self.dropped_old = 0
        self.stale = 0

    def update_image(self, image_bytes: bytes, observed_at: float) -> None:
        with self._lock:
            self._image = image_bytes
            self._image_at = observed_at
            self._image_version += 1

    def update_audio(self, wav_bytes: bytes, observed_at: float) -> None:
        with self._lock:
            self._audio = wav_bytes
            self._audio_at = observed_at
            self._audio_version += 1

    def take(self, *, max_age_s: float, sync_s: float = 4.0) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            image_new = self._image is not None and self._image_version != self._last_image_version
            audio_new = self._audio is not None and self._audio_version != self._last_audio_version
            if not image_new and not audio_new:
                return None
            image = self._image
            audio = self._audio
            image_at = self._image_at
            audio_at = self._audio_at
            image_version = self._image_version
            audio_version = self._audio_version
            use_image = image_new and now - image_at <= max_age_s
            use_audio = audio_new and now - audio_at <= max_age_s
            if audio_new and image is not None and abs(image_at - audio_at) <= sync_s:
                use_image = now - image_at <= max_age_s
                use_audio = True
            if not use_image and not use_audio:
                self.stale += 1
                self._last_image_version = max(self._last_image_version, image_version if image_new else 0)
                self._last_audio_version = max(self._last_audio_version, audio_version if audio_new else 0)
                return None
            if use_image:
                self._last_image_version = image_version
            if use_audio:
                self._last_audio_version = audio_version
            return {
                "image": image if use_image else None,
                "audio": audio if use_audio else None,
                "image_at": image_at if use_image else None,
                "audio_at": audio_at if use_audio else None,
                "source": "combined" if use_image and use_audio else "screen" if use_image else "audio",
            }


class GemmaSensoryStream:
    """Bounded live probe around an existing screen/audio capture boundary."""

    def __init__(
        self,
        *,
        client: GemmaSensoryClient,
        screen_capture: Any,
        audio_loopback: Any | None = None,
        target_title: str = "YouTube",
        frame_interval_s: float = 1.0,
        audio_window_s: float = 4.0,
        audio_step_s: float = 2.0,
        max_age_s: float = 8.0,
        change_threshold: float = 0.015,
        output_path: str | None = None,
        quant: str = "q2",
    ) -> None:
        self.client = client
        self.screen_capture = screen_capture
        self.audio_loopback = audio_loopback
        self.target_title = target_title
        self.frame_interval_s = max(0.5, min(float(frame_interval_s), 5.0))
        self.audio_window_s = max(1.0, min(float(audio_window_s), 10.0))
        self.audio_step_s = max(0.5, min(float(audio_step_s), self.audio_window_s))
        self.max_age_s = max(2.0, min(float(max_age_s), 30.0))
        self.change_threshold = max(0.0, min(float(change_threshold), 0.2))
        self.output_path = output_path
        self.quant = quant
        self.events = Event()
        self.stop_event = Event()
        self._threads: list[Thread] = []
        self._latest = LatestObservation()
        self._audio_lock = RLock()
        self._audio_buffer = bytearray()
        self._audio_rate = 0
        self._audio_channels = 0
        self._last_gray: Any = None
        self._count = 0
        self._errors = 0
        self._last_frame: dict[str, Any] = {}
        self._last_error: str | None = None
        self._started_at = time.time()

    @property
    def running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def start(self) -> None:
        if self.running:
            return
        self.stop_event.clear()
        if self.audio_loopback is not None:
            self.audio_loopback.consumer = self._on_audio
            self.audio_loopback.start()
        self._threads = [
            Thread(target=self._video_loop, name="gemma-video", daemon=True),
            Thread(target=self._worker_loop, name="gemma-worker", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self.stop_event.set()
        if self.audio_loopback is not None:
            try:
                self.audio_loopback.stop()
            except Exception:
                pass
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=timeout)
        self._threads = []

    def _on_audio(self, pcm16: bytes, sample_rate: int, channels: int, session_id: str) -> None:
        if not pcm16:
            return
        with self._audio_lock:
            if sample_rate != self._audio_rate or channels != self._audio_channels:
                self._audio_buffer.clear()
                self._audio_rate, self._audio_channels = sample_rate, channels
            self._audio_buffer.extend(pcm16)
            needed = int(self.audio_window_s * sample_rate) * channels * 2
            step = int(self.audio_step_s * sample_rate) * channels * 2
            if len(self._audio_buffer) < needed:
                return
            clip = bytes(self._audio_buffer[:needed])
            del self._audio_buffer[:step]
        wav = pcm16_to_wav(clip, sample_rate, channels)
        if wav:
            self._latest.update_audio(wav, time.time())
            self.events.set()

    def _video_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                observation = (
                    self.screen_capture.observe_window(self.target_title)
                    if hasattr(self.screen_capture, "observe_window")
                    else self.screen_capture.observe()
                )
                if isinstance(observation, dict) and observation.get("status") == "verified":
                    encoded = observation.get("image", {}).get("data_base64")
                    if isinstance(encoded, str) and encoded:
                        image = base64.b64decode(encoded)
                        if self._is_changed(image):
                            self._latest.update_image(image, time.time())
                            self.events.set()
                else:
                    self._errors += 1
                    self._last_error = "screen_capture_unavailable"
            except Exception as exc:  # noqa: BLE001 - probe must stay alive
                self._errors += 1
                self._last_error = f"video: {type(exc).__name__}: {exc}"[:300]
            self.stop_event.wait(self.frame_interval_s)

    def _is_changed(self, image: bytes) -> bool:
        try:
            from PIL import Image
            import numpy as np

            gray = np.asarray(
                Image.open(io.BytesIO(image)).convert("L").resize((32, 32)),
                dtype=np.float32,
            )
            if self._last_gray is None:
                self._last_gray = gray
                return True
            diff = float(np.mean(np.abs(gray - self._last_gray)) / 255.0)
            self._last_gray = gray
            return diff >= self.change_threshold
        except Exception:
            return True

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            self.events.wait(0.5)
            self.events.clear()
            try:
                item = self._latest.take(max_age_s=self.max_age_s)
                if item is None:
                    continue
                observed = [
                    value for value in (item.get("image_at"), item.get("audio_at"))
                    if isinstance(value, (int, float))
                ]
                observed_at = min(observed) if observed else time.time()
                result = self.client.describe(
                    image_bytes=item.get("image"),
                    audio_wav_bytes=item.get("audio"),
                )
                processed_at = time.time()
                if result.get("status") != "ok":
                    self._errors += 1
                    self._last_error = str(result.get("error") or result.get("status"))[:300]
                    self._last_frame = {"status": result.get("status"), "error": self._last_error}
                    continue
                frame = normalize_observation(
                    result["payload"],
                    source=str(item["source"]),
                    observed_interval=[observed_at, observed_at + self.audio_window_s],
                    observed_at=observed_at,
                    processed_at=processed_at,
                    model=self.client.model,
                    quant=self.quant,
                )
                frame["ttft_ms"] = result.get("ttft_ms")
                frame["total_ms"] = result.get("total_ms")
                frame["usage"] = result.get("usage") or {}
                self._count += 1
                self._last_frame = frame
                if self.output_path:
                    with open(self.output_path, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(frame, ensure_ascii=False) + "\n")
            except Exception as exc:  # noqa: BLE001 - probe must stay alive
                self._errors += 1
                self._last_error = f"worker: {type(exc).__name__}: {exc}"[:300]

    def state(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "count": self._count,
            "errors": self._errors,
            "dropped_old": self._latest.dropped_old,
            "stale": self._latest.stale,
            "last_error": self._last_error,
            "last_frame": self._last_frame,
            "started_at": self._started_at,
        }
