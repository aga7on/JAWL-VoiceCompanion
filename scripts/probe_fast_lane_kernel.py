"""Reproduce the kernel fast-lane decision for a real Companion turn.

Direct calls showed is_conversational_text works, and the adapter sends turn_id.
So either the turn state is not bound, or another gate rejects the slimming.
This probe drives the real envelope policy with the same shapes JAWL builds.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" / "jawl-sources" / "jawl-20260906-daily-v2"
sys.path.insert(0, str(SOURCE))
os.environ["JAWL_FAST_CONVERSATION"] = "1"

from src.l3_agent import companion_gateway  # noqa: E402
from src.l3_agent.llm import envelope_policy  # noqa: E402

UTTERANCE = "Какой сегодня статус моего проекта?"
TURN_ID = "turn-voice-probe-1"

# Mimic what the ReAct loop binds: a correlated turn with the raw message.
state = companion_gateway.CompanionTurnState(UTTERANCE, lambda: False)
token = companion_gateway.bind_companion_turn_state(state)
turn_token = companion_gateway.set_companion_turn_id(TURN_ID)

big_system = "S" * 9000
messages = [
    {"role": "system", "content": big_system},
    {"role": "user", "content": UTTERANCE + "\n\n[PERCEPTION]\nнекоторый блок"},
]

print("bound turn state:", companion_gateway.current_companion_turn_state() is not None)
print("current turn id:", companion_gateway.current_companion_turn_id())
print("utterance:", UTTERANCE)
print("system chars before:", len(big_system))

slimmed = envelope_policy._fast_lane_messages(list(messages))
if slimmed is None:
    print("RESULT: fast lane NOT applied (returned None)")
else:
    print("RESULT: fast lane applied")
    for index, message in enumerate(slimmed):
        print(f"  [{index}] {message['role']}: {len(message['content'])} chars")
        print(f"      head: {message['content'][:90]!r}")

companion_gateway.reset_companion_turn_id(turn_token)
companion_gateway.reset_companion_turn_state(token)