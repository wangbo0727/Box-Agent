"""Prepare one request through the existing exposure and visibility policies."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from ..base import Tool, build_tool_name_index
from .contracts import PreparedTools, ToolDefinitionView

if TYPE_CHECKING:
    from ..mcp_tool_search import MCPToolExposureManager


def prepare_tools(
    candidates: Iterable[Tool],
    *,
    tool_exposure: MCPToolExposureManager | None = None,
    is_tool_visible: Callable[[Tool], bool] | None = None,
) -> PreparedTools:
    """Freeze offered definitions and bind calls to their actual tool objects."""

    offered = list(candidates)
    registered_names = frozenset(tool.name for tool in offered)
    generations: dict[str, int] = {}
    if tool_exposure is not None:
        exposure = tool_exposure.prepare_tools(offered)
        offered = exposure.tools
        generations = dict(exposure.mcp_generations)
    else:
        generations = {
            tool.name: tool.mcp_generation
            for tool in offered
            if getattr(tool, "mcp_tool_id", None) is not None
            and isinstance(getattr(tool, "mcp_generation", None), int)
        }
    if is_tool_visible is not None:
        offered = [tool for tool in offered if is_tool_visible(tool)]
    name_index = build_tool_name_index(offered)
    targets = {tool.name: tool for tool in offered}
    return PreparedTools(
        definitions=tuple(ToolDefinitionView.from_tool(tool) for tool in offered),
        targets=targets,
        call_names={name: tool.name for name, tool in name_index.items()},
        mcp_generations={
            name: generation
            for name, generation in generations.items()
            if name in targets
        },
        _tool_exposure=tool_exposure,
        _registered_names=registered_names,
    )
