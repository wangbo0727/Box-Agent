"""Run-scoped assembly of model input over borrowed session capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .kernel.context_engine import _fallback_context_estimate, skill_reference_budget_chars
from .schema import Message
from .skill_context import SkillReferenceContext
from .tools.base import ToolResult
from .tools.engine.contracts import PreparedTools


@dataclass(frozen=True, slots=True)
class PreparedContext:
    """One request projection; durable history and tool admission stay external."""

    messages: list[Message]
    context_messages: list[Message]
    references: tuple[dict[str, Any], ...] = ()
    input_tokens: int = 0
    request_only_input_tokens: int = 0
    blocked_reason: str | None = None


class DefaultContextEngine:
    """Own request coverage and budgets, borrowing the final resolved services.

    The factory takes no dependencies. Composition binds this run only after
    plugin replacement and Skill/tool source validation have completed.
    """

    def __init__(self) -> None:
        self.references: SkillReferenceContext | None = None
        self.prepared_tools: PreparedTools | None = None
        self._history: list[Message] = []
        self._extra_messages: tuple[Message, ...] = ()
        self._token_limit = 113400
        self._output_tokens = 0
        self._request_reference_tokens = 0
        self._transient_tokens = 0
        self._pending_followup_blocks: list[dict[str, Any]] = []

    def configure_run(self, *, skill_engine: Any = None, session_store: Any = None) -> None:
        self.references = (SkillReferenceContext(skill_engine, session_store=session_store)
                           if skill_engine is not None else None)
        self.prepared_tools = None
        self._history = []

    def bind_history(self, messages: list[Message]) -> None:
        """Observe exact tool history before Kernel may compact it; never edit it."""
        self._history = messages
        if self.references is not None:
            self.references.bind_history(messages)

    @property
    def tool_reader(self):
        return self._read_reference if self.references is not None else None

    def reserve_followup(self, blocks: list[dict[str, Any]]) -> None:
        """Reserve already accepted request-only material during a serial batch."""
        self._pending_followup_blocks.extend(blocks)

    def _read_reference(self, name: str, **arguments: Any) -> ToolResult:
        assert self.references is not None
        self.references.bind_history([*self._history, *self._extra_messages])
        # Tool arguments and earlier committed replies may have been added
        # since preparation. Keep the exact offered schema/admission snapshot.
        calls = next((message.tool_calls for message in reversed(self._history)
                      if message.role == "assistant" and message.tool_calls), ())
        committed = {message.tool_call_id for message in self._history if message.role == "tool"}
        envelopes = [Message(role="tool", name=call.function.name, tool_call_id=call.id, content="")
                     for call in calls if call.id not in committed]
        definitions = self.prepared_tools.definitions if self.prepared_tools is not None else ()
        pending = ([Message(role="user", content=list(self._pending_followup_blocks))]
                   if self._pending_followup_blocks else [])
        available = skill_reference_budget_chars(
            [*self._history, *envelopes, *self._extra_messages, *pending], definitions,
            self._token_limit, self._output_tokens,
        )
        return self.references.read(name, **arguments, budget_chars=max(
            0, available - self._request_reference_tokens * 4,
        ))

    def prepare_request(
        self, messages: list[Message], *, prepared_tools: PreparedTools,
        token_limit: int, output_tokens: int = 0,
        extra_messages: tuple[Message, ...] = (),
        transient_message: Message | None = None, transient_tokens: int = 0,
    ) -> PreparedContext:
        """Project ordinary reference material using the offered tools unchanged."""
        self.bind_history(messages)
        self._pending_followup_blocks = []
        self.prepared_tools = prepared_tools
        self._extra_messages = (*extra_messages, *((transient_message,) if transient_message is not None else ()))
        self._token_limit, self._output_tokens = token_limit, output_tokens
        self._transient_tokens = (max(transient_tokens, _fallback_context_estimate([transient_message], {}))
                                  if transient_message is not None else 0)
        context_messages = [*messages, *extra_messages]
        references: tuple[dict[str, Any], ...] = ()
        self._request_reference_tokens = 0
        blocked_reason = None
        if self.references is not None:
            full_request = ([*context_messages, transient_message]
                            if transient_message is not None else context_messages)
            projection = self.references.prepare_request(
                context_messages,
                budget_chars=skill_reference_budget_chars(
                    full_request, prepared_tools.definitions, token_limit, output_tokens,
                ),
            )
            context_messages, references = projection.messages, projection.references
            blocked_reason = projection.blocked_reason
            self._request_reference_tokens = projection.input_tokens
        provider_messages = ([*context_messages, transient_message]
                             if transient_message is not None else context_messages)
        return PreparedContext(provider_messages, context_messages, references,
                               self._request_reference_tokens,
                               self._request_reference_tokens + self._transient_tokens, blocked_reason)
