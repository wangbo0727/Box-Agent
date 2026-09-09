"""Session Skill discovery, bounded reading and ordinary-context projection."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping, MutableSequence
from typing import Any
from hashlib import sha256
from types import SimpleNamespace

from .schema import Message
from .skill_context import append_reference, read_reference, render_reference, visible_ranges, reference_cost
from .skill_dependencies import SkillDependencyError, resolve_required_skills
from .skill_state import SkillContext, SkillRead, SkillSessionState
from .tools.base import ToolResult

from box_agent.tools.skill_loader import SkillLoader
from box_agent.tools.skill_preload import (
    AutoLoadedSkillsPrompt,
    build_auto_loaded_skills_prompt,
)


class SkillRuntime:
    """Borrow the loader; own only this session's facts and current references."""

    def __init__(self, loader: SkillLoader | None, *, session_log: Any = None,
                 messages: list[Message] | None = None):
        self.loader = loader
        self.session_log = session_log
        self.state = SkillSessionState()
        self._messages: list[Message] = []
        self._remaining = 50_000
        self._host_visible: dict[str, str] = {}
        self.turn_deliveries: dict[str, dict[str, Any]] = {}
        self.reference_overhead_chars = 0
        self._restore_pending: tuple[str, ...] = ()
        self._restoring: tuple[str, ...] = ()
        self._restore_diagnostics: dict[str, str] = {}
        self._legacy_system_suffix = ""
        if messages:
            self._observe_reads(messages)

    def begin_turn(self) -> None:
        self.turn_deliveries.clear()
        self._restoring, self._restore_pending = self._restore_pending, ()

    def select(self, names: list[str] | tuple[str, ...]) -> None:
        self.state.selected = tuple(dict.fromkeys(name.strip() for name in names if name.strip()))

    @property
    def active_names(self) -> tuple[str, ...]:
        if self.loader is not None:
            self.loader.maybe_reload()
        names = []
        for name in dict.fromkeys((*self.state.reads, *self.state.selected)):
            try:
                skill = self._resolve(name)
            except SkillDependencyError:
                continue
            previous = self.state.reads.get(name)
            if previous is not None and (sha256(skill.to_prompt().encode()).hexdigest() != previous.revision
                                         or previous.source != skill.source or previous.path != str(skill.skill_path or "")):
                continue
            names.append(name)
        return tuple(names)

    def _resolve(self, name: str) -> Any:
        record = self.state.reads.get(name)
        if record is not None and record.source == "caller":
            return SimpleNamespace(name=name, source="caller", skill_path=record.path,
                                   required_skills=[], related_skills=[], broken=False,
                                   to_prompt=lambda: record.prompt)
        if self.loader is None:
            raise SkillDependencyError("SKILL_PROVIDER_UNAVAILABLE", "No Skill source is configured.")
        resolve_required_skills(self.loader, [name])
        return self.loader.get_skill(name)

    def register_reference(self, name: str, prompt: str, *, expected_hash: str | None = None,
                           order: int | None = None, persist: bool = True) -> None:
        """Compatibility for an explicit host-provided reference, never system text."""
        revision = sha256(prompt.encode()).hexdigest()
        previous = self.state.reads.get(name)
        self.select([*self.state.selected, name])
        if previous is not None and previous.revision == revision and previous.prompt == prompt:
            return
        self._restore_diagnostics.pop(name, None)
        if expected_hash is not None and revision != expected_hash:
            self._restore_diagnostics[name] = self._restore_notice(
                name, {"sha256": expected_hash}, revision, "caller", "",
            )
        self.state.sequence = max(self.state.sequence + 1, order or 0)
        self.state.reads[name] = SkillRead(name, "caller", "", revision, prompt,
                                         order or self.state.sequence, "explicit")
        if persist and self.session_log is not None:
            self.session_log.append("skill/change", {"skills": self.log_records()})
            self.session_log.flush()

    def restore_records(self, records: list[dict[str, Any]]) -> None:
        """Resolve current valid references atomically, without rewriting history.

        Historical hashes describe the original read. An upgrade may change
        the effective source or body; that relationship is ordinary metadata,
        not a reason to prevent the session from continuing.
        """
        if self.loader is not None:
            self.loader.maybe_reload()
        restored: dict[str, SkillRead] = {}
        diagnostics: dict[str, str] = {}
        historical_bodies_verified = True
        for record in sorted(records, key=lambda row: row["loadOrder"]):
            name = record["name"]
            if self.loader is not None:
                # A prior caller reference must not bypass current source and
                # required-dependency validity during session restoration.
                skill = resolve_required_skills(self.loader, [name])[-1]
                prompt, source, path = skill.to_prompt(), skill.source, str(skill.skill_path or "")
            elif isinstance(record.get("prompt"), str):
                # The old public tuple API supplies current host text when no
                # Loader exists. It is never a historical snapshot assertion.
                prompt, source, path = record["prompt"], "caller", ""
            else:
                raise SkillDependencyError("SKILL_PROVIDER_UNAVAILABLE", "No Skill source is configured.")
            revision = sha256(prompt.encode()).hexdigest()
            same_body = revision == record["sha256"]
            historical_bodies_verified = historical_bodies_verified and same_body
            changed = (not same_body
                       or ("source" in record and record["source"] != source)
                       or ("path" in record and record["path"] != path))
            if changed:
                diagnostics[name] = self._restore_notice(name, record, revision, source, path)
            restored[name] = SkillRead(
                name, source, path, revision, prompt, record["loadOrder"], "restored",
                () if changed else tuple(tuple(pair) for pair in record.get("deliveredRanges", ())),
                False if changed else record.get("deliveredComplete", True),
            )
        from .tools.skill_preload import build_active_skills_prompt
        suffix = (build_active_skills_prompt("", {name: item.prompt for name, item in restored.items()})
                  if historical_bodies_verified else "")
        self.state = SkillSessionState(reads=restored,
                                       sequence=max((item.order for item in restored.values()), default=0))
        self._restore_diagnostics = diagnostics
        self._restore_pending = tuple(restored)
        self._restoring = ()
        self._legacy_system_suffix = suffix

    @staticmethod
    def _restore_notice(name: str, historical: dict[str, Any], revision: str, source: str, path: str) -> str:
        return (f"Skill '{name}' used the current valid reference at session restoration: "
                f"historical sha256={historical['sha256']}; current sha256={revision}. "
                f"Historical source={historical.get('source', 'unspecified')} path={historical.get('path', 'unspecified')}; "
                f"current source={source} path={path}. Historical logs remain unchanged; "
                "the restored reference does not prove the historical source or version.")


    def _remember(self, skill: Any, prompt: str, reason: str, metadata: dict[str, Any]) -> None:
        revision = sha256(prompt.encode()).hexdigest()
        old = self.state.reads.get(skill.name)
        ranges = set(old.delivered_ranges) if (old is not None and old.revision == revision
                  and old.source == skill.source and old.path == str(skill.skill_path or "")) else set()
        ranges.add((metadata["offset"], metadata["end_offset"]))
        coverage = {line for start, end in ranges for line in range(start, end)}
        self.state.sequence += 1
        self.state.reads[skill.name] = SkillRead(
            skill.name, skill.source, str(skill.skill_path or ""), revision,
            prompt, self.state.sequence, reason, tuple(sorted(ranges)),
            len(coverage) == metadata["total_lines"],
        )
        if self.session_log is not None:
            self.session_log.append("skill/change", {"skills": self.log_records()})
            self.session_log.flush()

    def log_records(self) -> list[dict[str, Any]]:
        return [read.log_record() for read in sorted(self.state.reads.values(), key=lambda r: r.order)]

    def _observe_reads(self, messages: list[Message]) -> None:
        """Recover facts from real, source-verified tool text for messages-only callers."""
        for message in messages:
            if (message.role != "tool" or message.name not in {"get_skill", "skill_view"}
                    or not message.tool_call_id or not isinstance(message.content, str)):
                continue
            parsed = read_reference(message.content)
            if parsed is None:
                continue
            metadata, _ = parsed
            name = metadata.get("name")
            if not isinstance(name, str):
                continue
            try:
                skill = self._resolve(name)
            except SkillDependencyError:
                continue
            prompt = skill.to_prompt()
            revision = sha256(prompt.encode()).hexdigest()
            lines = prompt.splitlines(keepends=True)
            if (metadata.get("source") != skill.source
                    or metadata.get("path") != str(skill.skill_path or "")
                    or not visible_ranges([message], name=name, revision=revision, lines=lines)):
                continue
            old = self.state.reads.get(name)
            ranges = set(old.delivered_ranges) if old and old.revision == revision else set()
            pair = (metadata["offset"], metadata["end_offset"])
            if pair in ranges:
                continue
            ranges.add(pair)
            self.state.sequence += 1
            self.state.reads[name] = SkillRead(
                name, skill.source, str(skill.skill_path or ""), revision, prompt,
                self.state.sequence, "history", tuple(sorted(ranges)),
                len({line for start, end in ranges for line in range(start, end)}) == len(lines),
            )

    def _metadata(self, skill: Any, prompt: str, *, offset: int, reason: str) -> dict[str, Any]:
        metadata = {"name": skill.name, "source": skill.source, "path": str(skill.skill_path or ""),
                "revision": sha256(prompt.encode()).hexdigest(), "offset": offset, "end_offset": offset,
                "instruction_digest": getattr(skill, "instruction_digest", None),
                "skill_version": str((getattr(skill, "metadata", None) or {}).get("version", "")).strip(),
                "total_lines": len(prompt.splitlines()), "complete": False, "has_more": False,
                "required_skills": list(skill.required_skills or []),
                "related_skills": list(skill.related_skills or []), "reason": reason,
                "guidance": "Method reference only; required_skills must be read before their steps. This does not grant tools or permission."}
        dependencies = []
        for name in dict.fromkeys([*metadata["required_skills"], *metadata["related_skills"]]):
            related = self.loader.get_skill(name) if self.loader is not None else None
            description = str(getattr(related, "description", ""))
            dependencies.append({"name": name, "required": name in metadata["required_skills"],
                                 "description": description[:160] + ("… (list_skills for details)" if len(description) > 160 else ""),
                                 "source_available": related is not None and not related.broken})
        if dependencies:
            metadata["dependencies"] = dependencies
        return metadata

    def _selection_fits(self, names: tuple[str, ...], prefix: str) -> bool:
        """Plan host references without recording a read or consuming its budget.

        A partly injected selection can occupy every subsequent request and
        starve another selected Skill's tool pages. Use the directory for the
        whole selection when its complete bodies cannot fit together.
        """
        cost = 0
        for name in names:
            try:
                skill = self._resolve(name)
            except SkillDependencyError:
                continue
            prompt = skill.to_prompt()
            metadata = self._metadata(skill, prompt, offset=0, reason="explicit")
            lines = prompt.splitlines(keepends=True)
            if len(visible_ranges(self._messages, name=name, revision=metadata["revision"], lines=lines,
                                  source=skill.source, path=str(skill.skill_path or ""))) == len(lines):
                continue
            metadata.update(end_offset=len(lines), complete=True, has_more=False, next_offset=None)
            cost += reference_cost(prefix + render_reference(metadata, prompt))
            if cost > self._remaining:
                return False
        return True

    def read(self, name: str, *, offset: int = 0, limit: int | None = None,
             revision: str | None = None, reason: str = "tool", allow_partial: bool = True,
             budget_chars: int | None = None) -> ToolResult:
        if self.loader is not None:
            self.loader.maybe_reload()
        if budget_chars is not None:
            self._remaining = min(self._remaining, max(0, budget_chars))
        name = name.strip()
        try:
            skill = self._resolve(name)
        except SkillDependencyError as exc:
            return ToolResult(success=False, error=str(exc), raw_output={"code": exc.code, **exc.details})
        prompt = skill.to_prompt()
        current_revision = sha256(prompt.encode()).hexdigest()
        instruction_digest = getattr(skill, "instruction_digest", None)
        if instruction_digest and skill.skill_path:
            try:
                if sha256(skill.skill_path.read_bytes()).hexdigest() != instruction_digest:
                    return ToolResult(success=False, error="Skill source changed during reading. Refresh and retry from offset=0.")
            except OSError as exc:
                return ToolResult(success=False, error=f"Skill source became unreadable: {exc}")
        if revision is not None and revision != current_revision:
            return ToolResult(success=False, error=f"Skill '{name}' changed; restart at offset=0 with revision={current_revision}.")
        lines = prompt.splitlines(keepends=True)
        if (isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset < len(lines)
                or (limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1))):
            return ToolResult(success=False, error="Invalid Skill offset/limit; use a valid zero-based line offset and positive limit.")
        covered = visible_ranges(self._messages, name=name, revision=current_revision, lines=lines,
                                 source=skill.source, path=str(skill.skill_path or ""))
        metadata = self._metadata(skill, prompt, offset=offset, reason=reason)
        if len(covered) == len(lines) or self._host_visible.get(name) == current_revision:
            metadata.update(complete=True, reused=True)
            content = f"Skill '{name}' revision {current_revision} is fully present in this request; reuse that reference."
            if reference_cost(content) > self._remaining:
                return ToolResult(success=False, error="Skill reference budget exhausted; compact context before another read.",
                                  raw_output={"code": "SKILL_CONTEXT_BUDGET", "name": name})
            self._remaining -= reference_cost(content)
            self.turn_deliveries[name] = dict(metadata)
            return ToolResult(success=True, content=content, model_context=content,
                              raw_output={"skill_reference": metadata})
        end = min(len(lines), offset + limit) if limit is not None else len(lines)
        # Exact rendered length includes the receipt and continuation parameters.
        while end > offset:
            metadata.update(end_offset=end, has_more=end < len(lines),
                            next_offset=end if end < len(lines) else None,
                            complete=len(covered | set(range(offset, end))) == len(lines))
            content = render_reference(metadata, "".join(lines[offset:end]))
            if reference_cost(content) <= self._remaining:
                break
            excess = reference_cost(content) - self._remaining
            while end > offset and excess > 0:
                end -= 1
                excess -= reference_cost(lines[end])
        if end <= offset:
            return ToolResult(success=False, error="Skill reference budget cannot fit the next complete line. Compact context or allocate a larger budget; do not retry the same page unchanged.",
                              raw_output={"code": "SKILL_CONTEXT_BUDGET", "name": name, "revision": current_revision})
        if not allow_partial and end < len(lines):
            return ToolResult(success=False, error=(
                f"Selected Skill '{name}' needs paged reading. Call get_skill with "
                f"skill_name={name!r}, offset=0, revision={current_revision!r}; "
                "follow next_offset until the needed instructions are read."),
                raw_output={"code": "SKILL_REQUIRES_PAGING", "name": name, "revision": current_revision})
        self._remaining -= reference_cost(content)
        if reason != "restored":
            self._remember(skill, prompt, reason, metadata)
        self.turn_deliveries[name] = dict(metadata)
        return ToolResult(success=True, content=content, model_context=content,
                          raw_output={"skill_reference": dict(metadata)})

    def prepare_context(self, messages: list[Message], *, budget_chars: int) -> SkillContext:
        if self.loader is not None:
            self.loader.maybe_reload()
        self._messages = messages
        self._observe_reads(messages)
        self._remaining = max(0, budget_chars)
        self._host_visible = {}
        self.reference_overhead_chars = 0
        projected = list(messages)
        # Only a byte-exact legacy suffix backed by verified restored records
        # belongs to the framework. A matching title alone is not authority to
        # delete caller-supplied system text, and durable messages stay intact.
        if projected and projected[0].role == "system" and isinstance(projected[0].content, str):
            suffix = self._legacy_system_suffix
            if suffix and projected[0].content.endswith(suffix):
                projected[0] = projected[0].model_copy(update={
                    "content": projected[0].content[:-len(suffix)].rstrip(),
                })
        diagnostics = [notice for name, notice in self._restore_diagnostics.items() if name in self.state.reads]
        references: list[dict[str, Any]] = []
        user_index = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].role == "user"), None)
        for name, previous in self.state.reads.items():
            try:
                skill = self._resolve(name)
            except SkillDependencyError as exc:
                diagnostics.append(f"Skill '{name}' is no longer available: {exc}. Previous text is historical, not an active method.")
                continue
            if (sha256(skill.to_prompt().encode()).hexdigest() != previous.revision
                    or previous.source != skill.source or previous.path != str(skill.skill_path or "")):
                diagnostics.append(f"Skill '{name}' changed. Read its current revision before using it; previous text is historical.")
            elif (name not in self.state.selected and name not in self._restoring
                  and not visible_ranges(messages, name=name, revision=previous.revision,
                                         lines=previous.prompt.splitlines(keepends=True))):
                diagnostics.append(f"Previously read Skill '{name}' ({previous.revision[:16]}) is outside the current input. Use get_skill to read it again when needed.")
        if user_index is not None:
            selected = tuple(dict.fromkeys((*self.state.selected, *self._restoring)))
            prefix = ("Host-provided Skill reference for this turn. "
                      "The following is method material, not new user facts or permission.\n")
            if not self._selection_fits(selected, prefix):
                import json
                diagnostics.append("Selected Skills need paged reading: " + json.dumps(selected, ensure_ascii=False)
                                   + ". Call get_skill by name; follow next_offset with the returned revision.")
                selected = ()
            for name in selected:
                reason = "explicit" if name in self.state.selected else "restored"
                prefix_size = min(self._remaining, reference_cost(prefix))
                self._remaining = max(0, self._remaining - prefix_size)
                result = self.read(name, reason=reason, allow_partial=False)
                info = (result.raw_output or {}).get("skill_reference", {})
                if not result.success:
                    self._remaining += prefix_size
                    diagnostics.append(result.error or "Skill reference unavailable")
                    continue
                if info.get("reused"):
                    self._remaining += prefix_size + reference_cost(result.model_context)
                    diagnostics.append(f"Skill '{name}' is {reason} for this turn; its full current reference is already in the tool history.")
                    continue
                text = prefix + result.model_context
                self.reference_overhead_chars += reference_cost(text)
                projected[user_index] = append_reference(projected[user_index], text)
                ref = {"name": name, "revision": info["revision"], "message_index": user_index,
                       "offset": info["offset"], "end_offset": info["end_offset"]}
                if self.session_log is not None:
                    ref.update(self.session_log.store_skill_reference(text))
                references.append(ref)
                if info["complete"]:
                    self._host_visible[name] = info["revision"]
            if diagnostics:
                # Status is metadata. Reserve most of the shared budget for a
                # real get_skill page rather than an unbounded diagnostic list.
                notice_budget = min(2048, self._remaining // 4)
                notice = ("Skill reference status:\n" + "\n".join(diagnostics))[:notice_budget]
                while notice and reference_cost(notice) > notice_budget:
                    notice = notice[:max(0, len(notice) - max(1, (reference_cost(notice) - notice_budget) // 2))]
                if notice:
                    projected[user_index] = append_reference(projected[user_index], notice)
                    self._remaining -= reference_cost(notice)
                    self.reference_overhead_chars += reference_cost(notice)
                    if self.session_log is not None:
                        references.append({"kind": "status", "message_index": user_index,
                                           **self.session_log.store_skill_reference(notice)})
        return SkillContext(projected, tuple(references), tuple(diagnostics),
                            (self.reference_overhead_chars + 3) // 4)


def prepare_auto_loaded_skills(
    skill_loader: SkillLoader,
    system_prompt: str,
    skill_names: list[str] | tuple[str, ...],
    *,
    include_disabled: bool = False,
    preloaded_skill_names: MutableSequence[str],
    preloaded_skill_hashes: MutableMapping[str, str],
    preloaded_skill_attributions: MutableMapping[str, Any] | None = None,
    prompt_builder: Callable[..., AutoLoadedSkillsPrompt] = build_auto_loaded_skills_prompt,
) -> tuple[AutoLoadedSkillsPrompt, set[str]]:
    """Legacy pure helper retained for external callers and historical tests.

    Default Agent, CLI, ACP and Tool Engine paths use SkillRuntime instead.
    This helper is not a supported way to inject Skill bodies into a run.
    """

    result = prompt_builder(
        skill_loader,
        system_prompt,
        skill_names,
        include_disabled=include_disabled,
    )
    unloaded_skill_names = apply_auto_loaded_skill_state(
        result,
        preloaded_skill_names=preloaded_skill_names,
        preloaded_skill_hashes=preloaded_skill_hashes,
        preloaded_skill_attributions=preloaded_skill_attributions,
    )
    return result, unloaded_skill_names


def apply_auto_loaded_skill_state(
    result: AutoLoadedSkillsPrompt,
    *,
    preloaded_skill_names: MutableSequence[str],
    preloaded_skill_hashes: MutableMapping[str, str],
    preloaded_skill_attributions: MutableMapping[str, Any] | None = None,
) -> set[str]:
    """Apply one preload result while preserving collection identities.

    Adapters retain warning, logging, prompt replacement, and host metadata
    decisions.  This helper only performs the shared state transition and
    returns names that were removed so each host can render them as before.
    """

    previous_skill_names = set(preloaded_skill_names)
    preloaded_skill_names[:] = result.loaded_names
    preloaded_skill_hashes.clear()
    preloaded_skill_hashes.update(result.loaded_skill_hashes)
    if preloaded_skill_attributions is not None:
        preloaded_skill_attributions.clear()
        preloaded_skill_attributions.update(
            {
                attribution.skill_name: attribution
                for attribution in result.loaded_attributions
            }
        )
    return previous_skill_names - set(result.loaded_names)


__all__ = ["SkillRuntime", "apply_auto_loaded_skill_state", "prepare_auto_loaded_skills"]
