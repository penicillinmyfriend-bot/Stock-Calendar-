"""Filesystem tools, confined to the project root.

``read_file`` and ``write_file`` both route every path through
:func:`agentcore.safety.resolve_in_project`, so the agent can never read or
write outside its sandbox -- not via ``..``, an absolute path, or a symlink.
"""

from __future__ import annotations

from typing import Any

from ..safety import SafetyError, resolve_in_project
from .base import Tool, ToolResult

# A defensive cap so a single read can't blow up the model's context window.
DEFAULT_MAX_READ_BYTES = 200_000


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file inside the project. Returns its contents."
    parameters = {
        "path": "Project-relative (or absolute-inside-project) path to read.",
        "max_bytes": f"Optional cap on bytes read (default {DEFAULT_MAX_READ_BYTES}).",
    }

    def run(self, *, path: str, max_bytes: int = DEFAULT_MAX_READ_BYTES, **_: Any) -> ToolResult:
        try:
            target = resolve_in_project(self.project_root, path)
        except SafetyError as exc:
            return ToolResult.failure(str(exc))
        if not target.exists():
            return ToolResult.failure(f"no such file: {path}")
        if target.is_dir():
            return ToolResult.failure(f"{path} is a directory, not a file")
        try:
            data = target.read_bytes()[: int(max_bytes)]
            text = data.decode("utf-8", errors="replace")
        except OSError as exc:
            return ToolResult.failure(f"could not read {path}: {exc}")
        return ToolResult.success(text, path=str(target), bytes=len(data))


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Create or modify a text file inside the project. Parent directories "
        "are created as needed. Use mode='append' to append instead of overwrite."
    )
    parameters = {
        "path": "Project-relative (or absolute-inside-project) path to write.",
        "content": "Full text to write (or to append when mode='append').",
        "mode": "'overwrite' (default) or 'append'.",
    }

    def run(self, *, path: str, content: str, mode: str = "overwrite", **_: Any) -> ToolResult:
        if mode not in ("overwrite", "append"):
            return ToolResult.failure(f"invalid mode {mode!r}; use 'overwrite' or 'append'")
        try:
            target = resolve_in_project(self.project_root, path)
        except SafetyError as exc:
            return ToolResult.failure(str(exc))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with target.open("a", encoding="utf-8") as fh:
                    fh.write(content)
            else:
                target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"could not write {path}: {exc}")
        return ToolResult.success(
            f"wrote {len(content)} chars to {path} (mode={mode})",
            path=str(target),
            bytes=len(content.encode("utf-8")),
        )
