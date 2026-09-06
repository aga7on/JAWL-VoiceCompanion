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
