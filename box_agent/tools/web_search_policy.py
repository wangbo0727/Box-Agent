"""Existing search batching and evidence counters, scoped to one tool run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .web_search_runtime import _normalize_web_search_query, _web_search_queries_are_near_duplicates

if TYPE_CHECKING:
    from .engine.budget import ToolBudgetState
    from .engine.results import ToolResultPipelineOutcome


@dataclass(slots=True)
class SearchBatch:
    seen: bool = False
    executed: int = 0
    deferred: int = 0
    duplicate_queries: int = 0
    new_results: int = 0
    duplicate_results: int = 0
    structured_results: int = 0
    labels: list[str] = field(default_factory=list)


class WebSearchPolicy:
    def __init__(self, batch_size: int, total_limit: int):
        self.batch_size, self.total_limit = batch_size, total_limit
        self.seen_queries: set[str] = set()
        self.seen_result_keys: set[str] = set()
        self.unique_results = 0
        self.duplicate_results = 0
        self.no_new_batches = 0

    def reserve(self, arguments: dict[str, Any], batch: SearchBatch, budget: ToolBudgetState) -> tuple[bool, str | None]:
        batch.seen = True
        query_key = _normalize_web_search_query(arguments)
        duplicate = next((query for query in self.seen_queries
                          if _web_search_queries_are_near_duplicates(query_key, query)), None)
        if duplicate is not None:
            batch.duplicate_queries += 1
            return False, (
                "Duplicate web_search query skipped by runtime batching "
                "(exact or near-duplicate). "
                f"It substantially overlaps {duplicate!r}. Use the evidence already "
                "returned and search a genuinely different evidence gap."
            )
        if batch.executed >= self.batch_size:
            batch.deferred += 1
            return False, (
                f"web_search deferred by runtime batching (batch size {self.batch_size}). "
                "Review the current batch results and re-issue only still-missing, non-duplicate queries."
            )
        allowed, error = budget.reserve("web_search")
        if allowed:
            if query_key:
                self.seen_queries.add(query_key)
            batch.executed += 1
        return allowed, error

    def record_result(self, outcome: ToolResultPipelineOutcome, batch: SearchBatch) -> None:
        batch.new_results += outcome.web_search_new_results
        batch.duplicate_results += outcome.web_search_duplicate_results
        self.unique_results += outcome.web_search_new_results
        self.duplicate_results += outcome.web_search_duplicate_results
        batch.structured_results += int(outcome.web_search_inspected)
        batch.labels.extend(outcome.web_search_labels[:3])

    def guidance(self, batch: SearchBatch, total_calls: int) -> str | None:
        if not batch.seen:
            return None
        if batch.executed > 0 and batch.structured_results > 0:
            self.no_new_batches = self.no_new_batches + 1 if batch.new_results == 0 else 0
        lines = [
            "Search batch controller update (internal; do not mention this controller to the user):",
            f"- Executed this batch: {batch.executed}; total executed this turn: {total_calls}/{self.total_limit}; batch size: {self.batch_size}.",
        ]
        if batch.deferred:
            lines.append(f"- Deferred this batch: {batch.deferred}.")
        if batch.duplicate_queries:
            lines.append(f"- Duplicate queries skipped this batch: {batch.duplicate_queries}.")
        if batch.structured_results:
            lines.append(
                f"- New structured results this batch: {batch.new_results}; "
                f"duplicate structured results this batch: {batch.duplicate_results}; "
                f"unique structured results this turn: {self.unique_results}; "
                f"duplicates filtered this turn: {self.duplicate_results}."
            )
        if batch.labels:
            lines.append(f"- New result examples: {'; '.join(batch.labels[:5])}.")
        if total_calls >= self.total_limit:
            lines.append("- The web_search total limit has been reached. Do not call web_search again; synthesize the final answer from gathered evidence and briefly mark gaps.")
        elif self.no_new_batches >= 2:
            lines.append("- Two consecutive structured search batches added no new results. Stop searching unless a critical first-party source is still missing.")
        else:
            lines.append(f"- Before searching again, inspect the deduped evidence. If gaps remain, issue at most {self.batch_size} new, specific, non-duplicate web_search queries.")
        return "\n".join(lines)
