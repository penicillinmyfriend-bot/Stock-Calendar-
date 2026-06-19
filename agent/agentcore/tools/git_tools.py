"""Git operations.

Two layers:

* :class:`Git` -- a thin, programmatic wrapper the orchestrator uses to run the
  *branch -> test -> commit-or-revert* loop and to power ``agent rollback``.
* A set of LLM-facing :class:`~agentcore.tools.base.Tool` wrappers
  (``git_status``, ``git_diff``, ``git_commit``, ``git_branch``) so the agent
  can inspect and record its own work while it reasons.

Every git invocation is scoped to the project with ``git -C <root>``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .base import Tool, ToolResult


class GitError(Exception):
    """Raised for an unexpected git failure (programmer-level error)."""


class Git:
    """Programmatic git wrapper scoped to a single repository."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _run(self, *args: str, check: bool = False) -> Tuple[int, str]:
        proc = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
        )
        out = (proc.stdout + proc.stderr).strip()
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {out}")
        return proc.returncode, out

    # --- queries ----------------------------------------------------------
    def is_repo(self) -> bool:
        code, out = self._run("rev-parse", "--is-inside-work-tree")
        return code == 0 and out.strip() == "true"

    def current_branch(self) -> str:
        return self._run("rev-parse", "--abbrev-ref", "HEAD", check=True)[1]

    def head_hash(self) -> str:
        return self._run("rev-parse", "HEAD", check=True)[1]

    def status_porcelain(self) -> str:
        return self._run("status", "--porcelain", check=True)[1]

    def has_changes(self) -> bool:
        return bool(self.status_porcelain())

    def log(self, n: int = 10) -> str:
        return self._run("log", f"-n{n}", "--oneline", "--decorate")[1]

    def diff(self, staged: bool = False, path: Optional[str] = None) -> str:
        args: List[str] = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args += ["--", path]
        return self._run(*args)[1]

    # --- mutations --------------------------------------------------------
    def create_branch(self, name: str) -> None:
        self._run("checkout", "-b", name, check=True)

    def checkout(self, name: str) -> None:
        self._run("checkout", name, check=True)

    def ensure_branch(self, name: str) -> None:
        """Switch to *name*, creating it from HEAD if it does not exist."""
        if self.current_branch() == name:
            return
        code, _ = self._run("rev-parse", "--verify", "--quiet", name)
        if code == 0:
            self.checkout(name)
        else:
            self.create_branch(name)

    def stage_all(self) -> None:
        self._run("add", "-A", check=True)

    def commit(self, message: str) -> Optional[str]:
        """Stage everything and commit. Returns the new hash, or None if the
        working tree was clean (nothing to commit)."""
        self.stage_all()
        if not self.has_changes() and self._run("diff", "--cached", "--quiet")[0] == 0:
            return None
        code, out = self._run("commit", "-m", message)
        if code != 0:
            # Nothing to commit is not an error we want to crash on.
            if "nothing to commit" in out:
                return None
            raise GitError(f"commit failed: {out}")
        return self.head_hash()

    def discard_changes(self) -> None:
        """Revert the working tree to HEAD, dropping new/modified files.

        Ignored files (e.g. the agent's ``.agent/`` state dir) are preserved,
        because ``git clean`` never removes ignored paths without ``-x``.
        """
        self._run("reset", "--hard", "HEAD", check=True)
        self._run("clean", "-fd")

    def reset_hard(self, ref: str) -> None:
        self._run("reset", "--hard", ref, check=True)


# --------------------------------------------------------------------------- #
# LLM-facing tools
# --------------------------------------------------------------------------- #
class _GitTool(Tool):
    """Base for git tools: exposes a configured :class:`Git` instance."""

    @property
    def git(self) -> Git:
        return Git(self.project_root)


class GitStatusTool(_GitTool):
    name = "git_status"
    description = "Show the current branch and the working-tree status."
    parameters: dict = {}

    def run(self, **_: Any) -> ToolResult:
        try:
            branch = self.git.current_branch()
            status = self.git.status_porcelain() or "(clean)"
        except GitError as exc:
            return ToolResult.failure(str(exc))
        return ToolResult.success(f"branch: {branch}\n{status}", branch=branch)


class GitDiffTool(_GitTool):
    name = "git_diff"
    description = "Show the diff of current changes (optionally staged, or for one path)."
    parameters = {
        "staged": "If true, show staged changes instead of unstaged.",
        "path": "Optional path to limit the diff to.",
    }

    def run(self, *, staged: bool = False, path: Optional[str] = None, **_: Any) -> ToolResult:
        return ToolResult.success(self.git.diff(staged=staged, path=path) or "(no diff)")


class GitCommitTool(_GitTool):
    name = "git_commit"
    description = "Stage all changes and commit them with a message."
    parameters = {"message": "The commit message."}

    def run(self, *, message: str, **_: Any) -> ToolResult:
        try:
            sha = self.git.commit(message)
        except GitError as exc:
            return ToolResult.failure(str(exc))
        if sha is None:
            return ToolResult.failure("nothing to commit")
        return ToolResult.success(f"committed {sha[:8]}: {message}", commit=sha)


class GitBranchTool(_GitTool):
    name = "git_branch"
    description = "Create and/or switch to a branch."
    parameters = {"name": "Branch name to switch to (created if missing)."}

    def run(self, *, name: str, **_: Any) -> ToolResult:
        try:
            self.git.ensure_branch(name)
        except GitError as exc:
            return ToolResult.failure(str(exc))
        return ToolResult.success(f"on branch {name}", branch=name)
