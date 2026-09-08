"""C5's intentional schedule-name delta against the fixed C1 contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from box_agent.events import ToolCallResult, ToolCallStart
from box_agent.runtime import run_agent_loop
from box_agent.schema import FunctionCall, Message, StreamEvent, ToolCall
from box_agent.tools.base import build_tool_name_index
from box_agent.tools.schedule_tool import CreateScheduledTaskTool
from box_agent.tools.skill_loader import SkillLoader
from box_agent.tools.sub_agent_capabilities import (
    CapabilityFailure, CapabilityResolver, DelegationSpec, parse_delegation_spec,
)


ROOT = Path(__file__).resolve().parent.parent
LEGACY_NAME = "create_scheduled_task"
PREPARATION_NAME = "prepare_scheduled_task"
DRAFT_ARGUMENTS = {
    "name": "工作日报", "prompt": "汇总当天已完成工作和后续事项。", "cron_expr": "0 9 * * 1-5",
}


class ScheduleLLM:
    def __init__(self, requested_name: str | None = None):
        self.requested_name = requested_name
        self.offered_names = []

    async def generate_stream(self, messages, tools=None, **kwargs):
        self.offered_names.append([tool.name for tool in tools or []])
        if self.requested_name is not None:
            requested_name, self.requested_name = self.requested_name, None
            yield StreamEvent(type="finish", finish_reason="tool_use", tool_calls=[
                ToolCall(id="schedule-original-call", type="function", function=FunctionCall(
                    name=requested_name, arguments=DRAFT_ARGUMENTS,
                )),
            ])
        else:
            yield StreamEvent(type="text", delta="请核对草稿后保存。")
            yield StreamEvent(type="finish", finish_reason="stop")


def test_c5_changes_only_schedule_schema_name_and_adds_legacy_inbound_alias():
    from box_agent.tools.schedule_tool import PrepareScheduledTaskTool

    assert CreateScheduledTaskTool is PrepareScheduledTaskTool
    tool = PrepareScheduledTaskTool()
    baseline = json.loads((ROOT / "tests/fixtures/tool_engine/c1_schemas.json").read_text())["tools"][LEGACY_NAME]
    expected_schema = {**baseline["schema"], "name": PREPARATION_NAME}
    assert tool.name == PREPARATION_NAME
    assert tool.to_schema() == expected_schema
    assert tool.to_openai_schema()["function"]["name"] == PREPARATION_NAME
    assert tool.aliases == (LEGACY_NAME,)
    index = build_tool_name_index([tool])
    assert {id(target) for target in index.values()} == {id(tool)}
    assert set(index) == {
        LEGACY_NAME, PREPARATION_NAME,
        LEGACY_NAME.replace("_", "-"), PREPARATION_NAME.replace("_", "-"),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_name", [LEGACY_NAME, PREPARATION_NAME, "create-scheduled-task"])
async def test_schedule_alias_preserves_call_id_and_host_draft_with_one_offered_schema(requested_name):
    class CountingScheduleTool(CreateScheduledTaskTool):
        calls = 0

        async def execute(self, **kwargs):
            self.calls += 1
            return await super().execute(**kwargs)

    tool = CountingScheduleTool()
    llm = ScheduleLLM(requested_name)
    messages = [Message(role="system", content="system"), Message(role="user", content="已确认任务与时间。")]
    events = [event async for event in run_agent_loop(
        llm=llm, messages=messages, tools={tool.name: tool}, max_steps=3,
    )]
    assert all(names == [PREPARATION_NAME] for names in llm.offered_names)
    assert tool.calls == 1
    starts = [event for event in events if isinstance(event, ToolCallStart)]
    results = [event for event in events if isinstance(event, ToolCallResult)]
    assert len(starts) == len(results) == 1
    assert starts[0].tool_call_id == results[0].tool_call_id == "schedule-original-call"
    assert starts[0].tool_name == results[0].tool_name == PREPARATION_NAME
    assert results[0].raw_output == {
        "kind": "officev3_schedule_draft",
        "draft": {**DRAFT_ARGUMENTS, "trigger_type": "cron", "fire_at": None},
    }
    assert "是否最终保存由用户决定" in results[0].content
    assert messages[2].tool_calls[0].function.name == requested_name


@pytest.mark.parametrize("requested_name", [LEGACY_NAME, PREPARATION_NAME])
def test_schedule_names_retain_external_side_effect_delegation_rejection(requested_name):
    spec = parse_delegation_spec(task="准备任务草稿", required_tools=[requested_name])
    assert isinstance(spec, DelegationSpec)
    result = CapabilityResolver().resolve(
        spec, parent_tools={requested_name: CreateScheduledTaskTool()},
    )
    assert isinstance(result, CapabilityFailure)
    assert result.code == "CAPABILITY_CONSTRAINT_CONFLICT"
    assert result.details["denied_reason"] == "external_side_effect_disabled"


def test_scheduled_task_skill_preserves_business_guidance_with_new_tool_references():
    skill_path = ROOT / "box_agent/skills/scheduled-task/SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    # The approved change is three tool references; the original workflow stays fixed.
    legacy_text = text.replace(PREPARATION_NAME, LEGACY_NAME)
    assert hashlib.sha256(legacy_text.encode()).hexdigest() == "a370df5f9edc2afcebd9458b63af777b2d335877533dd6e42d01a33850d9ce70"
    assert PREPARATION_NAME in text
    assert LEGACY_NAME not in text
    loader = SkillLoader(sources=[(ROOT / "box_agent/skills", "builtin")])
    loader.discover_skills()
    skill = loader.get_skill("scheduled-task")
    assert skill is not None
    assert PREPARATION_NAME in skill.description
    assert PREPARATION_NAME in skill.to_prompt()
    prompt = (ROOT / "box_agent/config/system_prompt.md").read_text(encoding="utf-8")
    # The stable prompt has no schedule-specific instruction to migrate;
    # the Tool description and this Skill own the draft/save semantics.
    assert LEGACY_NAME not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [False, True])
async def test_legacy_schedule_history_restores_without_reissuing_draft(tmp_path, completed):
    from box_agent.agent import Agent
    from box_agent.session_log import SessionLog

    call = ToolCall(id="historical-schedule", type="function", function=FunctionCall(
        name=LEGACY_NAME, arguments=DRAFT_ARGUMENTS,
    ))
    historical_draft = {
        "kind": "officev3_schedule_draft",
        "draft": {**DRAFT_ARGUMENTS, "trigger_type": "cron", "fire_at": None},
    }
    root = tmp_path / "sessions"
    log = SessionLog.create(root, session_id="old-schedule", cwd=tmp_path)
    log.append("turn/start", {"turn": 1})
    log.append("step/start", {"turn": 1, "step": 1})
    historical_messages = [
        Message(role="user", content="请准备日报任务。"),
        Message(role="assistant", content="", tool_calls=[call]),
    ]
    log.append_unlogged_messages(historical_messages, turn=1, step=1)
    log.append("tool/call", {
        "turn": 1, "step": 1, "callId": call.id,
        "name": LEGACY_NAME, "arguments": DRAFT_ARGUMENTS,
    })
    if completed:
        historical_messages.append(
            Message(role="tool", tool_call_id=call.id, content="已发送草稿，请核对保存。"),
        )
        log.append_unlogged_messages(historical_messages, turn=1, step=1, tool_result_metadata={call.id: {
            "toolName": LEGACY_NAME, "success": True, "rawOutput": historical_draft,
        }})
        log.append("step/end", {"turn": 1, "step": 1})
        log.append("turn/end", {"turn": 1, "reason": {"kind": "completed"}})
    log.flush()
    log.close()

    class NeverReissuedSchedule(CreateScheduledTaskTool):
        calls = 0

        async def execute(self, **kwargs):
            self.calls += 1
            raise AssertionError("restoring history must never issue another draft")

    restored_log = SessionLog.open(root, session_id="old-schedule", cwd=tmp_path)
    restored_log.prepare_resume()
    tool = NeverReissuedSchedule()
    llm = ScheduleLLM()
    agent = Agent(
        llm_client=llm, system_prompt="system", tools=[tool],
        workspace_dir=str(tmp_path), deferred_mcp_loading_enabled=False,
        session_log=restored_log,
    )
    assert any(
        message.tool_calls and message.tool_calls[0].function.name == LEGACY_NAME
        for message in agent.messages
    )
    assert any(message.tool_call_id == call.id for message in agent.messages)
    agent.add_user_message("只查看先前记录，不重新发送草稿。")
    try:
        events = [event async for event in agent.run_events()]
        assert tool.calls == 0
        assert not any(isinstance(event, (ToolCallStart, ToolCallResult)) for event in events)
        calls = [event for event in restored_log.events if event["type"] == "tool/call"]
        assert len(calls) == 1
        assert calls[0]["data"]["callId"] == call.id
        assert calls[0]["data"]["name"] == LEGACY_NAME
        result = next(event for event in restored_log.events if event["type"] == "tool/result")
        if completed:
            assert result["data"]["result"]["rawOutput"] == historical_draft
        else:
            assert result["data"]["error"]["code"] == "TOOL_OUTCOME_UNKNOWN"
        # Historical calls do not activate a discoverable tool in a new session.
        assert llm.offered_names[0] == ["tool_search"]
        assert agent.tools[PREPARATION_NAME] is tool
        assert LEGACY_NAME not in llm.offered_names[0]
    finally:
        restored_log.close()
