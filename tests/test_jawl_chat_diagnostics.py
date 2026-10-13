import threading
from types import SimpleNamespace

import pytest

from jawl_voicecompanion import jawl_web
from jawl_voicecompanion.jawl_web import JawlTurnCancelled, JawlWebChatAdapter, JawlWebUnavailable


def _event(event_type, payload=None):
    return SimpleNamespace(type=event_type, payload=payload or {})


def _race_old_diagnostic(adapter, action, old_status, old_owner):
    attempted = threading.Event()
    release = threading.Event()
    original_set = adapter._set_native_diagnostics
    old_errors = []

    def delayed_set(turn_id, status=None, error=None):
        if turn_id is old_owner and status == old_status:
            attempted.set()
            assert release.wait(2), "test did not release the old diagnostics writer"
        return original_set(turn_id, status, error)

    adapter._claim_native_diagnostics(old_owner)
    adapter._set_native_diagnostics = delayed_set

    def consume_old():
        try:
            action()
        except Exception as exc:  # the old request is expected to terminate
            old_errors.append(exc)

    thread = threading.Thread(target=consume_old)
    thread.start()
    assert attempted.wait(2), "old request did not reach its diagnostic write"
    new_owner = object()
    adapter._claim_native_diagnostics(new_owner)
    adapter._set_native_diagnostics(new_owner, "connected", "B completed")
    release.set()
    thread.join(2)
    assert not thread.is_alive()
    assert old_errors
    assert adapter.last_chat_status == "connected"
    assert adapter.last_chat_error == "B completed"


def test_sync_old_terminal_error_cannot_replace_completed_turn_diagnostics():
    adapter = JawlWebChatAdapter("http://127.0.0.1", native_gateway=True)
    owner = object()
    adapter._iter_native_events = lambda *args: iter([
        _event("turn.error", {"reason": "A failed"}),
    ])

    def old_request():
        adapter._respond_native_serialized("A", None, "turn-A", owner)

    _race_old_diagnostic(adapter, old_request, "offline", owner)


def test_sync_old_cancellation_cannot_replace_completed_turn_diagnostics():
    adapter = JawlWebChatAdapter("http://127.0.0.1", native_gateway=True)
    owner = object()
    adapter._iter_native_events = lambda *args: iter([
        _event("turn.cancelled", {"reason": "A cancelled"}),
    ])

    def old_request():
        adapter._respond_native_serialized("A", None, "turn-A", owner)

    _race_old_diagnostic(adapter, old_request, "cancelled", owner)


def test_stream_old_unsafe_final_cannot_replace_completed_turn_diagnostics(monkeypatch):
    adapter = JawlWebChatAdapter("http://127.0.0.1", native_gateway=True)
    owner = object()
    adapter._new_native_diagnostic_owner = lambda: owner
    adapter._iter_native_events = lambda *args: iter([
        _event("assistant.final", {"response": {"text": "unsafe"}}),
    ])

    def reject_response(_text):
        raise jawl_web.JawlUnsafeResponse("unsafe final")

    monkeypatch.setattr(jawl_web, "filter_user_response", reject_response)

    def old_request():
        list(adapter.stream_envelope("A", correlation_id="turn-A"))

    _race_old_diagnostic(adapter, old_request, "invalid_response", owner)


def test_stream_old_terminal_error_cannot_replace_completed_turn_diagnostics():
    adapter = JawlWebChatAdapter("http://127.0.0.1", native_gateway=True)
    owner = object()
    adapter._new_native_diagnostic_owner = lambda: owner
    adapter._iter_native_events = lambda *args: iter([
        _event("turn.error", {"reason": "A failed"}),
    ])

    def old_request():
        list(adapter.stream_envelope("A", correlation_id="turn-A"))

    _race_old_diagnostic(adapter, old_request, "error", owner)


def test_precancelled_waiter_does_not_claim_or_overwrite_active_owner():
    adapter = JawlWebChatAdapter("http://127.0.0.1", native_gateway=True)
    active_owner = object()
    adapter._claim_native_diagnostics(active_owner)
    adapter._set_native_diagnostics(active_owner, "starting", "A is active")
    assert adapter._native_turn_lock.acquire(timeout=0.1)
    cancelled = threading.Event()
    cancelled.set()
    try:
        with pytest.raises(JawlTurnCancelled):
            adapter.respond_envelope("waiter", cancel_event=cancelled, correlation_id="turn-C")
        assert adapter._native_diagnostic_owner is active_owner
        assert adapter.last_chat_status == "starting"
        assert adapter.last_chat_error == "A is active"
    finally:
        adapter._native_turn_lock.release()


def test_sync_native_error_keeps_offline_status_and_reason_for_current_owner():
    adapter = JawlWebChatAdapter("http://127.0.0.1", native_gateway=True)
    owner = object()
    adapter._new_native_diagnostic_owner = lambda: owner
    adapter._claim_native_diagnostics(owner)
    adapter._iter_native_events = lambda *args: iter([
        _event("turn.error", {"reason": "native failure"}),
    ])

    with pytest.raises(JawlWebUnavailable, match="native failure"):
        adapter.respond_envelope("A", correlation_id="turn-A")

    assert adapter.last_chat_status == "offline"
    assert adapter.last_chat_error == "native failure"


def test_sync_unsafe_final_maps_to_invalid_response_for_current_owner(monkeypatch):
    adapter = JawlWebChatAdapter("http://127.0.0.1", native_gateway=True)
    owner = object()
    adapter._new_native_diagnostic_owner = lambda: owner
    adapter._claim_native_diagnostics(owner)
    adapter._iter_native_events = lambda *args: iter([
        _event("assistant.final", {"response": {"text": "unsafe"}}),
    ])

    def reject_response(_text):
        raise jawl_web.JawlUnsafeResponse("unsafe final")

    monkeypatch.setattr(jawl_web, "filter_user_response", reject_response)
    with pytest.raises(JawlWebUnavailable, match="unsafe Companion response"):
        adapter.respond_envelope("A", correlation_id="turn-A")

    assert adapter.last_chat_status == "invalid_response"
    assert adapter.last_chat_error == "unsafe final"
