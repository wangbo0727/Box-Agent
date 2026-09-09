"""Observable Skill reference behavior, independent of a host protocol."""

import json
from hashlib import sha256

import pytest

from box_agent import skill_runtime
from box_agent.schema import Message
from box_agent.tools.skill_loader import SkillLoader


def make_runtime(tmp_path, body="FIRST_RULE\nSECOND_RULE", extra=""):
    path = tmp_path / "skills" / "demo" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: demo\ndescription: example\n{extra}---\n{body}\n")
    loader = SkillLoader(sources=[(tmp_path / "skills", "user")])
    loader.discover_skills()
    factory = getattr(skill_runtime, "SkillRuntime", None)
    assert factory is not None, "A shared Skill reference runtime is required"
    return factory(loader), path


def test_read_returns_full_reference_without_modifying_system(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    messages = [Message(role="system", content="BASE"), Message(role="user", content="task")]
    runtime.prepare_context(messages, budget_chars=50000)
    result = runtime.read("demo")
    assert result.success and "SECOND_RULE" in result.model_context
    assert result.raw_output["skill_reference"]["complete"] is True
    assert messages[0].content == "BASE"


def test_dedup_requires_body_in_actual_input_and_rereads_after_compaction(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    messages = [Message(role="system", content="BASE"), Message(role="user", content="task")]
    runtime.prepare_context(messages, budget_chars=50000)
    first = runtime.read("demo")
    messages.append(Message(role="tool", name="get_skill", tool_call_id="call_1", content=first.model_context))
    runtime.prepare_context(messages, budget_chars=50000)
    duplicate = runtime.read("demo")
    assert "SECOND_RULE" not in duplicate.model_context
    assert duplicate.raw_output["skill_reference"]["reused"] is True
    messages.pop()
    runtime.prepare_context(messages, budget_chars=50000)
    assert "SECOND_RULE" in runtime.read("demo").model_context


def test_selected_reference_survives_multiple_requests_without_changing_user_text(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    runtime.select(["demo"])
    messages = [Message(role="system", content="BASE"), Message(role="user", content="/demo task")]
    first = runtime.prepare_context(messages, budget_chars=50000)
    assert "SECOND_RULE" in str(first.messages[-1].content)
    messages.append(Message(role="assistant", content="continue"))
    second = runtime.prepare_context(messages, budget_chars=50000)
    assert "SECOND_RULE" in str(second.messages[1].content)
    assert messages[1].content == "/demo task"
    assert second.messages[0].content == "BASE"


def test_long_body_is_complete_when_budget_allows_and_page_advances_when_not(tmp_path):
    runtime, _ = make_runtime(tmp_path, ("x" * 100 + "\n") * 300 + "MIDDLE_IMPORTANT_RULE")
    runtime.prepare_context([], budget_chars=50000)
    full = runtime.read("demo")
    assert "MIDDLE_IMPORTANT_RULE" in full.model_context
    assert full.raw_output["skill_reference"]["complete"]
    runtime.prepare_context([], budget_chars=2000)
    page = runtime.read("demo")
    info = page.raw_output["skill_reference"]
    assert page.success and not info["complete"] and info["has_more"]
    assert info["next_offset"] > 0
    assert len(page.model_context) <= 2000
    runtime.prepare_context([], budget_chars=20)
    exhausted = runtime.read("demo")
    assert not exhausted.success
    assert "budget" in exhausted.error.lower()


def test_revision_change_rejects_stale_page(tmp_path):
    runtime, path = make_runtime(tmp_path)
    runtime.prepare_context([], budget_chars=50000)
    old = runtime.read("demo").raw_output["skill_reference"]["revision"]
    path.write_text(path.read_text() + "CHANGED_VERSION\n")
    result = runtime.read("demo", offset=1, revision=old)
    assert not result.success and "changed" in result.error.lower()


def test_missing_required_returns_diagnostic_without_parent_body(tmp_path):
    runtime, _ = make_runtime(tmp_path, extra="required_skills: [missing]\n")
    result = runtime.read("demo")
    assert not result.success and "missing" in result.error
    assert "FIRST_RULE" not in result.content


def test_same_loader_does_not_share_session_selection(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    other = type(runtime)(runtime.loader)
    runtime.select(["demo"])
    messages = [Message(role="user", content="task")]
    assert "FIRST_RULE" in str(runtime.prepare_context(messages, budget_chars=50000).messages)
    assert "FIRST_RULE" not in str(other.prepare_context(messages, budget_chars=50000).messages)


def test_large_host_selection_leaves_budget_for_forward_reading(tmp_path):
    runtime, _ = make_runtime(tmp_path, ("x" * 100 + "\n") * 70)
    runtime.select(["demo"])
    original = [Message(role="user", content="task")]
    projected = runtime.prepare_context(original, budget_chars=2000)
    added = sum(len(b["text"]) for b in projected.messages[0].content[1:])
    assert added <= 2000
    first = runtime.read("demo")
    assert first.success
    info = first.raw_output["skill_reference"]
    original.append(Message(role="tool", name="get_skill", tool_call_id="page_1", content=first.model_context))
    runtime.prepare_context(original, budget_chars=2000)
    next_page = runtime.read("demo", offset=info["next_offset"], revision=info["revision"])
    assert next_page.success
    assert next_page.raw_output["skill_reference"]["end_offset"] > info["end_offset"]


def test_partial_delivery_has_durable_range_facts(tmp_path):
    runtime, _ = make_runtime(tmp_path, ("x" * 100 + "\n") * 70)
    runtime.prepare_context([], budget_chars=2000)
    page = runtime.read("demo")
    metadata = page.raw_output["skill_reference"]
    record = runtime.log_records()[0]
    assert not record["deliveredComplete"]
    assert record["deliveredRanges"] == [[metadata["offset"], metadata["end_offset"]]]


def test_messages_only_runtime_retains_read_index_after_body_compaction(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    result = runtime.read("demo")
    history = [Message(role="user", content="task"), Message(
        role="tool", name="get_skill", tool_call_id="read", content=result.model_context)]
    restored = type(runtime)(runtime.loader, messages=history)
    assert restored.active_names == ("demo",)
    compacted = [history[0], Message(role="assistant", content="summary")]
    context = restored.prepare_context(compacted, budget_chars=50000)
    assert "Use get_skill" in str(context.messages[0].content)
    assert "FIRST_RULE" not in str(context.messages)
    assert "FIRST_RULE" in restored.read("demo").model_context


def test_verified_legacy_system_suffix_is_only_removed_from_request_copy(tmp_path):
    from box_agent.tools.skill_preload import build_active_skills_prompt

    runtime, _ = make_runtime(tmp_path)
    runtime.read("demo")
    records = runtime.log_records()
    old_system = build_active_skills_prompt("CALLER BASE", {"demo": runtime.state.reads["demo"].prompt})
    restored = type(runtime)(runtime.loader)
    restored.restore_records(records)
    restored.begin_turn()
    history = [Message(role="system", content=old_system), Message(role="user", content="continue")]
    context = restored.prepare_context(history, budget_chars=50000)
    assert context.messages[0].content == "CALLER BASE"
    assert "FIRST_RULE" in str(context.messages[1].content)
    assert history[0].content == old_system
    restored.begin_turn()
    assert restored.prepare_context(history, budget_chars=50000).messages[0].content == "CALLER BASE"
    unrelated = "CALLER BASE\n\n## Active Skill Instructions\nuser-authored instructions"
    history[0] = Message(role="system", content=unrelated)
    assert restored.prepare_context(history, budget_chars=50000).messages[0].content == unrelated


def test_upgraded_restore_does_not_claim_current_body_verifies_historical_system_suffix(tmp_path):
    from box_agent.tools.skill_preload import build_active_skills_prompt

    runtime, path = make_runtime(tmp_path)
    runtime.read("demo")
    records = runtime.log_records()
    old_system = build_active_skills_prompt("CALLER BASE", {"demo": runtime.state.reads["demo"].prompt})
    path.write_text(path.read_text().replace("FIRST_RULE", "CURRENT_RULE"))
    runtime.loader.maybe_reload()
    current_system = build_active_skills_prompt("CALLER BASE", {"demo": runtime.loader.get_skill("demo").to_prompt()})
    restored = type(runtime)(runtime.loader)
    restored.restore_records(records)
    restored.begin_turn()
    for system in (old_system, current_system):
        history = [Message(role="system", content=system), Message(role="user", content="continue")]
        context = restored.prepare_context(history, budget_chars=50000)
        assert context.messages[0].content == system
        assert history[0].content == system
        assert "CURRENT_RULE" in str(context.messages[1].content)
        assert records[0]["sha256"] in str(context.messages[1].content)


@pytest.mark.parametrize("invalid", ["missing", "disabled", "broken", "required"])
def test_restore_rejects_unavailable_current_skill_atomically_even_with_caller_fallback(tmp_path, invalid):
    from box_agent.skill_dependencies import SkillDependencyError

    runtime, path = make_runtime(tmp_path)
    runtime.read("demo")
    records = runtime.log_records()
    runtime.register_reference("retained", "existing reference")
    runtime.register_reference("demo", "caller text must not bypass the configured source")
    before = runtime.log_records()
    sequence = runtime.state.sequence
    selected = runtime.state.selected
    if invalid == "missing":
        path.unlink()
    elif invalid == "disabled":
        settings = tmp_path / "settings.json"
        settings.write_text('{"disabledSkillNames":["demo"]}')
        runtime.loader = SkillLoader(sources=[(path.parent.parent, "user")], skill_settings_path=settings)
        runtime.loader.discover_skills()
    elif invalid == "broken":
        path.write_text("---\nname: [\n---\nbroken\n")
    else:
        path.write_text(path.read_text().replace("description: example", "description: example\nrequired_skills: [missing]"))
    with pytest.raises(SkillDependencyError) as error:
        runtime.restore_records(records)
    assert error.value.code == {
        "missing": "SKILL_NOT_FOUND", "disabled": "SKILL_DISABLED",
        "broken": "SKILL_BROKEN", "required": "SKILL_NOT_FOUND",
    }[invalid]
    assert runtime.log_records() == before
    assert runtime.state.sequence == sequence
    assert runtime.state.selected == selected


def test_register_reference_is_idempotent_and_records_actual_upgraded_hash(tmp_path):
    from box_agent.session_log import SessionLog

    log = SessionLog.create(tmp_path / "sessions", session_id="reference", cwd=tmp_path)
    runtime = skill_runtime.SkillRuntime(None, session_log=log)
    runtime.register_reference("demo", "current", expected_hash=sha256(b"historical").hexdigest())
    before = log.path.read_bytes()
    records = runtime.log_records()
    sequence = runtime.state.sequence
    runtime.register_reference("demo", "current")
    assert log.path.read_bytes() == before
    assert runtime.log_records() == records
    assert runtime.state.sequence == sequence
    assert records[0]["sha256"] == sha256(b"current").hexdigest()
    runtime.register_reference("demo", "next")
    assert runtime.state.sequence == sequence + 1
    assert log.replay().skills[0]["sha256"] == sha256(b"next").hexdigest()
    log.close()


def test_restore_preserves_saved_order_and_keeps_range_facts_only_for_unchanged_sources(tmp_path):
    runtime, path = make_runtime(tmp_path)
    other_path = path.parent.parent / "other" / "SKILL.md"
    other_path.parent.mkdir()
    other_path.write_text("---\nname: other\ndescription: other\n---\nUNCHANGED_RULE\n")
    runtime.read("other")
    runtime.read("demo")
    records = runtime.log_records()
    records.reverse()
    path.write_text(path.read_text().replace("FIRST_RULE", "UPGRADED_RULE"))
    restored = type(runtime)(runtime.loader)
    restored.restore_records(records)
    assert list(restored.state.reads) == ["other", "demo"]
    assert [record["loadOrder"] for record in restored.log_records()] == [1, 2]
    assert restored.state.reads["other"].delivered_complete
    assert restored.state.reads["other"].delivered_ranges
    assert not restored.state.reads["demo"].delivered_complete
    assert restored.state.reads["demo"].delivered_ranges == ()
    assert "UPGRADED_RULE" in restored.state.reads["demo"].prompt


def test_multibyte_body_and_status_obey_actual_reference_budget(tmp_path):
    from box_agent.skill_context import reference_cost

    runtime, _ = make_runtime(tmp_path, ("请逐页检查，保留全部原始能力。🙂\n") * 120)
    runtime.select(["demo"])
    context = runtime.prepare_context([Message(role="user", content="task")], budget_chars=2000)
    page = runtime.read("demo")
    assert page.success and page.raw_output["skill_reference"]["next_offset"] > 0
    added = "".join(block["text"] for block in context.messages[0].content[1:])
    assert reference_cost(added) + reference_cost(page.model_context) <= 2000
