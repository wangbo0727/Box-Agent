"""Provider recovery must retain aliases from the prepared request snapshot."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from box_agent.llm import openai_client
from box_agent.retry import RetryConfig
from box_agent.schema import Message
from box_agent.tools.base import Tool, ToolResult
from box_agent.tools.engine.preparation import prepare_tools
from box_agent.tools.schedule_tool import PrepareScheduledTaskTool


class EchoTool(Tool):
    name = "echo_text"
    aliases = ("legacy_echo",)
    description = "Echo a value."
    parameters = {
        "type": "object", "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    async def execute(self, value):
        return ToolResult(success=True, content=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True], ids=["generate", "generate-stream"])
@pytest.mark.parametrize("scheduled", [False, True], ids=["local-alias", "schedule-old-name"])
async def test_provider_recovers_legacy_alias_from_prepared_definitions(monkeypatch, streaming, scheduled):
    tool = PrepareScheduledTaskTool() if scheduled else EchoTool()
    alias = "create_scheduled_task" if scheduled else "legacy_echo"
    arguments = {"name": "Draft", "prompt": "Show a draft"} if scheduled else {"value": "hello"}
    source = f"<tool_call><function={alias}>" + "".join(
        f"<parameter={name}>{value}</parameter>" for name, value in arguments.items()
    ) + "</function></tool_call>"
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=source, tool_calls=None), finish_reason="stop")],
        usage=None,
    )

    async def chunks():
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=source, tool_calls=None), finish_reason="stop",
        )])

    create = AsyncMock(return_value=chunks() if streaming else response)
    monkeypatch.setattr(openai_client, "AsyncOpenAI", lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    ))
    client = openai_client.OpenAIClient(
        api_key="test-only", model="SenseNova-Flash", retry_config=RetryConfig(enabled=False),
    )
    prepared = prepare_tools([tool])
    # Changes after the request was prepared must not silently change the
    # provider's alias interpretation, or add aliases to the wire schema.
    tool.aliases = ()
    messages = [Message(role="user", content="Use the requested tool.")]
    if streaming:
        events = [event async for event in client.generate_stream(messages, list(prepared.definitions))]
        result = next(event for event in events if event.type == "finish")
        assert not any(event.type == "text" for event in events)
    else:
        result = await client.generate(messages, list(prepared.definitions))
        assert result.content == ""
    assert result.finish_reason == "tool_calls"
    assert [(call.function.name, call.function.arguments) for call in result.tool_calls] == [(alias, arguments)]
    normalized = prepared.canonicalize_calls(result.tool_calls)
    assert normalized[0].function.name == tool.name
    assert [item["function"]["name"] for item in create.call_args.kwargs["tools"]] == [tool.name]


def test_prepared_provider_aliases_are_an_immutable_snapshot():
    tool = EchoTool()
    tool.aliases = ["legacy_echo"]
    prepared = prepare_tools([tool])
    tool.aliases.append("later_alias")
    assert prepared.definitions[0].aliases == ("legacy_echo",)
    assert "later_alias" not in prepared.call_names
