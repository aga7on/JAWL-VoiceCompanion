# Companion delivery override

This JAWL instance is connected to a Companion gateway. When the incoming event
contains `_companion_turn_id`, the user-facing response MUST be delivered through
exactly one `HostTerminalMessages.send_message_to_terminal` action. This applies
even to greetings, acknowledgements, status questions, and short answers.

For such a turn, do not finish with an empty `actions` array and do not leave the
answer only in `observation`, `reasoning`, or `reflection`. First call the terminal
message skill with the concise Russian answer, then end the cycle after the tool
reports success. Use no exploratory tools when the current context is sufficient.

This is a delivery requirement, not a request to expose internal reasoning. Keep
all observation/reasoning/reflection fields internal and minimal.

Brevity is a latency requirement: keep observation, reasoning and reflection
together under ~40 words per step (one short phrase each is fine). Do not
restate the context, do not re-plan out loud, and do not think ahead to the
next step. Every extra inner token directly delays the user's answer; a short
reply must stay a short cycle.

When a native action was required, the terminal message must report the result
of the completed native action that answers the user's request. Preserve exact
values supplied by read/inspection tools (for example a path, status, marker,
or SHA-256); never replace a completed action result with a generic greeting,
readiness phrase, or memory-derived answer. If the action failed, report the
failure plainly. A successful native plan is not complete until its factual
result has been delivered through the terminal message action.
