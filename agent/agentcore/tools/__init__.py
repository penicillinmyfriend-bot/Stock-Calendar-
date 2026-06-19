"""Tool registry.

Builds the set of tools available to the agent for a given run. The optional
web tools are included **only** when ``web.enabled`` is true in the config, so
a disabled web tool isn't even advertised to the model.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Tool, ToolContext, ToolResult
from .fs import ReadFileTool, WriteFileTool
from .git_tools import (
    Git,
    GitBranchTool,
    GitCommitTool,
    GitDiffTool,
    GitStatusTool,
)
from .shell import RunCommandTool, RunTestsTool
from .web import WebFetchTool, WebSearchTool

__all__ = [
    "Tool",
    "ToolContext",
    "ToolResult",
    "ToolRegistry",
    "build_registry",
    "Git",
]


class ToolRegistry:
    """A name -> tool mapping with helpers for prompting and dispatch."""

    def __init__(self, tools: List[Tool]) -> None:
        self._tools: Dict[str, Tool] = {t.name: t for t in tools}

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self):
        return iter(self._tools.values())

    def names(self) -> List[str]:
        return list(self._tools)

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def specs(self) -> List[Dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    def describe(self) -> str:
        """A compact, model-facing description of every available tool."""
        lines = []
        for t in self._tools.values():
            params = ", ".join(t.parameters) if t.parameters else "(no args)"
            lines.append(f"- {t.name}({params}): {t.description}")
        return "\n".join(lines)

    def dispatch(self, name: str, args: Dict[str, Any]) -> ToolResult:
        """Invoke a tool by name, converting bad input into a ToolResult."""
        if name not in self._tools:
            return ToolResult.failure(f"unknown tool: {name}")
        try:
            return self._tools[name].run(**(args or {}))
        except TypeError as exc:
            return ToolResult.failure(f"bad arguments for {name}: {exc}")


def build_registry(context: ToolContext, *, expose_git_write: bool = True) -> ToolRegistry:
    """Construct the tools available for a run, honoring config (e.g. web).

    When ``expose_git_write`` is False the mutating git tools (commit/branch)
    are withheld. The autonomous loop uses this so that *only the harness*
    commits -- and only after tests pass -- guaranteeing the test gate.
    """
    tools: List[Tool] = [
        ReadFileTool(context),
        WriteFileTool(context),
        RunCommandTool(context),
        RunTestsTool(context),
        GitStatusTool(context),
        GitDiffTool(context),
    ]
    if expose_git_write:
        tools.append(GitCommitTool(context))
        tools.append(GitBranchTool(context))
    web = getattr(context.config, "web", None)
    if web and getattr(web, "enabled", False):
        tools.append(WebSearchTool(context))
        tools.append(WebFetchTool(context))
    return ToolRegistry(tools)
