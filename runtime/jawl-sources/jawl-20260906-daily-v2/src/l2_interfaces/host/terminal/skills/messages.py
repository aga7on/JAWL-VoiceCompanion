"""
Host Terminal communication skills.

Allows sending messages directly to the operator's console and reading terminal history.
"""

from typing import Any, Optional

from src.l2_interfaces.host.terminal.client import HostTerminalClient
from src.l3_agent.companion_gateway import current_companion_turn_id
from src.l3_agent.skills.registry import SkillResult, skill


class HostTerminalMessages:
    def __init__(self, client: HostTerminalClient):
        self.client = client

    @skill()
    async def send_message_to_terminal(
        self, text: str, response: Optional[dict[str, Any]] = None
    ) -> SkillResult:
        """
        Sends markdown text to local terminal display.
        """

        try:
            if response is None:
                await self.client.broadcast_message(text)
            else:
                await self.client.broadcast_message(text, response=response)
            # A native Companion turn is complete once its user-facing
            # response was delivered.  Ending the ReAct cycle here prevents a
            # second autonomous step from keeping the single-turn transport
            # slot busy after ``assistant.final`` was emitted.  Legacy terminal
            # messages retain their historic multi-step behaviour.
            return SkillResult.ok("True", terminate_loop=bool(current_companion_turn_id()))

        except Exception as e:
            return SkillResult.fail(f"Error sending to terminal: {e}")

    @skill()
    async def read_terminal_history(self, limit: int = 15) -> SkillResult:
        """
        Returns recent terminal message history.
        """

        try:
            messages = self.client.state.recent_messages
            if not messages:
                return SkillResult.ok("Terminal history is empty.")

            limit = max(1, min(limit, 100))  # Protection against overflow
            recent = messages[-limit:]

            return SkillResult.ok("Terminal history:\n" + "\n".join(recent))
        except Exception as e:
            return SkillResult.fail(f"Error reading terminal history: {e}")
