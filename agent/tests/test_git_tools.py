"""Tests for the git wrapper and git tools (using a throwaway repo)."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from agentcore.tools.base import ToolContext
from agentcore.tools.git_tools import Git, GitBranchTool, GitCommitTool, GitStatusTool


def init_repo(root: Path) -> Git:
    def run(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    run("config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hello\n")
    run("add", "-A")
    run("commit", "-q", "-m", "initial")
    return Git(root)


class GitWrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.git = init_repo(self.root)
        self.addCleanup(self.tmp.cleanup)

    def test_is_repo_and_branch(self):
        self.assertTrue(self.git.is_repo())
        self.assertTrue(self.git.current_branch())

    def test_create_branch_and_commit(self):
        self.git.create_branch("feature/x")
        self.assertEqual(self.git.current_branch(), "feature/x")
        (self.root / "new.txt").write_text("data")
        self.assertTrue(self.git.has_changes())
        sha = self.git.commit("add new.txt")
        self.assertIsNotNone(sha)
        self.assertFalse(self.git.has_changes())

    def test_commit_nothing_returns_none(self):
        self.assertIsNone(self.git.commit("noop"))

    def test_discard_changes_reverts_modifications_and_new_files(self):
        before = self.git.head_hash()
        (self.root / "README.md").write_text("CHANGED\n")
        (self.root / "junk.txt").write_text("temp")
        self.git.discard_changes()
        self.assertEqual(self.git.head_hash(), before)
        self.assertEqual((self.root / "README.md").read_text(), "hello\n")
        self.assertFalse((self.root / "junk.txt").exists())

    def test_reset_hard_rolls_back_a_commit(self):
        good = self.git.head_hash()
        (self.root / "a.txt").write_text("x")
        self.git.commit("bad commit")
        self.assertNotEqual(self.git.head_hash(), good)
        self.git.reset_hard(good)
        self.assertEqual(self.git.head_hash(), good)
        self.assertFalse((self.root / "a.txt").exists())

    def test_ensure_branch_switches_and_creates(self):
        start = self.git.current_branch()
        self.git.ensure_branch("work")
        self.assertEqual(self.git.current_branch(), "work")
        self.git.ensure_branch(start)
        self.git.ensure_branch("work")  # existing branch, just switch
        self.assertEqual(self.git.current_branch(), "work")


class GitToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        init_repo(self.root)
        self.ctx = ToolContext(project_root=self.root)
        self.addCleanup(self.tmp.cleanup)

    def test_status_tool(self):
        r = GitStatusTool(self.ctx).run()
        self.assertTrue(r.ok, r.error)
        self.assertIn("branch:", r.output)

    def test_branch_then_commit_tool(self):
        self.assertTrue(GitBranchTool(self.ctx).run(name="t/1").ok)
        (self.root / "f.txt").write_text("y")
        r = GitCommitTool(self.ctx).run(message="add f")
        self.assertTrue(r.ok, r.error)
        self.assertIn("commit", r.meta)

    def test_commit_tool_nothing_to_commit(self):
        r = GitCommitTool(self.ctx).run(message="noop")
        self.assertFalse(r.ok)


if __name__ == "__main__":
    unittest.main()
