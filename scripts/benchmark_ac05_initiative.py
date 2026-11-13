"""Measure AC-05 (appropriate initiative) on the real components.

AC-05 as written in JAWL_GOAL.md asks for two things that unit tests cannot
show, because tests only prove thresholds fire in isolation:

  passive mode: 0 unwanted remarks over >= 20 minutes;
  active mode:  >= 80% of expert-marked significant events handled, and
                 <= 2 inappropriate interruptions in 30 minutes.

This harness drives the real gates (``AttentionPresence`` for screen initiative,
``ProactiveFeed`` for spoken initiative) with a labeled event stream and reports
the counts with their denominators. It never invents events: each case is
constructed here with an explicit expectation, so a pass or fail is auditable.

Usage:
    python -X utf8 scripts/benchmark_ac05_initiative.py --report runtime/instances/ac05_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jawl_voicecompanion.attention import AttentionPresence  # noqa: E402
from jawl_voicecompanion.proactive import ProactiveFeed  # noqa: E402


# --- Screen-initiative cases -------------------------------------------------
# (summary, significance, expectation, why)
# expectation: "must_propose" = a genuinely significant event the companion
# should surface; "must_stay_silent" = noise, private text, or a non-event.
SCREEN_CASES: list[tuple[str, int, str, str]] = [
    ("Появилась ошибка в редакторе кода", 3, "must_propose", "actionable failure"),
    ("Сборка проекта завершилась с ошибкой компиляции", 3, "must_propose", "actionable failure"),
    ("Терминал: Permission denied при записи файла", 3, "must_propose", "blocking error"),
    ("Скачался файл отчёта", 1, "must_stay_silent", "low salience, expected"),
    ("Открылась новая вкладка браузера", 1, "must_stay_silent", "low salience"),
    ("Курсор переместился в другой угол", 1, "must_stay_silent", "no meaning"),
    ("Изменился заголовок окна мессенджера", 1, "must_stay_silent", "routine"),
    ("Введите пароль: password field focused", 3, "must_stay_silent", "private content"),
    ("Токен авторизации sk-live-9f2c показан на экране", 3, "must_stay_silent", "secret"),
    ("Список файлов прокручен вниз", 2, "must_stay_silent", "navigation, not an event"),
    ("Уведомление: обновление доступно", 2, "must_stay_silent", "not urgent"),
    ("Тест упал: AssertionError в test_parser", 3, "must_propose", "actionable failure"),
    ("Мигает индикатор записи", 1, "must_stay_silent", "ambient noise"),
    ("Закончилось место на диске C:", 3, "must_propose", "actionable failure"),
    ("Открылся диалог подтверждения удаления", 3, "must_propose", "needs attention"),
]


def _screen_phase(
    *, active_user: bool, dnd: bool, label: str
) -> dict[str, Any]:
    """Run every screen case through the real gate in one configuration."""
    delivered: list[dict[str, Any]] = []
    attention = AttentionPresence(
        cooldown_seconds=0.0,
        budget_per_hour=100,
        dnd=dnd,
        intent_sink=delivered.append,
        activity_provider=(
            (lambda: {"status": "verified", "user_active": active_user})
            if active_user is not None
            else None
        ),
    )
    decisions = []
    for index, (summary, significance, expectation, why) in enumerate(SCREEN_CASES):
        result = attention.consume(
            {
                "type": "SCREEN_DELTA",
                "event_id": f"{label}:{index}",
                "payload": {"changed": True, "summary": summary, "significance": significance},
            }
        )
        proposed = result.get("status") == "proposed"
        decisions.append(
            {
                "summary": summary,
                "expectation": expectation,
                "status": result.get("status"),
                "reason": result.get("reason"),
                "proposed": proposed,
                "why": why,
            }
        )
    correct = sum(
        1
        for d in decisions
        if (d["expectation"] == "must_propose") == d["proposed"]
    )
    return {
        "label": label,
        "active_user": active_user,
        "dnd": dnd,
        "cases": len(decisions),
        "correct": correct,
        "accuracy": round(correct / len(decisions), 4),
        "false_interruptions": sum(
            1 for d in decisions if d["expectation"] == "must_stay_silent" and d["proposed"]
        ),
        "missed_significant": sum(
            1 for d in decisions if d["expectation"] == "must_propose" and not d["proposed"]
        ),
        "delivered_count": len(delivered),
        "decisions": decisions,
    }


class _FakeJawl:
    """Stand-in for the JAWL history client; returns queued rows on demand."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def chat_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.rows[-limit:]


