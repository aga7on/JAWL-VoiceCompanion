"""Single lifecycle boundary for the JAWL VoiceCompanion runtime.

The runtime is deliberately a composition/lifecycle object, not a second
brain. JAWL remains the authority for identity, goals, canonical memory and
native actions; this object only owns the control/presentation servers and
their shutdown order.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Thread, current_thread
from typing import Any, ClassVar


@dataclass
class CompanionRuntime:
    """Own one control server and its optional read-only presentation server."""

    control: Any
    presentation: Any | None = None
    presentation_thread: Thread | None = None
    _closed: bool = False
    _presentation_closed: bool = False
    _control_closed: bool = False
    PRESENTATION_JOIN_TIMEOUT_SECONDS: ClassVar[float] = 2.0

    def attach_presentation(self, presentation: Any, *, start: bool = True) -> Any:
        """Attach the presentation origin exactly once and optionally start it."""
        if self._closed:
            raise RuntimeError("cannot attach presentation after runtime shutdown")
        if self.presentation is not None:
            raise RuntimeError("presentation server is already attached")
        self.presentation = presentation
        if start:
            thread = Thread(
                target=presentation.serve_forever,
                name="avatar-presentation",
                daemon=True,
            )
            thread.start()
            self.presentation_thread = thread
        return presentation

    def serve_forever(self) -> None:
        """Run the control plane; all adapters remain owned by its server."""
        if self._closed:
            raise RuntimeError("cannot serve a stopped runtime")
        self.control.serve_forever()

    def close(self) -> None:
        """Stop every owned server best-effort, then surface the first error.

        ``close`` is idempotent: a fully stopped runtime returns immediately.
        If a step fails, the remaining steps still run, the runtime stays
        retryable for the parts that are not stopped yet, and the first
        exception is re-raised after every owned server was addressed. The
        control server already owns VoiceMem, ASR, TTS, ambient workers and
        the local HostOS adapter through ``server_close``.
        """
        errors: list[BaseException] = []
        presentation = self.presentation
        presentation_thread = self.presentation_thread
        if presentation is not None and not self._presentation_closed:
            try:
                presentation.shutdown()
            except BaseException as exc:  # noqa: BLE001 - best-effort teardown
                errors.append(exc)
            try:
                presentation.server_close()
            except BaseException as exc:  # noqa: BLE001 - best-effort teardown
                errors.append(exc)
            finally:
                if (
                    presentation_thread is not None
                    and presentation_thread is not current_thread()
                    and presentation_thread.is_alive()
                ):
                    try:
                        presentation_thread.join(
                            timeout=self.PRESENTATION_JOIN_TIMEOUT_SECONDS
                        )
                    except BaseException as exc:  # noqa: BLE001
                        errors.append(exc)
            self._presentation_closed = True
        if not self._control_closed:
            try:
                self.control.server_close()
            except BaseException as exc:  # noqa: BLE001 - best-effort teardown
                errors.append(exc)
            else:
                self._control_closed = True
        self._closed = self._presentation_closed and self._control_closed
        if errors:
            raise errors[0]


__all__ = ["CompanionRuntime"]
