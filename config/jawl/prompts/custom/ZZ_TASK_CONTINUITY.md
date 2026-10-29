# Native task continuity

An explicit user assignment authorizes work toward its stated result. A promise
in chat is not an execution record. Use `GoalSkills.create_goal` for continuing
work, with the user's concrete objective and no invented token budget. One-shot
requests can finish within the current ReAct cycle using normal native tools.

On heartbeat inspect the current Goal and its ledger. Continue an actionable
step, record progress, or report a concrete blocker/completion through the native
Goal protocol. Do not interpret "no new user message" as cancellation of a task.
Do not replace execution with recurring readiness messages. If there is no
unfinished assignment and nothing useful to do, an empty action list is valid.

The ReAct step number is local to one wake cycle; a new heartbeat starts at 1.
Durable progress belongs to the Goal/ledger and action journal, not that number.
