"""Session-owned Skill read facts; source discovery has no session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import Message


@dataclass(frozen=True, slots=True)
class SkillRead:
    name: str
    source: str
    path: str
    revision: str
    prompt: str
    order: int
    reason: str
    delivered_ranges: tuple[tuple[int, int], ...] = ()
    delivered_complete: bool = False

    def log_record(self) -> dict[str, Any]:
        # These three original fields retain the old restore/hash contract.
        return {"name": self.name, "sha256": self.revision, "loadOrder": self.order,
                "source": self.source, "path": self.path, "reason": self.reason,
                "deliveredRanges": [list(pair) for pair in self.delivered_ranges],
                "deliveredComplete": self.delivered_complete}


@dataclass(frozen=True, slots=True)
class SkillContext:
    messages: list[Message]
    references: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[str, ...] = ()
    input_tokens: int = 0


@dataclass(slots=True)
class SkillSessionState:
    reads: dict[str, SkillRead] = field(default_factory=dict)
    selected: tuple[str, ...] = ()
    sequence: int = 0
