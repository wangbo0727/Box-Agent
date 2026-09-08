"""Permission attempts preserve a model call's live progress and final reply."""

import asyncio

import pytest

from box_agent.core import run_agent_loop
from box_agent.events import ToolCallResult, ToolCallStart
from box_agent.schema import FunctionCall, Message, StreamEvent, ToolCall
from box_agent.tools.base import EventEmittingTool, Tool, ToolResult


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_approval_stream_reaches_consumer_before_effect_finishes(parallel):
    released = asyncio.Event()
    progress = {"phase": "approved-and-running"}
    contexts = []

    class GatedTool(EventEmittingTool):
        name = "gated_progress"
        description = "A controlled effect behind two permission gates."
        parameters = {"type": "object", "properties": {}}
        parallel_safe = parallel
        attempts = 0
        effects = 0

        async def execute(self):
            self.attempts += 1
            contexts.append((self._event_queue is not None, self._parent_tool_call_id))
            if self.attempts < 3:
                return ToolResult(
                    success=False,
                    permission_request={"scope": "fixture", "requested_scope": str(self.attempts)},
                )
            assert self._event_queue is not None
            self._event_queue.put_nowait(progress)
            await released.wait()
            self.effects += 1
            return ToolResult(success=True, content="effect completed")

    class Approver:
        requests = []

        async def negotiate(self, request):
            self.requests.append(request["requested_scope"])
            return True

    class Model:
        requests = 0

        async def generate_stream(self, messages, tools=None, **kwargs):
            self.requests += 1
            if self.requests == 1:
                yield StreamEvent(type="finish", finish_reason="tool_use", tool_calls=[
                    ToolCall(id="logical-call", type="function", function=FunctionCall(
                        name="gated_progress", arguments={},
                    )),
                ])
            else:
                yield StreamEvent(type="text", delta="Done.")
                yield StreamEvent(type="finish", finish_reason="stop")

    tool, approver = GatedTool(), Approver()
    events = []

    async def consume():
        async for event in run_agent_loop(
            llm=Model(), tools={tool.name: tool},
            messages=[Message(role="system", content="sys"), Message(role="user", content="go")],
            permission_negotiator=approver, max_steps=3,
        ):
            events.append(event)
            if event is progress:
                assert tool.effects == 0
                released.set()

    await asyncio.wait_for(consume(), timeout=3)
    assert progress in events
    assert tool.attempts == 3
    assert tool.effects == 1
    assert contexts == [(True, "logical-call")] * 3
    assert approver.requests == ["1", "2"]
    assert len([event for event in events if isinstance(event, ToolCallStart)]) == 1
    results = [event for event in events if isinstance(event, ToolCallResult)]
    assert len(results) == 1
    assert results[0].success
    assert results[0].policy_decision["retry_count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_cancellation_during_approval_does_not_start_another_attempt(parallel):
    from box_agent.events import DoneEvent, StopReason

    cancelled = False

    class Gated(Tool):
        name = "gated"
        description = "Perform an effect only after approval."
        parameters = {"type": "object", "properties": {}}
        parallel_safe = parallel
        attempts = 0
        effects = 0

        async def execute(self):
            self.attempts += 1
            if self.attempts == 1:
                return ToolResult(success=False, permission_request={"scope": "fixture"})
            self.effects += 1
            return ToolResult(success=True, content="effect done")

    class Approver:
        async def negotiate(self, request):
            nonlocal cancelled
            cancelled = True
            return True

    class Model:
        async def generate_stream(self, messages, tools=None, **kwargs):
            yield StreamEvent(type="finish", finish_reason="tool_use", tool_calls=[
                ToolCall(id="cancelled-call", type="function", function=FunctionCall(name="gated", arguments={})),
            ])

    tool = Gated()
    events = [event async for event in run_agent_loop(
        llm=Model(), tools={tool.name: tool}, messages=[Message(role="user", content="go")],
        permission_negotiator=Approver(), is_cancelled=lambda: cancelled, max_steps=2,
    )]
    assert tool.attempts == 1
    assert tool.effects == 0
    assert len([event for event in events if isinstance(event, ToolCallResult)]) == 1
    assert any(isinstance(event, DoneEvent) and event.stop_reason == StopReason.CANCELLED for event in events)
