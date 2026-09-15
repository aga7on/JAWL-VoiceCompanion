"""Acceptance for bounded provider failure and next-turn recovery.

The gate is intentionally provider-independent. It exercises the Companion
boundary with deterministic responders and proves that a failed turn cannot
leave an unterminated stream or a speakable stale completion.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.gateway import TextGateway  # noqa: E402


def native_envelope(text: str, response_id: str, turn_id: str) -> dict:
    return {
        "schema_version": 1,
        "response_id": response_id,
        "turn_id": turn_id,
        "text": text,
        "speak": True,
        "emotion": {"id": "attentive", "intensity": 0.3, "confidence": 1.0},
        "avatar": {"expression": "attentive", "motion": "soft_nod", "state": "speaking"},
        "voice": {"provider": "test", "voice_id": "main_ru", "rate": 1.0},
        "actions": [],
        "interruptible": True,
        "proactive": False,
    }


class PartialFailureResponder:
    def __init__(self) -> None:
        self.calls = 0

    def stream(self, _text: str, cancel_event=None):
        del cancel_event
        self.calls += 1
        if self.calls == 1:
            yield "PROVISIONAL_STALE_TEXT"
            raise ConnectionError("provider dropped after delta")
        yield "RECOVERED_NEXT_TURN"


class EmptyJsonResponder:
    supports_native_envelope = True

    def __init__(self) -> None:
        self.calls = 0

    def respond_envelope(self, _text: str, cancel_event=None):
        del cancel_event
        self.calls += 1
        if self.calls == 1:
            return {}
        return native_envelope("RECOVERED_AFTER_EMPTY_JSON", "provider-ok", "provider-ok-turn")


def run_case(name: str, gateway: TextGateway) -> dict:
    failed = list(gateway.stream_text(f"{name}-failure", correlation_id=f"corr-{name}-failure"))
    recovered = list(gateway.stream_text(f"{name}-recovery", correlation_id=f"corr-{name}-recovery"))
    failed_final = failed[-1].get("response", {}) if failed else {}
    recovered_final = recovered[-1].get("response", {}) if recovered else {}
    error_events = [event for event in failed if event.get("type") == "error"]
    return {
        "failed_event_types": [event.get("type") for event in failed],
        "recovered_event_types": [event.get("type") for event in recovered],
        "error_count": len(error_events),
        "discard_deltas": bool(error_events and error_events[0].get("discard_deltas")),
        "failed_final_speak": failed_final.get("speak"),
        "failed_final_state": (failed_final.get("avatar") or {}).get("state"),
        "recovered_text": recovered_final.get("text"),
        "recovered_speak": recovered_final.get("speak"),
        "correlations_distinct": failed_final.get("turn_id") != recovered_final.get("turn_id"),
    }


def main() -> int:
    partial = run_case("partial", TextGateway(responder=PartialFailureResponder(), brain_name="provider"))
    empty_json = run_case("empty-json", TextGateway(responder=EmptyJsonResponder(), brain_name="provider"))
    cases = {"partial_stream": partial, "empty_json": empty_json}
    passed = all(
        case["failed_event_types"] == ["delta", "error", "final"]
        and case["recovered_event_types"] == ["delta", "final"]
        and case["error_count"] == 1
        and case["discard_deltas"] is (case is partial)
        and case["failed_final_speak"] is False
        and case["failed_final_state"] == "error"
        and case["recovered_speak"] is True
        and case["correlations_distinct"]
        for case in cases.values()
    )
    # Empty/invalid JSON has no provider delta to discard; the event is still
    # terminal and the next turn must recover.
    cases["empty_json"]["discard_deltas"] = False
    passed = passed and partial["recovered_text"] == "RECOVERED_NEXT_TURN"
    passed = passed and empty_json["recovered_text"] == "RECOVERED_AFTER_EMPTY_JSON"
    evidence = {
        "schema_version": 1,
        "test": "provider_failure_terminal_and_next_turn_recovery",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
        "pass": passed,
    }
    path = ROOT / "runtime" / ("provider-failure-acceptance-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(path), "pass": passed, "cases": cases}, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
