"""The agent loop.

Each session the orchestrator:

1. loads its goal + roadmap and the recent journal,
2. switches to a dedicated work branch and records the rollback point,
3. repeatedly asks the local model for the next action (as JSON), runs the
   chosen tool, and -- whenever the working tree changed -- runs the tests and
   either **commits** (green) or **reverts** (red),
4. reflects on each observation and feeds it back into the next prompt,
5. stops at the budget hard-stop or when the model declares a clean stopping
   point, then writes a session summary to the journal.

The model client is injected, so the whole loop is exercised in tests with a
scripted fake -- no Ollama required.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .budget import Budget
from .config import Config
from .persistence import Persistence, utc_timestamp
from .tools import Git, ToolContext, build_registry

DEFAULT_BRANCH = "agent/work"
_MAX_HISTORY = 8

SYSTEM_PROMPT = """\
You are a local, self-improving software agent. You run entirely offline.

Your goal is described in the ROADMAP below. You pursue it by taking ONE action
at a time using the available tools.

Hard rules you cannot change:
- You may only read/write inside the project sandbox.
- Every change you make to files is automatically tested. If the tests pass the
  change is committed to git; if they fail it is reverted. So make small,
  test-safe steps and keep the suite green.
- You cannot extend your time/iteration budget. When it runs out you stop.
- Keep ROADMAP.md and your progress notes current by editing files with tools.

Available tools:
{tools}

Respond with a SINGLE JSON object and nothing else, of the form:
{{"thought": "<brief reasoning>",
  "tool": "<tool name, or null to stop>",
  "args": {{<arguments for the tool>}},
  "commit_message": "<message to use if this change is kept (optional)>",
  "done": <true to end the session at a clean stopping point, else false>}}
