"""Cancellation must not leave a one-shot grant for another logical call."""

import asyncio

import pytest

from box_agent.core import run_agent_loop
from box_agent.events import ToolCallResult
from box_agent.runtime import invoke_tool_with_permissions
from box_agent.schema import FunctionCall, Message, StreamEvent, ToolCall
from box_agent.tools.skillhub_install_tool import SkillHubInstallTool


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["direct", "serial", "parallel"])
@pytest.mark.parametrize("cancel_at", ["approval", "queued-retry"])
async def test_cancelled_approval_cannot_authorize_the_next_call(monkeypatch, entrypoint, cancel_at):
    candidate = {"id": "fixture-skill", "slug": "fixture", "name": "Fixture"}
    installs = []
    cancelled = False
    approval_returned = False

    async def installer(payload):
        installs.append(payload)
        return {"status": "installed", "skill": {"name": "fixture"}}

    tool = SkillHubInstallTool(
        installer, candidate_provider=lambda skill_id: candidate if skill_id == candidate["id"] else None,
    )
    tool.parallel_safe = entrypoint == "parallel"
    arguments = {"skill_id": candidate["id"]}

    class Approver:
        async def negotiate(self, request):
            nonlocal cancelled, approval_returned
            approval_returned = True
            if cancel_at == "approval":
                cancelled = True
            return True

    # Simulate cancellation after negotiation returned, before the scheduled
    # retry coroutine starts. No tool or permission implementation is replaced.
    original_create_task = asyncio.create_task

    def create_task(coro, *args, **kwargs):
        nonlocal cancelled
        if cancel_at == "queued-retry" and approval_returned:
            cancelled = True
        return original_create_task(coro, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_task", create_task)
    if entrypoint == "direct":
        result, _ = await invoke_tool_with_permissions(
            tool, arguments, permission_negotiator=Approver(), is_cancelled=lambda: cancelled,
        )
    else:
        class Model:
            async def generate_stream(self, messages, tools=None, **kwargs):
                yield StreamEvent(type="finish", finish_reason="tool_use", tool_calls=[
                    ToolCall(id="cancelled-install", type="function", function=FunctionCall(
                        name=tool.name, arguments=arguments,
                    )),
                ])

        events = [event async for event in run_agent_loop(
            llm=Model(), tools={tool.name: tool}, messages=[Message(role="user", content="install")],
            permission_negotiator=Approver(), is_cancelled=lambda: cancelled, max_steps=2,
        )]
        results = [event for event in events if isinstance(event, ToolCallResult)]
        assert len(results) == 1
        result = results[0]

    assert not result.success
    assert installs == []
    monkeypatch.setattr(asyncio, "create_task", original_create_task)
    denials = []

    class Denier:
        async def negotiate(self, request):
            denials.append(request)
            return False

    next_result, decision = await invoke_tool_with_permissions(
        tool, arguments, permission_negotiator=Denier(),
    )
    assert len(denials) == 1, "the cancelled call's grant must not bypass a fresh confirmation"
    assert not next_result.success
    assert decision["decision"] == "denied"
    assert installs == []
