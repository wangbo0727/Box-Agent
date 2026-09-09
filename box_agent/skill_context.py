"""Bounded ordinary-context Skill references, never system instructions."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .schema import Message

REFERENCE_START = "[Skill reference]\n"
REFERENCE_END = "\n[/Skill reference]"


def reference_cost(text: str) -> int:
    """Character-equivalent cost using the same UTF-8 guard as context estimates."""
    return max(len(text), (len(text.encode("utf-8")) * 4 + 2) // 3)


def render_reference(metadata: dict[str, Any], body: str) -> str:
    # Billing provenance and generic rules belong in raw metadata/the common
    # instructions, not repeated in every model-facing page header.
    visible = {key: value for key, value in metadata.items()
               if key not in {"instruction_digest", "reason", "guidance"}}
    return (REFERENCE_START + json.dumps(visible, ensure_ascii=False, sort_keys=True)
            + "\n\n" + body + REFERENCE_END)


def read_reference(content: str) -> tuple[dict[str, Any], str] | None:
    """Parse a complete framework reference, not an arbitrary mention/receipt."""
    if not content.startswith(REFERENCE_START) or not content.endswith(REFERENCE_END):
        return None
    try:
        header, body = content[len(REFERENCE_START):-len(REFERENCE_END)].split("\n\n", 1)
        metadata = json.loads(header)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("revision"), str):
            return None
        return metadata, body
    except (ValueError, TypeError):
        return None


def visible_ranges(messages: Iterable[Message], *, name: str, revision: str,
                   lines: list[str], source: str | None = None, path: str | None = None) -> set[int]:
    """Only actual complete tool text counts; summaries/acks cannot pin content."""
    covered: set[int] = set()
    for message in messages:
        if (message.role != "tool" or message.name not in {"get_skill", "skill_view"}
                or not message.tool_call_id or not isinstance(message.content, str)):
            continue
        parsed = read_reference(message.content)
        if parsed is None:
            continue
        meta, body = parsed
        if meta.get("name") != name or meta.get("revision") != revision:
            continue
        if ((source is not None and meta.get("source") != source)
                or (path is not None and meta.get("path") != path)):
            continue
        start, end = meta.get("offset"), meta.get("end_offset")
        if (isinstance(start, int) and not isinstance(start, bool)
                and isinstance(end, int) and not isinstance(end, bool)
                and 0 <= start < end <= len(lines)
                and body == "".join(lines[start:end])):
            covered.update(range(start, end))
    return covered


def append_reference(message: Message, text: str) -> Message:
    """Project onto a request copy; keep host input and durable history intact."""
    blocks = ([{"type": "text", "text": message.content}]
              if isinstance(message.content, str) else list(message.content))
    blocks.append({"type": "text", "text": text})
    return message.model_copy(update={"content": blocks})