"""


@dataclass
class ActionRecord:
    iteration: int
    thought: str
    tool: Optional[str]
    args: Dict[str, Any]
    ok: bool
    observation: str
    committed: bool = False
    commit: Optional[str] = None


@dataclass
class SessionResult:
    stop_reason: str
    iterations: int
    commits: List[str] = field(default_factory=list)
    actions: List[ActionRecord] = field(default_factory=list)
    summary: str = ""


def parse_action(text: str) -> Dict[str, Any]:
    """Extract a single JSON action object from model output, forgivingly."""
    cleaned = text.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    # Otherwise grab from the first '{' to the last '}'.
    if not cleaned.startswith("{"):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"thought": text[:200], "tool": None, "done": False, "_parse_error": True}


class Orchestrator:
    def __init__(
        self,
        config: Config,
        llm: Any,
        *,
        branch: str = DEFAULT_BRANCH,
        logger: Any = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.branch = branch
        self.log = logger or (lambda *a, **k: None)

        self.project_root = Path(config.project_root)
        self.context = ToolContext(project_root=self.project_root, config=config)
        # Autonomous loop: harness owns commits, so withhold git write tools.
        self.registry = build_registry(self.context, expose_git_write=False)
        self.git = Git(self.project_root)

        config_dir = Path(config.config_path).parent
        self.persistence = Persistence(
            roadmap_path=config_dir / "ROADMAP.md",
            journal_path=config_dir / "JOURNAL.md",
            state_dir=config.state_dir,
        )

    # ------------------------------------------------------------------ #
    def run(self, budget: Budget) -> SessionResult:
        if not self.git.is_repo():
            raise RuntimeError(f"{self.project_root} is not a git repository")

        self.git.ensure_branch(self.branch)
        start_commit = self.git.head_hash()
        self.persistence.record_session_start(start_commit)
        self.log(f"session start on branch '{self.branch}' at {start_commit[:8]}")

        roadmap = self.persistence.read_roadmap()
        history: List[str] = []
        actions: List[ActionRecord] = []
        commits: List[str] = []

        budget.start()
        stop_reason = "completed"
        while budget.should_continue():
            iteration = budget.iterations + 1
            try:
                raw = self.llm.chat(self._messages(roadmap, history), format="json")
            except Exception as exc:  # model unreachable -> stop cleanly
                stop_reason = f"model error: {exc}"
                break

            action = parse_action(raw)
            thought = str(action.get("thought", "")).strip()

            if action.get("done"):
                stop_reason = "agent reported a clean stopping point"
                if thought:
                    history.append(f"[{iteration}] done: {thought}")
                budget.tick()
                break

            tool_name = action.get("tool")
            if not tool_name:
                obs = "no tool selected; respond with a valid JSON action"
                history.append(f"[{iteration}] {obs}")
                actions.append(ActionRecord(iteration, thought, None, {}, False, obs))
                budget.tick()
                continue

            args = action.get("args") or {}
            result = self.registry.dispatch(tool_name, args)
            committed, commit_hash, gate_note = self._test_and_commit(action, iteration)
            if commit_hash:
                commits.append(commit_hash)

            observation = self._format_observation(result, gate_note)
            record = ActionRecord(
                iteration, thought, tool_name, args, result.ok, observation,
                committed=committed, commit=commit_hash,
            )
            actions.append(record)
            history.append(f"[{iteration}] {tool_name}: {observation}")
            self.log(f"iter {iteration}: {tool_name} -> {observation}")

            budget.tick()
        else:
            stop_reason = budget.stop_reason() or "completed"

        if budget.exhausted() and budget.stop_reason():
            stop_reason = budget.stop_reason()

        result = SessionResult(
            stop_reason=stop_reason,
            iterations=budget.iterations,
            commits=commits,
            actions=actions,
        )
        result.summary = self._write_summary(result, start_commit)
        # Commit the journal/roadmap updates so a later revert can never lose
        # them (markdown housekeeping, so no test gate needed).
        if self.git.has_changes():
            journal_commit = self.git.commit(f"agent: session journal {utc_timestamp()}")
            if journal_commit:
                self.log(f"journal committed at {journal_commit[:8]}")
        self.log(f"session end: {stop_reason}; {len(commits)} commit(s)")
        return result

    # ------------------------------------------------------------------ #
    def _messages(self, roadmap: str, history: List[str]) -> List[Dict[str, str]]:
        system = SYSTEM_PROMPT.format(tools=self.registry.describe())
        recent = "\n".join(history[-_MAX_HISTORY:]) or "(nothing yet)"
        journal_tail = self.persistence.latest_journal_entry()
        user = (
            f"# ROADMAP\n{roadmap}\n\n"
            f"# Recent journal\n{journal_tail}\n\n"
            f"# Recent actions this session\n{recent}\n\n"
            "What is your next action? Respond with a single JSON object."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _test_and_commit(self, action: Dict[str, Any], iteration: int):
        """If the working tree changed, test it and commit or revert.

        Returns ``(committed, commit_hash, note)``.
        """
        if not self.git.has_changes():
            return False, None, "no file changes"

        test_result = self.registry.dispatch("run_tests", {})
        if test_result.ok:
            message = (
                action.get("commit_message")
                or f"agent: {str(action.get('thought', 'change'))[:60]}"
            )
            commit_hash = self.git.commit(message)
            if commit_hash:
                self.persistence.record_good_commit(commit_hash)
                return True, commit_hash, f"tests passed -> committed {commit_hash[:8]}"
            return False, None, "tests passed but nothing to commit"

        # Tests failed: revert the change so HEAD stays green.
        self.git.discard_changes()
        fail = (test_result.error or "tests failed").splitlines()
        tail = " ".join(fail[-3:]) if fail else "tests failed"
        return False, None, f"tests FAILED -> reverted ({tail})"

    @staticmethod
    def _format_observation(result, gate_note: str) -> str:
        head = "ok" if result.ok else f"error: {result.error}"
        body = (result.output or "").strip()
        if body:
            body = body if len(body) <= 500 else body[:500] + "..."
            head = f"{head} | {body}"
        return f"{head} [{gate_note}]"

    def _write_summary(self, result: SessionResult, start_commit: str) -> str:
        ts = utc_timestamp()
        tool_counts: Dict[str, int] = {}
        for a in result.actions:
            if a.tool:
                tool_counts[a.tool] = tool_counts.get(a.tool, 0) + 1
        tools_used = ", ".join(f"{k}×{v}" for k, v in tool_counts.items()) or "none"
        commit_lines = "\n".join(f"  - {c[:8]}" for c in result.commits) or "  (none)"

        entry = (
            f"## Session {ts}\n\n"
            f"- Branch: `{self.branch}` (started at `{start_commit[:8]}`)\n"
            f"- Stop reason: {result.stop_reason}\n"
            f"- Iterations: {result.iterations}\n"
            f"- Tools used: {tools_used}\n"
            f"- Commits ({len(result.commits)}):\n{commit_lines}\n"
        )
        if result.actions:
            last = result.actions[-1]
            entry += f"- Last action: {last.tool or 'none'} — {last.observation}\n"

        self.persistence.append_journal(entry)
        self.persistence.record_session_summary(
            {
                "timestamp": ts,
                "stop_reason": result.stop_reason,
                "iterations": result.iterations,
                "commits": result.commits,
            }
        )
        return entry
