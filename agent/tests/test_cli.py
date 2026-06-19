"""Tests for the CLI commands that don't need a running model."""

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from agentcore import cli
from agentcore.config import Config
from agentcore.persistence import Persistence
from agentcore.tools.git_tools import Git

CONFIG_YAML = """\
model:
  name: test-model
paths:
  project_root: "."
  state_dir: ".agent"
web:
  enabled: false
tests:
  command: "python -c \\"print('ok')\\""
"""


def build_repo(root: Path) -> Path:
    def g(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "T")
    g("config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text(".agent/\n")
    cfg = root / "config.yaml"
    cfg.write_text(CONFIG_YAML)
    (root / "ROADMAP.md").write_text("# Roadmap\n")
    (root / "JOURNAL.md").write_text("# Journal\n")
    g("add", "-A")
    g("commit", "-q", "-m", "initial")
    return cfg


def run_cli(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = cli.main(argv)
    return code, out.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.cfg = build_repo(self.root)
        self.addCleanup(self.tmp.cleanup)

    def test_status(self):
        code, out = run_cli(["--config", str(self.cfg), "status"])
        self.assertEqual(code, 0)
        self.assertIn("test-model", out)
        self.assertIn("current branch", out)

    def test_log_empty(self):
        code, out = run_cli(["--config", str(self.cfg), "log"])
        self.assertEqual(code, 0)

    def test_no_command_prints_help(self):
        code, _ = run_cli(["--config", str(self.cfg)])
        self.assertEqual(code, 1)

    def test_rollback_to_session_start(self):
        git = Git(self.root)
        cfg = Config.load(self.cfg)
        persistence = Persistence(
            roadmap_path=self.root / "ROADMAP.md",
            journal_path=self.root / "JOURNAL.md",
            state_dir=cfg.state_dir,
        )
        start = git.head_hash()
        persistence.record_session_start(start)

        # Make a commit we will roll back.
        (self.root / "extra.txt").write_text("temp")
        git.commit("a change to undo")
        self.assertNotEqual(git.head_hash(), start)

        code, out = run_cli(["--config", str(self.cfg), "rollback", "--yes"])
        self.assertEqual(code, 0, out)
        self.assertEqual(git.head_hash(), start)
        self.assertFalse((self.root / "extra.txt").exists())

    def test_rollback_no_target(self):
        code, out = run_cli(["--config", str(self.cfg), "rollback", "--yes"])
        self.assertEqual(code, 1)
        self.assertIn("nothing to roll back", out)

    def test_rollback_requires_approval_without_tty(self):
        git = Git(self.root)
        persistence = Persistence(
            roadmap_path=self.root / "ROADMAP.md",
            journal_path=self.root / "JOURNAL.md",
            state_dir=Config.load(self.cfg).state_dir,
        )
        persistence.record_session_start(git.head_hash())
        # No --yes and no TTY -> refuse.
        code, out = run_cli(["--config", str(self.cfg), "rollback"])
        self.assertEqual(code, 1)
        self.assertIn("not approved", out)


if __name__ == "__main__":
    unittest.main()
