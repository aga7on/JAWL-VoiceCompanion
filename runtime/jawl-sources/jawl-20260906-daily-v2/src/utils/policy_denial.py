"""Attempt-scoped observation of native security-policy denials.

L2 native authority marks the in-flight skill attempt at the exact point it
raises ``PermissionError``, because a skill may swallow the exception before
any higher layer observes it.  The mark itself carries no policy: it only
records that native authority denied something during the current attempt.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, List, Optional

_ATTEMPT: ContextVar[Optional[List[bool]]] = ContextVar(
    "jawl_native_policy_attempt", default=None
)


def observe_native_policy_deny() -> None:
    """Mark the current skill attempt as denied (call at the raise site)."""

    attempt = _ATTEMPT.get()
    if attempt is not None:
        attempt[0] = True


def attempt_denied() -> bool:
    """Whether native authority denied anything during the current attempt."""

    attempt = _ATTEMPT.get()
    return bool(attempt and attempt[0])


@contextmanager
def skill_attempt() -> Iterator[None]:
    """Attempt scope for one skill invocation."""

    attempt = [False]
    token = _ATTEMPT.set(attempt)
    try:
        yield
    finally:
        _ATTEMPT.reset(token)
