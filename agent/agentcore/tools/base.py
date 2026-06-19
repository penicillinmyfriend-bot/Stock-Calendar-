"""Tool interface shared by every tool the agent can call.

A *tool* is a small, well-described capability (read a file, run the tests,
make a git commit). Tools are deliberately uniform so the orchestrator can:

* advertise them to the local model (``name`` + ``description`` + ``parameters``),
* invoke them by name with a dict of arguments,
* and reason about a uniform :class:`ToolResult` afterwards.

Tools never raise for *expected* failures (a missing file, a failing command);
they return ``ToolResult.failure(...)`` so the agent can reflect and recover.
They only raise for programmer errors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class ToolResult:
    """Uniform result of running a tool."""

    ok: bool
    output: str = ""
    error: str | None = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, output: str = "", **meta: Any) -> "ToolResult":
        return cls(ok=True, output=output, meta=meta)

    @classmethod
    def failure(cls, error: str, **meta: Any) -> "ToolResult":
        return cls(ok=False, error=error, meta=meta)

    def __str__(self) -> str:  # convenient for journaling / prompts
        if self.ok:
            return f"OK: {self.output}".rstrip()
        return f"ERROR: {self.error}"


@dataclass
class ToolContext:
    """Everything a tool needs from its environment.

    ``project_root`` is the sandbox boundary; ``config`` is the loaded
    :class:`agentcore.config.Config` (typed loosely to avoid an import cycle).
    """

    project_root: Path
    config: Any = None


class Tool(ABC):
    """Base class for all tools."""

    #: Stable identifier the model uses to call the tool.
    name: str = ""
    #: One-line human/LLM-facing description.
    description: str = ""
    #: Lightweight parameter schema: ``{"arg": "what it is"}``.
    parameters: Dict[str, str] = {}

    def __init__(self, context: ToolContext) -> None:
        self.context = context

    @property
    def project_root(self) -> Path:
        return self.context.project_root

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool and return a :class:`ToolResult`."""

    def spec(self) -> Dict[str, Any]:
        """Machine-readable description for the model's tool list."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
