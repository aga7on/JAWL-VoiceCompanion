"""Single lifecycle boundary for the JAWL VoiceCompanion runtime.

The runtime is deliberately a composition/lifecycle object, not a second
brain. JAWL remains the authority for identity, goals, canonical memory and
native actions; this object only owns the control server and its shutdown
order. The separate presentation origin was removed in ADR-052 (UI
consolidation): the OBS/pet surface is the single app window in ``?mode=obs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CompanionRuntime:
    """Own one control server and its bounded shutdown sequence."""

    control: Any
    _closed: bool = False
    _control_closed: bool = False
    _sensory_history_flushed: bool = False

    def serve_forever(self) -> None:
        """Run the control plane; all adapters remain owned by its server."""
        if self._closed:
            raise RuntimeError("cannot serve a stopped runtime")
        self.control.serve_forever()

    def close(self) -> None:
        """Stop the owned server best-effort, then surface the first error.

        ``close`` is idempotent: a fully stopped runtime returns immediately.
        If a step fails, the remaining steps still run, the runtime stays
        retryable for the parts that are not stopped yet, and the first
        exception is re-raised after every owned step was addressed. The
        control server already owns VoiceMem, ASR, TTS, ambient workers and
        the local HostOS adapter through ``server_close``.
        """
        errors: list[BaseException] = []
        if not self._control_closed:
            try:
                self.control.server_close()
            except BaseException as exc:  # noqa: BLE001 - best-effort teardown
                errors.append(exc)
            else:
                self._control_closed = True
        # The control server stops the capture/description producers in
        # server_close(). Persist their final text observations only after
        # those producers have been asked to stop, so shutdown cannot race a
        # late history write. SensoryHistoryStore already flushes periodically;
        # this closes the final short interval and surfaces a failed write.
        if not self._sensory_history_flushed:
            history = getattr(self.control, "sensory_history", None)
            flush = getattr(history, "flush", None)
            if callable(flush):
                try:
                    flush_result = flush()
                    if isinstance(flush_result, dict) and flush_result.get("last_error"):
                        raise OSError(str(flush_result["last_error"]))
                except BaseException as exc:  # noqa: BLE001 - keep teardown best-effort
                    errors.append(exc)
                else:
                    self._sensory_history_flushed = True
            else:
                self._sensory_history_flushed = True
        self._closed = self._control_closed
        if errors:
            raise errors[0]


__all__ = ["CompanionRuntime"]