class _FakeHistory:
    """Conversation history used for the idle gate and active-hours learning."""

    def __init__(self) -> None:
        self._turns: list[dict[str, Any]] = []

    def note_turn(self, when: float) -> None:
        stamp = datetime.fromtimestamp(when, timezone.utc).isoformat()
        self._turns.append({"created_at": stamp, "user": "вопрос", "response": {"text": "ответ"}})

    def turns(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._turns[-limit:]


def _spoken_phase(
    *, minutes: float, expect_delivery: bool, idle: bool, label: str
) -> dict[str, Any]:
    """Drive the spoken-initiative gate over a simulated timeline.

    ``minutes`` of wall time are simulated at 12 s poll resolution, which is the
    production poll interval, so rate limiting and idle gating behave as they do
    live. One initiative message arrives every 2 minutes of the window.
    """
    client = _FakeJawl()
    history = _FakeHistory()
    feed = ProactiveFeed(
        client, history=history, poll_interval_s=12.0, min_gap_s=300.0, max_per_hour=6
    )
    base = 1_700_000_000.0
    feed.poll(now=base)  # seed: existing history is not initiative

    polls = int(minutes * 60 / 12)
    arrivals = 0
    delivered = 0
    for step in range(1, polls + 1):
        now = base + step * 12.0
        if step % 10 == 0:  # every 2 minutes
            arrivals += 1
            stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            client.rows.append(
                {"sender": "Companion", "text": f"наблюдение номер {arrivals}", "time": stamp}
            )
        if not idle:
            # The user keeps talking, so the idle gate must hold delivery back.
            history.note_turn(now)
        delivered += len(feed.poll(now=now))
    state = feed.state(now=base + minutes * 60)
    return {
        "label": label,
        "minutes": minutes,
        "idle": idle,
        "expect_delivery": expect_delivery,
        "initiative_messages": arrivals,
        "delivered": delivered,
        "queued": len(state["queued"]),
        "suppressed_duplicates": state["suppressed_duplicates"],
        "suppressed_unusable": state["suppressed_unusable"],
        "delivered_per_30min": round(delivered / max(minutes, 1e-9) * 30.0, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default=str(ROOT / "runtime" / "instances" / "ac05_report.json"))
    parser.add_argument("--passive-minutes", type=float, default=20.0)
    parser.add_argument("--active-minutes", type=float, default=30.0)
    args = parser.parse_args()

    began = time.time()

    # Screen initiative: baseline, user busy, and DND.
    screen_baseline = _screen_phase(active_user=False, dnd=False, label="screen_idle_user")
    screen_busy = _screen_phase(active_user=True, dnd=False, label="screen_user_active")
    screen_dnd = _screen_phase(active_user=False, dnd=True, label="screen_dnd")
    # Above, active_user=False means "provider present, user not active".

    # Spoken initiative: idle window delivers nothing unwanted; a user turn
    # within the idle window must suppress delivery.
    spoken_passive = _spoken_phase(
        minutes=args.passive_minutes, expect_delivery=False, idle=False, label="spoken_user_talking"
    )
    spoken_active = _spoken_phase(
        minutes=args.active_minutes, expect_delivery=True, idle=True, label="spoken_user_idle"
    )

    passive_windows = [screen_busy, screen_dnd, spoken_passive]
    failures: list[str] = []

    # AC-05 passive requirement: 0 unwanted remarks.
    if screen_busy["false_interruptions"]:
        failures.append(
            f"user-active screen gate proposed {screen_busy['false_interruptions']} interruptions"
        )
    if screen_dnd["false_interruptions"]:
        failures.append(f"DND screen gate proposed {screen_dnd['false_interruptions']} interruptions")
    if spoken_passive["delivered"]:
        failures.append(
            f"spoken gate delivered {spoken_passive['delivered']} messages while the user was talking"
        )

    # AC-05 active requirement: significant events handled, few interruptions.
    if screen_baseline["false_interruptions"]:
        failures.append(
            f"baseline screen gate fired on {screen_baseline['false_interruptions']} non-events"
        )
    significant = sum(1 for _, _, e, _ in SCREEN_CASES if e == "must_propose")
    handled = sum(
        1
        for d in screen_baseline["decisions"]
        if d["expectation"] == "must_propose" and d["proposed"]
    )
    coverage = handled / max(significant, 1)
    if coverage < 0.80:
        failures.append(f"significant-event coverage {coverage:.1%} is below the 80% target")
    if not spoken_active["delivered"]:
        failures.append("spoken gate delivered nothing in a genuinely idle window")

    report = {
        "acceptance_id": "AC-05",
        "scope": "component_gates_automated",
        "status": "PASS" if not failures else "FAILED",
        "failures": failures,
        "hardware": "local CPU (no GPU use)",
        "parameters": {
            "screen_cases": len(SCREEN_CASES),
            "passive_minutes": args.passive_minutes,
            "active_minutes": args.active_minutes,
        },
        "screen": {
            "baseline_idle": screen_baseline,
            "user_active": screen_busy,
            "dnd": screen_dnd,
        },
        "spoken": {"user_talking": spoken_passive, "user_idle": spoken_active},
        "metrics": {
            "significant_events": significant,
            "significant_handled": handled,
            "significant_coverage": round(coverage, 4),
            "false_interruptions_user_active": screen_busy["false_interruptions"],
            "false_interruptions_dnd": screen_dnd["false_interruptions"],
            "false_interruptions_baseline": screen_baseline["false_interruptions"],
            "unwanted_spoken_passive": spoken_passive["delivered"],
            "delivered_per_30min_idle": spoken_active["delivered_per_30min"],
        },
        "criteria": {
            "passive_zero_unwanted": (
                screen_busy["false_interruptions"] == 0
                and screen_dnd["false_interruptions"] == 0
                and spoken_passive["delivered"] == 0
            ),
            "active_coverage_ge_80pct": coverage >= 0.80,
            "active_delivers_when_idle": spoken_active["delivered"] > 0,
        },
        "known_limits": [
            "Gates are driven directly; the live stack was not observed for a real "
            "20-30 minute owner session.",
            "Screen cases are labeled by this harness, not by an independent expert.",
            "Event significance values are supplied by the caller, matching how the "
            "Qwen sensor tags observations in production.",
        ],
        "elapsed_s": round(time.time() - began, 1),
    }

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 58)
    print("  AC-05 Initiative Measurement")
    print("=" * 58)
    print(f"Status: {report['status']}")
    print(
        f"Significant coverage: {handled}/{significant} "
        f"({coverage:.1%})   target >= 80%"
    )
    print(
        "False interruptions: "
        f"user-active={screen_busy['false_interruptions']} "
        f"dnd={screen_dnd['false_interruptions']} "
        f"baseline={screen_baseline['false_interruptions']}"
    )
    print(f"Spoken while user talks: {spoken_passive['delivered']} (target 0)")
    print(
        f"Spoken when idle: {spoken_active['delivered']} over "
        f"{args.active_minutes:.0f} min "
        f"({spoken_active['delivered_per_30min']}/30min, max 6/hour)"
    )
    if failures:
        print("Failures:")
        for item in failures:
            print(f"  - {item}")
    print(f"Report: {out}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())