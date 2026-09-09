"""Public host regressions for source binding, restoration and paging admission."""

from hashlib import sha256
from types import SimpleNamespace

import pytest

from box_agent.agent import Agent
from box_agent.events import ErrorEvent
from box_agent.schema import FunctionCall, StreamEvent, ToolCall
from box_agent.session_log import SessionLog
from box_agent.skill_dependencies import SkillDependencyError
from box_agent.tools.base import Tool, ToolResult
from box_agent.tools.skill_loader import SkillLoader
from box_agent.tools.skill_tool import GetSkillTool


class CapturingProvider:
    model = "offline-test"
    max_output_tokens = 1024

    def __init__(self, request_skill=None):
        self.requests = []
        self.request_skill = request_skill

    async def generate_stream(self, messages, tools=None, **kwargs):
        self.requests.append([message.model_copy(deep=True) for message in messages])
        if self.request_skill and len(self.requests) == 1:
            yield StreamEvent(type="finish", finish_reason="tool", tool_calls=[ToolCall(
                id="read-selected", type="function", function=FunctionCall(
                    name="get_skill", arguments={"skill_name": self.request_skill, "limit": 10}))])
            return
        yield StreamEvent(type="text", delta="done")
        yield StreamEvent(type="finish", finish_reason="stop")


def loader_at(path):
    folder = path / "demo"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: demo\ndescription: example\n---\nMETHOD_BODY\n")
    loader = SkillLoader(sources=[(path, "user")], skill_settings_path=path / "settings.json")
    loader.discover_skills()
    return loader


class OtherTool(Tool):
    def __init__(self, loader):
        self.skill_loader = loader

    @property
    def name(self):
        return "other_tool"

    @property
    def description(self):
        return "Unrelated integration with its own source"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    async def execute(self):
        return ToolResult(success=True, content="ok")


@pytest.mark.asyncio
async def test_public_agent_binds_only_real_skill_tools_before_actual_request(tmp_path):
    loader_a, loader_b = loader_at(tmp_path / "a"), loader_at(tmp_path / "b")
    provider = CapturingProvider()
    agent = Agent(llm_client=provider, system_prompt="BASE",
                  tools=[OtherTool(loader_a), GetSkillTool(loader_b)], workspace_dir=str(tmp_path),
                  deferred_mcp_loading_enabled=False, max_steps=1)
    agent.add_user_message("task")
    _ = [event async for event in agent.run_events()]
    assert len(provider.requests) == 1
    assert agent.skill_runtime.loader is loader_b


def seed_log(root, cwd):
    log = SessionLog.create(root, session_id="restore-skill", cwd=cwd)
    log.append("skill/change", {"skills": [{"name": "demo", "sha256": sha256(b"historical").hexdigest(), "loadOrder": 1}]})
    log.flush()
    path = log.path
    log.close()
    return path


@pytest.mark.asyncio
async def test_agent_without_current_source_blocks_before_provider_and_log_write(tmp_path):
    path = seed_log(tmp_path / "sessions", tmp_path)
    before = path.read_bytes()
    log = SessionLog.open(tmp_path / "sessions", session_id="restore-skill", cwd=tmp_path)
    provider = CapturingProvider()
    try:
        agent = Agent(llm_client=provider, system_prompt="BASE", tools=[], session_log=log,
                      workspace_dir=str(tmp_path), deferred_mcp_loading_enabled=False, max_steps=1)
        agent.add_user_message("continue")
        with pytest.raises(SkillDependencyError, match="No Skill source"):
            _ = [event async for event in agent.run_events()]
        assert provider.requests == []
        assert path.read_bytes() == before
    finally:
        log.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("skills_enabled", [False, True])
