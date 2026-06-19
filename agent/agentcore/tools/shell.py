"""Sandboxed command execution and the test runner.

``run_command`` executes a *single* program (no shell, so no pipes,
redirects, or ``&&`` chaining) after the command clears
:func:`agentcore.safety.check_command`. ``run_tests`` runs the project's
configured test command and reports pass/fail -- this is the signal the
orchestrator uses to decide commit-vs-revert.
"""

from __future__ import annotations

import shlex
import subprocess
from typing import Any, List, Tuple

from ..safety import SafetyError, check_command
from .base import Tool, ToolResult

# Shell control characters. We run with shell=False (so these are inert and
# safe), but we still reject an *unquoted* operator and tell the model to run
# one program at a time, since piping/chaining wouldn't work as intended.
_OPERATOR_CHARS = set("();<>|&")


def _has_shell_operators(command: str) -> bool:
    """True if *command* contains an unquoted shell operator (| & ; < > ( ))."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return True  # unbalanced quotes -> treat as suspicious
    return any(tok and set(tok) <= _OPERATOR_CHARS for tok in tokens)

# Cap captured output so a noisy command can't flood the model context.
_MAX_OUTPUT_CHARS = 20_000

DEFAULT_TEST_COMMAND = "python -m unittest discover -s agent/tests -t agent"


def _command_policy(config: Any) -> Tuple[List[str], List[str], int]:
    """Pull (allowlist, denylist, timeout) from a Config, with safe defaults."""
    commands = getattr(config, "commands", None)
    allowlist = list(getattr(commands, "allowlist", []) or [])
    denylist = list(getattr(commands, "denylist", []) or [])
    timeout = int(getattr(commands, "timeout", 120) or 120)
    return allowlist, denylist, timeout


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    head = _MAX_OUTPUT_CHARS // 2
    tail = _MAX_OUTPUT_CHARS - head
    return text[:head] + "\n...[truncated]...\n" + text[-tail:]


def _run_argv(argv: List[str], cwd, timeout: int) -> Tuple[int, str]:
    """Execute argv (no shell). Returns (returncode, combined_output)."""
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, f"command not found: {argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"command timed out after {timeout}s"
    combined = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, _truncate(combined)


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "Run a single sandboxed program inside the project (no shell pipes, "
        "redirects, or && chaining). Returns combined stdout/stderr and the "
        "exit code."
    )
    parameters = {
        "command": "The command to run, e.g. 'python script.py --flag'.",
        "timeout": "Optional per-command timeout in seconds.",
    }

    def run(self, *, command: str, timeout: int | None = None, **_: Any) -> ToolResult:
        allowlist, denylist, default_timeout = _command_policy(self.context.config)
        if _has_shell_operators(command):
            return ToolResult.failure(
                "shell operators are not allowed; run one program at a time"
            )
        try:
            check_command(
                command,
                project_root=self.project_root,
                allowlist=allowlist,
                denylist=denylist,
            )
        except SafetyError as exc:
            return ToolResult.failure(f"blocked by sandbox: {exc}")

        argv = shlex.split(command)
        code, output = _run_argv(argv, self.project_root, timeout or default_timeout)
        if code == 0:
            return ToolResult.success(output, returncode=0)
        return ToolResult.failure(
            f"command exited with code {code}\n{output}", returncode=code
        )


class RunTestsTool(Tool):
    name = "run_tests"
    description = (
        "Run the project's test suite. Succeeds only if every test passes "
        "(exit code 0). This is the gate for keeping or reverting a change."
    )
    parameters: dict = {}

    def run(self, **_: Any) -> ToolResult:
        tests_cfg = getattr(self.context.config, "tests", None)
        command = getattr(tests_cfg, "command", None) or DEFAULT_TEST_COMMAND
        _, _, default_timeout = _command_policy(self.context.config)
        # The test command comes from config (trusted) but is still screened.
        try:
            check_command(command, project_root=self.project_root)
        except SafetyError as exc:
            return ToolResult.failure(f"test command blocked by sandbox: {exc}")

        argv = shlex.split(command)
        code, output = _run_argv(argv, self.project_root, max(default_timeout, 300))
        passed = code == 0
        result = ToolResult(
            ok=passed,
            output=output if passed else "",
            error=None if passed else f"tests failed (exit {code})\n{output}",
            meta={"returncode": code, "command": command},
        )
        return result
