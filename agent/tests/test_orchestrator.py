"""End-to-end tests for the agent loop, using a scripted fake model.

A real throwaway git repo + test suite is created so the
test-then-commit-or-revert behaviour is exercised for real -- only the model is
faked.
"""

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from agentcore.budget import Budget
from agentcore.config import Config
from agentcore.orchestrator import Orchestrator, parse_action
from agentcore.tools.git_tools import Git

CONFIG_YAML = """\
model:
  name: test-model
session:
  default_minutes: 10
  default_iterations: 25
paths:
  project_root: "."
  state_dir: ".agent"
web:
  enabled: false
commands:
  allowlist: []
  denylist: []
  timeout: 60
tests:
  command: "python -m unittest discover -s suite -t ."
"""


class FakeLLM:
    """Returns scripted JSON actions; falls back to a 'done' action."""

    def __init__(self, responses):
        self.responses = [json.dumps(r) if isinstance(r, dict) else r for r in responses]
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return json.dumps({"thought": "stopping", "done": True})


class LoopingLLM:
    """Always returns the same action (used to test the budget hard stop)."""

    def __init__(self, action):
        self.action = json.dumps(action)
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.action


def build_project(root: Path) -> Config:
    def g(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "T")
    g("config", "commit.gpgsign", "false")

    (root / ".gitignore").write_text(".agent/\n")
    (root / "config.yaml").write_text(CONFIG_YAML)
    (root / "ROADMAP.md").write_text("# Roadmap\n\nGoal: stay green.\n")
    (root / "JOURNAL.md").write_text("# Journal\n")
    (root / "app.py").write_text("def add(a, b):\n    return a + b\n")
    suite = root / "suite"
    suite.mkdir()
    (suite / "__init__.py").write_text("")
    (suite / "test_app.py").write_text(textwrap.dedent("""\
        import unittest
        from app import add
        class T(unittest.TestCase):
            def test_add(self):
                self.assertEqual(add(1, 2), 3)
    """))
    g("add", "-A")
    g("commit", "-q", "-m", "initial project")
    return Config.load(root / "config.yaml")


class ParseActionTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(parse_action('{"tool": "x"}')["tool"], "x")

    def test_fenced_json(self):
        a = parse_action('```json\n{"tool": "y", "done": false}\n```')
        self.assertEqual(a["tool"], "y")

    def test_json_with_prose(self):
        a = parse_action('Sure! {"tool": "z"} hope that helps')
        self.assertEqual(a["tool"], "z")

    def test_garbage_is_safe(self):
        a = parse_action("not json at all")
        self.assertIsNone(a["tool"])
        self.assertTrue(a["_parse_error"])


class OrchestratorLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.config = build_project(self.root)
        self.git = Git(self.root)
        self.addCleanup(self.tmp.cleanup)

    def test_green_change_is_committed(self):
        llm = FakeLLM([
            {"thought": "add a helper", "tool": "write_file",
             "args": {"path": "helper.py", "content": "X = 1\n"},
             "commit_message": "add helper"},
            {"thought": "done", "done": True},
        ])
        orch = Orchestrator(self.config, llm)
        result = orch.run(Budget(max_iterations=10))
        self.assertEqual(len(result.commits), 1)
        self.assertTrue((self.root / "helper.py").exists())
        # The commit is on the agent's work branch.
        self.assertEqual(self.git.current_branch(), "agent/work")
        log = self.git.log(5)
        self.assertIn("add helper", log)

    def test_red_change_is_reverted(self):
        llm = FakeLLM([
            {"thought": "break add", "tool": "write_file",
             "args": {"path": "app.py", "content": "def add(a, b):\n    return a - b\n"}},
            {"thought": "done", "done": True},
        ])
        orch = Orchestrator(self.config, llm)
        result = orch.run(Budget(max_iterations=10))
        self.assertEqual(len(result.commits), 0)
        # The breaking change was reverted, so the suite still passes.
        self.assertEqual((self.root / "app.py").read_text(), "def add(a, b):\n    return a + b\n")
        self.assertFalse(self.git.has_changes())

    def test_clean_stop(self):
        llm = FakeLLM([{"thought": "nothing to do", "done": True}])
        orch = Orchestrator(self.config, llm)
        result = orch.run(Budget(max_iterations=10))
        self.assertIn("clean stopping point", result.stop_reason)
        self.assertEqual(len(result.commits), 0)

    def test_budget_hard_stop_iterations(self):
        # The model never stops; the iteration budget must.
        llm = LoopingLLM({"thought": "peek", "tool": "read_file", "args": {"path": "app.py"}})
        orch = Orchestrator(self.config, llm)
        result = orch.run(Budget(max_iterations=3))
        self.assertEqual(result.iterations, 3)
        self.assertEqual(llm.calls, 3)
        self.assertIn("iteration budget", result.stop_reason)

    def test_session_summary_written_to_journal(self):
        llm = FakeLLM([{"thought": "stop", "done": True}])
        orch = Orchestrator(self.config, llm)
        orch.run(Budget(max_iterations=5))
        journal = (self.root / "JOURNAL.md").read_text()
        self.assertIn("## Session", journal)
        self.assertIn("Stop reason", journal)
        # Run state records the session-start (rollback) commit.
        state = orch.persistence.load_state()
        self.assertIsNotNone(state.session_start_commit)

    def test_multiple_changes_accumulate_commits(self):
        llm = FakeLLM([
            {"thought": "f1", "tool": "write_file", "args": {"path": "a.py", "content": "A=1\n"}},
            {"thought": "f2", "tool": "write_file", "args": {"path": "b.py", "content": "B=2\n"}},
            {"thought": "done", "done": True},
        ])
        orch = Orchestrator(self.config, llm)
        result = orch.run(Budget(max_iterations=10))
        self.assertEqual(len(result.commits), 2)


if __name__ == "__main__":
    unittest.main()
