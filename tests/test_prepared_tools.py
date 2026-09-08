"""One model request binds immutable definitions to the original tools."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from threading import Lock

import pytest

from box_agent.cache_fingerprint import build_cache_fingerprint
from box_agent.schema import FunctionCall, ToolCall
from box_agent.tools.base import Tool, ToolResult
from box_agent.tools.engine.preparation import prepare_tools
from box_agent.tools.mcp_tool_catalog import MCPToolCatalog
from box_agent.tools.mcp_tool_search import MCPToolExposureManager


class MutableTool(Tool):
    aliases = ("old_echo",)

    def __init__(self, name: str = "echo_text") -> None:
        self._name = name
        self._description = "Echo a value"
        self._parameters = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        }
        self.extension = {"version": [1]}
        self.lock = Lock()
        self.calls: list[str] = []
        self.state = "before"

    def __deepcopy__(self, memo):
        raise AssertionError("Never clone a live tool")

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return self._description

    @property
    def parameters(self):
        return self._parameters

    def to_schema(self):
        return {**super().to_schema(), "custom_anthropic": self.extension}

    def to_openai_schema(self):
        schema = super().to_openai_schema()
        schema["function"]["strict"] = True
        schema["custom_openai"] = self.extension
        return schema

    def compaction_state(self):
        return "Echo state", self.state

    async def execute(self, value):
        self.calls.append(value)
        return ToolResult(success=True, content=value)


class MCPTool(MutableTool):
    aliases = ()

    def __init__(self, *, always_load=True):
        super().__init__("remote_echo")
        self._server_name = "echo-server"
        self._remote_name = "echo"
        self._mcp_generation = 0
        self.mcp_always_load = always_load

    @property
    def server_name(self):
        return self._server_name

    @property
    def remote_name(self):
        return self._remote_name

    @property
    def mcp_tool_id(self):
        return f"mcp:{self.server_name}/{self.name}"

    @property
    def mcp_generation(self):
        return self._mcp_generation


def test_definitions_preserve_actual_custom_schemas_without_copying_live_tools():
    tool = MutableTool()
    expected = deepcopy((tool.parameters, tool.to_schema(), tool.to_openai_schema()))

    prepared = prepare_tools([tool])
    definition = prepared.definitions[0]
    tool._parameters["required"].append("later")
    tool.extension["version"].append(2)

    assert definition.name == "echo_text"
    assert definition.description == "Echo a value"
    assert (
        definition.parameters, definition.to_schema(), definition.to_openai_schema()
    ) == expected
    assert prepared.targets["echo_text"] is tool
    assert not hasattr(definition, "invoke")
    assert not hasattr(definition, "execute")


def test_definition_access_cannot_mutate_later_provider_requests():
    prepared = prepare_tools([MutableTool()])
    definition = prepared.definitions[0]
    expected = deepcopy(
        (definition.parameters, definition.to_schema(), definition.to_openai_schema())
    )

    definition.parameters["required"].clear()
    definition.to_schema()["custom_anthropic"]["version"].append(9)
    definition.to_openai_schema()["function"]["parameters"].clear()

    assert (
        definition.parameters, definition.to_schema(), definition.to_openai_schema()
    ) == expected
    assert prepared.validate_call("echo_text") is None
    with pytest.raises(TypeError):
        prepared.targets["echo_text"] = MutableTool()
    with pytest.raises(TypeError):
        prepared.call_names["old_echo"] = "different"


def test_alias_normalization_preserves_original_calls_and_nested_arguments():
    tool = MutableTool()
    prepared = prepare_tools([tool])
    calls = [
        ToolCall(
            id="c1", type="function",
            function=FunctionCall(name="old-echo", arguments={"nested": [1]}),
        ),
        ToolCall(id="c2", type="function", function=FunctionCall(name="unknown", arguments={})),
    ]

    normalized = prepared.canonicalize_calls(calls)
    normalized[0].function.arguments["nested"].append(2)
    tool.aliases = ("new_name",)

    assert [call.function.name for call in normalized] == ["echo_text", "unknown"]
    assert calls[0].function.name == "old-echo"
    assert calls[0].function.arguments == {"nested": [1]}
    assert prepared.call_names["echo-text"] == "echo_text"
    assert prepared.validate_call("old-echo") is None
    assert "not offered" in prepared.validate_call("new_name")


def test_unoffered_calls_are_rejected_without_mcp():
    hidden = MutableTool("hidden")
    hidden.aliases = ()
    prepared = prepare_tools(
        [MutableTool(), hidden], is_tool_visible=lambda tool: tool is not hidden
    )

    assert [tool.name for tool in prepared.definitions] == ["echo_text"]
    assert "not offered" in prepared.validate_call("hidden")
    assert "not offered" in prepared.validate_call("missing")


def test_visibility_filter_runs_after_exposure_and_before_alias_validation():
    catalog = MCPToolCatalog()
    remote = MCPTool()
    remote.aliases = ("old_echo",)
    catalog.replace_server("echo-server", [remote])
    exposure = MCPToolExposureManager(catalog, OrderedDict())
    observed = []

    def visible(tool):
        observed.append(tool)
        return tool is not remote

    prepared = prepare_tools([MutableTool()], tool_exposure=exposure, is_tool_visible=visible)

    assert observed[-1] is remote
    assert list(prepared.targets) == ["echo_text"]
    assert not prepared.mcp_generations
    assert "not offered" in prepared.validate_call("remote_echo")


def test_alias_conflicts_use_existing_name_index_rules():
    conflicting = MutableTool("old_echo")
    conflicting.aliases = ()
    with pytest.raises(ValueError, match="conflicts"):
        prepare_tools([MutableTool(), conflicting])


async def test_registry_replacement_never_swaps_the_offered_execution_target():
    original = MutableTool()
    registry = {original.name: original}
    prepared = prepare_tools(list(registry.values()))
    replacement = MutableTool()
    registry[original.name] = replacement

    assert prepared.validate_call("echo_text") is None
    result = await prepared.targets["echo_text"].invoke({"value": "original"})

    assert result.success
    assert original.calls == ["original"]
    assert replacement.calls == []


@pytest.mark.parametrize("mutation", ["parameters", "schema_extension", "name"])
def test_changed_tool_definition_requires_new_preparation(mutation):
    tool = MutableTool()
    prepared = prepare_tools([tool])
    if mutation == "parameters":
        tool._parameters["properties"]["value"]["type"] = "integer"
    elif mutation == "schema_extension":
        tool.extension["version"].append(2)
    else:
        tool._name = "other_target"

    error = prepared.validate_call("echo_text")

    assert error is not None
    assert "changed" in error
    assert "prepare" in error.lower()


def test_description_only_changes_do_not_invalidate_a_request():
    tool = MutableTool()
    prepared = prepare_tools([tool])
    tool._description = "Updated live description"

    assert prepared.validate_call("echo_text") is None
    assert prepared.definitions[0].description == "Echo a value"
    assert prepared.definitions[0].to_schema()["description"] == "Echo a value"


def test_runtime_compaction_state_is_read_from_the_original_tool():
    tool = MutableTool()
    prepared = prepare_tools([tool])
    tool.state = "after"

    assert prepared.definitions[0].compaction_state() == ("Echo state", "after")


def test_mcp_source_metadata_preserves_cache_fingerprints():
    tool = MCPTool()
    prepared = prepare_tools([tool])

    assert prepared.definitions[0].server_name == tool.server_name
    assert prepared.definitions[0]._server_name == tool._server_name
    assert build_cache_fingerprint(
        messages=[], tools=list(prepared.definitions)
    ) == build_cache_fingerprint(messages=[], tools=[tool])
    assert prepared.target_identity("remote_echo") == (tool.mcp_tool_id, "echo-server")
    assert prepared.target_identity("absent") == (None, None)


@pytest.mark.parametrize("private_server_name", [None, "private-source"])
def test_local_and_private_source_cache_fingerprints_remain_unchanged(private_server_name):
    tool = MutableTool()
    if private_server_name is not None:
        tool._server_name = private_server_name
    prepared = prepare_tools([tool])

    assert build_cache_fingerprint(
        messages=[], tools=list(prepared.definitions)
    ) == build_cache_fingerprint(messages=[], tools=[tool])


@pytest.mark.parametrize(
    "attribute,value", [("_remote_name", "other"), ("_server_name", "other-server")]
)
def test_changed_mcp_execution_mapping_invalidates_the_original_request(attribute, value):
    tool = MCPTool()
    prepared = prepare_tools([tool])
    identity = prepared.target_identity(tool.name)
    setattr(tool, attribute, value)

    assert "changed" in prepared.validate_call("remote_echo")
    assert prepared.target_identity("remote_echo") == identity


def test_mcp_reconnect_invalidates_previous_generation_and_retains_old_target():
    catalog = MCPToolCatalog()
    original = MCPTool()
    catalog.replace_server("echo-server", [original])
    exposure = MCPToolExposureManager(catalog, OrderedDict())
    prepared = prepare_tools([], tool_exposure=exposure)

    assert prepared.mcp_generations == {"remote_echo": 1}
    assert prepared.validate_call("remote_echo") is None
    replacement = MCPTool()
    catalog.replace_server("echo-server", [replacement])

    assert "changed after it was offered" in prepared.validate_call("remote_echo")
    assert prepared.targets["remote_echo"] is original


def test_mcp_validation_checks_the_bound_target_generation():
    catalog = MCPToolCatalog()
    tool = MCPTool()
    catalog.replace_server("echo-server", [tool])
    prepared = prepare_tools([], tool_exposure=MCPToolExposureManager(catalog, OrderedDict()))
    tool._mcp_generation += 1

    assert "execution target changed" in prepared.validate_call("remote_echo")


def test_deferred_mcp_tools_are_not_offered_until_activated():
    catalog = MCPToolCatalog()
    catalog.replace_server("echo-server", [MCPTool(always_load=False)])
    prepared = prepare_tools([], tool_exposure=MCPToolExposureManager(catalog, OrderedDict()))

    assert not prepared.definitions
    assert "not offered" in prepared.validate_call("remote_echo")
