"""Async event-driven Qwen describer with an honest observation age.

Qwen returns one plain-text sentence.  The code owns the envelope: caption,
observed_at, processed_at, age_ms, stale, source and event_id.  No JSON is
requested from the model, no OCR is requested and no audio is sent.
"""

from __future__ import annotations

import base64
import json
import queue
import time
from dataclasses import dataclass
from threading import Event, Lock, Thread, current_thread
from typing import Any, Callable

import requests

DEFAULT_PROMPT = (
    "Describe this video frame in one sentence. Name visible objects and actions. "
    "Do not transcribe on-screen text. Do not mention audio. Plain text only, no JSON."
)


@dataclass(frozen=True)
class QwenEventObservation:
    caption: str
    observed_at: float
    processed_at: float
    age_ms: float
    stale: bool
    source: str
    event_id: str
    model: str
    budget: int
    truncated: bool
    frame_id: str = ""
    scene_id: str = ""
    roi: tuple[float, float, float, float] | None = None
    captured_monotonic: float = 0.0


class QwenEventDescriber:
    """One background worker, one latest pending frame, explicit age/stale."""

    def __init__(
        self,
        base_url: str,
        *,
        model: str = "qwen3.5-0.8b",
        max_age_s: float = 6.0,
        timeout: float = 120.0,
        transport: Callable[[dict[str, Any]], tuple[str, bool]] | None = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.model = model
        self.max_age_s = max(0.5, float(max_age_s))
        self.timeout = float(timeout)
        self._transport = transport or self._http_transport
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._lock = Lock()
        self._stop = Event()
        self._thread = Thread(target=self._loop, name="qwen-event-describer", daemon=True)
        self._restart_requested = False
        self._latest: QwenEventObservation | None = None
        self._count = 0
        self._errors = 0
        self._dropped = 0
        self._last_error: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                # stop(timeout) is deliberately bounded. If an HTTP transport
                # outlives that join, revive the existing worker in place
                # instead of returning with its stop flag still set (which
                # would make it exit as soon as the transport unblocks).
                if self._stop.is_set():
                    self._restart_requested = True
                self._stop.clear()
                return
            self._stop.clear()
            self._restart_requested = False
            self._thread = Thread(target=self._loop, name="qwen-event-describer", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def submit(
        self,
        image_bytes: bytes,
        *,
        observed_at: float | None = None,
        source: str = "screen",
        event_id: str = "",
        frame_id: str = "",
        scene_id: str = "",
        roi: tuple[float, float, float, float] | None = None,
        captured_monotonic: float | None = None,
    ) -> bool:
        if not image_bytes:
            return False
        observed_at_value = float(observed_at if observed_at is not None else time.time())
        captured_monotonic_value = (
            float(captured_monotonic)
            if captured_monotonic is not None
            else time.monotonic() - max(0.0, time.time() - observed_at_value)
        )
        item = {
            "image": bytes(image_bytes),
            "observed_at": observed_at_value,
            "source": str(source)[:64],
            "event_id": str(event_id)[:64],
            "frame_id": str(frame_id)[:64],
            "scene_id": str(scene_id)[:64],
            "roi": tuple(float(value) for value in roi) if roi is not None else None,
            "captured_monotonic": captured_monotonic_value,
        }
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(item)
                with self._lock:
                    self._dropped += 1
                return True
            except queue.Full:
                return False

    def poll(self) -> QwenEventObservation | None:
        with self._lock:
            return self._latest

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "count": self._count,
                "errors": self._errors,
                "dropped": self._dropped,
                "last_error": self._last_error,
                "latest": self._latest,
            }

    def _loop(self) -> None:
        try:
            while True:
                with self._lock:
                    if self._stop.is_set():
                        break
                    self._restart_requested = False
                try:
                    item = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    caption, truncated = self._transport(self._payload(item["image"], self.model, 64))
                    budget = 64
                    if truncated:
                        caption, truncated = self._transport(self._payload(item["image"], self.model, 128))
                        budget = 128
                    processed_at = time.time()
                    age_ms = max(
                        0.0,
                        time.monotonic() - float(item["captured_monotonic"]),
                    ) * 1000.0
                    observation = QwenEventObservation(
                        caption=str(caption).strip(),
                        observed_at=float(item["observed_at"]),
                        processed_at=processed_at,
                        age_ms=round(age_ms, 1),
                        stale=age_ms > self.max_age_s * 1000.0,
                        source=item["source"],
                        event_id=item["event_id"],
                        model=self.model,
                        budget=int(budget),
                        truncated=bool(truncated),
                        frame_id=str(item.get("frame_id") or ""),
                        scene_id=str(item.get("scene_id") or ""),
                        roi=item.get("roi"),
                        captured_monotonic=float(item.get("captured_monotonic") or 0.0),
                    )
                    with self._lock:
                        self._latest = observation
                        self._count += 1
                except Exception as exc:  # noqa: BLE001 - worker must stay alive
                    with self._lock:
                        self._errors += 1
                        self._last_error = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            restart_thread: Thread | None = None
            with self._lock:
                if self._thread is current_thread():
                    self._thread = None
                    if self._restart_requested:
                        self._restart_requested = False
                        self._stop.clear()
                        restart_thread = Thread(
                            target=self._loop,
                            name="qwen-event-describer",
                            daemon=True,
                        )
                        self._thread = restart_thread
            if restart_thread is not None:
                restart_thread.start()

    @staticmethod
    def _payload(image_bytes: bytes, model: str, max_tokens: int = 64) -> dict[str, Any]:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": DEFAULT_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                        },
                    ],
                }
            ],
            "max_tokens": int(max_tokens),
            "temperature": 0.0,
            "top_p": 0.9,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
            "cache_prompt": False,
        }

    def _http_transport(self, payload: dict[str, Any]) -> tuple[str, bool]:
        text = ""
        finish_reason = None
        response = requests.post(
            self.base_url + "/chat/completions",
            json=payload,
            stream=True,
            timeout=self.timeout,
        )
        response.raise_for_status()
        for raw in response.iter_lines(decode_unicode=False):
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            choice = (event.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                text += piece
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
        stripped = text.strip()
        truncated = finish_reason == "length" or (
            bool(stripped) and not stripped.endswith((".", "!", "?")) and finish_reason is None
        )
        return stripped, truncated
