"""Keep the existing Skill activation behavior at the tool-result boundary."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..schema import Message
from .skill_preload import build_active_skills_prompt
from .base import Tool, ToolResult


class SkillResultAdapter:
    def __init__(self, messages: list[Message], activator: Callable[[str, str], None] | None):
        self.messages = messages
        self.activator = activator
        self.prompts: dict[str, str] = {}

    def activate(
        self,
        tool: Tool | None,
        arguments: dict[str, Any],
        result: ToolResult,
    ) -> ToolResult:
        """Move a loaded skill from tool history into active system context."""
        skill_name = arguments.get("skill_name")
        if (
            tool is None
            or not getattr(tool, "loads_active_skill_instructions", False)
            or not result.success
            or result.model_context is not None
            or not isinstance(skill_name, str)
            or not skill_name.strip()
            or not result.content.strip()
            or bool((result.raw_output or {}).get("broken"))
        ):
            return result

        normalized_name = skill_name.strip()
        if self.activator is not None:
            self.activator(normalized_name, result.content)
        elif self.messages and self.messages[0].role == "system":
            self.prompts[normalized_name] = result.content
            system_content = (
                self.messages[0].content
                if isinstance(self.messages[0].content, str)
                else str(self.messages[0].content)
            )
            self.messages[0] = Message(
                role="system",
                content=build_active_skills_prompt(
                    system_content,
                    self.prompts,
                ),
            )
        else:
            return result

        acknowledgement = (
            f"Skill '{normalized_name}' loaded into active system instructions. "
            "Follow those instructions for the active task."
        )
        return result.model_copy(update={"model_context": acknowledgement})
