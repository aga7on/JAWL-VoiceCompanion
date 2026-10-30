"""Per-request ONNX cancellation without patching sessions or upstream files."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import copy
from dataclasses import replace
import threading
from typing import Any, Callable, Iterator


class InferenceCancelled(RuntimeError):
    """Only the owning inference request was interrupted."""


class InferenceCancellation(threading.Event):
    """Signal a request and terminate only RunOptions currently owned by it."""

    def __init__(self) -> None:
        super().__init__()
        self._run_lock = threading.Lock()
        self._runs: dict[int, Any] = {}

    def check(self) -> None:
        if self.is_set():
            raise InferenceCancelled("speech inference cancelled")

    def set(self) -> None:
        super().set()
        with self._run_lock:
            for options in self._runs.values():
                options.terminate = True

    def attach(self, options: Any) -> None:
        with self._run_lock:
            self.check()
            self._runs[id(options)] = options

    def detach(self, options: Any) -> None:
        with self._run_lock:
            self._runs.pop(id(options), None)


_current: ContextVar[InferenceCancellation | None] = ContextVar("tts_inference_request", default=None)


@contextmanager
def inference_scope(token: InferenceCancellation) -> Iterator[None]:
    token.check()
    previous = _current.set(token)
    try:
        yield
    finally:
        _current.reset(previous)


class CancellableSession:
    """Proxy the observed Tera/RUAccent synchronous .run interface only."""

    def __init__(self, session: Any, run_options_factory: Callable[[], Any]):
        if not callable(getattr(session, "run", None)):
            raise ValueError("unsupported Tera ONNX session layout")
        self._session = session
        self._options_factory = run_options_factory

    def __getattr__(self, name: str) -> Any:
        if name.startswith("run_"):
            raise AttributeError("Tera cancellation adapter supports synchronous run only")
        return getattr(self._session, name)

    def run(self, output_names: Any, input_feed: Any, run_options: Any = None) -> Any:
        token = _current.get()
        if token is None:
            return self._session.run(output_names, input_feed, run_options)
        if run_options is not None:
            raise ValueError("Tera cancellation adapter must own per-run RunOptions")
        token.check()
        options = self._options_factory()
        token.attach(options)
        try:
            try:
                result = self._session.run(output_names, input_feed, options)
            except Exception:
                token.check()  # translate native termination, not other failures
                raise
            token.check()
            return result
        finally:
            token.detach(options)


def wrap_loaded_tts(loaded: Any, run_options_factory: Callable[[], Any]) -> Any:
    """Copy only runtime owners; cached/shared native sessions stay unchanged.

    Current bundled RUAccent has four neural model holders. Unknown layouts
    fail at startup instead of silently advertising incomplete cancellation.
    """
    sessions = {name: CancellableSession(getattr(loaded, name), run_options_factory)
                for name in ("text_encoder", "duration_predictor", "sampler", "vocoder")}
    accentizer = loaded.accentizer
    if accentizer is not None:
        accentizer = copy(accentizer)
        if accentizer.mode == "full":
            for name in ("accent_model", "omograph_model", "stress_usage", "yo_classifier"):
                holder = copy(getattr(accentizer, name))
                holder.session = CancellableSession(holder.session, run_options_factory)
                setattr(accentizer, name, holder)
        elif accentizer.mode != "dictionary":
            raise ValueError("unsupported RUAccent cancellation layout")
    return replace(loaded, **sessions, accentizer=accentizer)