async def test_acp_without_loader_rejects_historical_skill_without_rewriting_log(tmp_path, monkeypatch, skills_enabled):
    import box_agent.acp as acp_module
    from box_agent.acp import BoxACPAgent
    from box_agent.config import AgentConfig, Config, LLMConfig, ToolsConfig

    path = seed_log(tmp_path / "sessions", tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(acp_module, "state_path", lambda name: tmp_path / name)

    class Conn:
        async def sessionUpdate(self, payload):
            pass

    provider = CapturingProvider()
    config = Config(llm=LLMConfig(api_key="offline"), agent=AgentConfig(max_steps=1, workspace_dir=str(tmp_path)),
                    tools=ToolsConfig(enable_skills=skills_enabled, enable_todo=False, enable_plan=False,
                                      enable_sub_agent=False, enable_mcp=False))
    adapter = BoxACPAgent(Conn(), config, provider, [], "BASE", skill_loader=None)
    with pytest.raises(SkillDependencyError, match="No Skill source"):
        await adapter.newSession(SimpleNamespace(cwd=str(tmp_path), field_meta={
            "session_id": "restore-skill", "session_mode": "general"}))
    assert provider.requests == []
    assert path.read_bytes() == before


@pytest.mark.asyncio
async def test_acp_restore_borrows_real_tool_loader_when_separate_loader_is_omitted(tmp_path, monkeypatch):
    import box_agent.acp as acp_module
    from box_agent.acp import BoxACPAgent
    from box_agent.config import AgentConfig, Config, LLMConfig, ToolsConfig

    seed_log(tmp_path / "sessions", tmp_path)
    monkeypatch.setattr(acp_module, "state_path", lambda name: tmp_path / name)

    class Conn:
        async def sessionUpdate(self, payload):
            pass

    provider = CapturingProvider()
    loader = loader_at(tmp_path / "skills")
    config = Config(llm=LLMConfig(api_key="offline"), agent=AgentConfig(max_steps=1, workspace_dir=str(tmp_path)),
                    tools=ToolsConfig(enable_todo=False, enable_plan=False, enable_sub_agent=False, enable_mcp=False))
    adapter = BoxACPAgent(Conn(), config, provider, [GetSkillTool(loader)], "BASE", skill_loader=None)
    session = await adapter.newSession(SimpleNamespace(cwd=str(tmp_path), field_meta={
        "session_id": "restore-skill", "session_mode": "general"}))
    try:
        await adapter.prompt(SimpleNamespace(sessionId=session.sessionId, prompt=[{"text": "continue"}], field_meta={}))
        assert adapter._sessions[session.sessionId].agent.skill_runtime.loader is loader
        assert len(provider.requests) == 1
        assert "METHOD_BODY" in str(provider.requests[0])
    finally:
        adapter._sessions[session.sessionId].agent.session_log.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("size,with_reader", [(32000, False), (100, False), (32000, True)])
async def test_explicit_material_needs_body_or_an_offered_paging_reader(tmp_path, size, with_reader):
    provider = CapturingProvider(request_skill="first" if with_reader else None)
    tools = [GetSkillTool(loader_at(tmp_path / "skills"))] if with_reader else []
    agent = Agent(llm_client=provider, system_prompt="BASE", tools=tools, workspace_dir=str(tmp_path),
                  deferred_mcp_loading_enabled=False, token_limit=5000, max_steps=3)
    for name in ("first", "second"):
        agent.activate_skill_instructions(name, name.upper() + "\n" + ("x" * 79 + "\n") * (size // 80))
    agent.add_user_message("follow both selected methods")
    events = [event async for event in agent.run_events()]
    if size == 32000 and not with_reader:
        assert provider.requests == []
        assert any(isinstance(event, ErrorEvent) and "reader" in event.message.lower() for event in events)
    else:
        assert len(provider.requests) == (2 if with_reader else 1)
        text = str(provider.requests[0])
        assert ("get_skill" in text and "paged" in text) if with_reader else ("FIRST" in text and "SECOND" in text)
        if with_reader:
            result = next(message for message in provider.requests[1] if message.role == "tool")
            assert result.tool_call_id == "read-selected"
            assert "FIRST" in result.content and '"has_more": true' in result.content
    assert ("get_skill" in agent.tools) == with_reader
