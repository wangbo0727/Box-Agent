"""The model and kernel use the same run-scoped tool preparation service."""

from copy import deepcopy
from dataclasses import replace

import pytest

from box_agent.composition import compose_default_kernel_services
from box_agent.core import run_agent_loop
from box_agent.events import ToolCallResult
from box_agent.kernel.loop import AgentLoopKernel
from box_agent.schema import FunctionCall, Message, StreamEvent, ToolCall
from box_agent.tools.base import Tool, ToolResult


class MutableTool(Tool):
    name = "write_record"
    description = "Record a value."

    def __init__(self):
        self.schema = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }
        self.values = []

    @property
    def parameters(self):
        return self.schema

    async def execute(self, value):
        self.values.append(value)
        return ToolResult(success=True, content=value)


def messages():
    return [Message(role="system", content="sys"), Message(role="user", content="record it")]


class MutatingLLM:
    def __init__(self, tool):
        self.tool = tool
        self.requests = 0
        self.request_schema = None

    async def generate_stream(self, messages, tools=None, **kwargs):
        self.requests += 1
        if self.requests == 1:
            self.request_schema = deepcopy(tools[0].to_schema())
            self.tool.schema["properties"]["value"]["type"] = "integer"
            # The request view itself must remain unchanged while execution
            # validates whether its real target still implements that contract.
            assert tools[0].to_schema() == self.request_schema
            yield StreamEvent(type="finish", finish_reason="tool_use", tool_calls=[
                ToolCall(id="record-1", type="function", function=FunctionCall(
                    name="write_record", arguments={"value": "original"},
                )),
            ])
        else:
            yield StreamEvent(type="text", delta="The tool definition changed.")
            yield StreamEvent(type="finish", finish_reason="stop")


@pytest.mark.asyncio
async def test_model_request_keeps_its_schema_and_rejects_changed_definition():
    tool = MutableTool()
    llm = MutatingLLM(tool)
    events = [event async for event in run_agent_loop(
        llm=llm, tools={tool.name: tool}, messages=messages(), max_steps=3,
    )]
    results = [event for event in events if isinstance(event, ToolCallResult)]
    assert len(results) == 1
    assert results[0].success is False
    assert "definition" in (results[0].error or "").lower()
    assert tool.values == []


@pytest.mark.asyncio
async def test_explicit_engine_is_used_and_borrowed_registry_remains_live():
    from box_agent.tools.engine.engine import DefaultToolEngine

    tool = MutableTool()
    registry = {tool.name: tool}

    class QuietLLM:
        async def generate_stream(self, messages, tools=None, **kwargs):
            assert [item.name for item in tools] == ["write_record", "other"]
            yield StreamEvent(type="text", delta="Ready.")
            yield StreamEvent(type="finish", finish_reason="stop")

    class RecordingEngine(DefaultToolEngine):
        calls = 0

        def prepare_tools(self, **kwargs):
            self.calls += 1
            return super().prepare_tools(**kwargs)

    engine = RecordingEngine(tools=registry)
    services = replace(compose_default_kernel_services({"llm": QuietLLM(), "tools": registry}),
                       tool_engine=engine)
    other = MutableTool()
    other.name = "other"
    registry[other.name] = other
    kernel = AgentLoopKernel(_services=services, messages=messages(), max_steps=1)
    _events = [event async for event in kernel.run()]
    assert engine.calls == 1
    assert registry[tool.name] is tool
    assert registry[other.name] is other


def test_default_composition_builds_separate_run_engines_over_same_tools():
    tool = MutableTool()
    registry = {tool.name: tool}
    arguments = {"llm": object(), "tools": registry}
    first = compose_default_kernel_services(arguments)
    second = compose_default_kernel_services(arguments)
    assert first.tool_engine is not second.tool_engine
    assert first.tool_engine.prepare_tools().targets[tool.name] is tool
    assert second.tool_engine.prepare_tools().targets[tool.name] is tool
