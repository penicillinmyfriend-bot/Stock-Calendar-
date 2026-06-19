"""Tests for the sandboxed command runner and the test runner."""

import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace

from agentcore.tools.base import ToolContext
from agentcore.tools.shell import RunCommandTool, RunTestsTool


def make_config(allowlist=None, denylist=None, timeout=30, test_command=None):
    return SimpleNamespace(
        commands=SimpleNamespace(
            allowlist=allowlist or [],
            denylist=denylist or [],
            timeout=timeout,
        ),
        tests=SimpleNamespace(command=test_command),
    )


class RunCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.ctx = ToolContext(project_root=self.root, config=make_config())
        self.tool = RunCommandTool(self.ctx)
        self.addCleanup(self.tmp.cleanup)

    def test_simple_command_runs(self):
        r = self.tool.run(command="python -c \"print('hi')\"")
        self.assertTrue(r.ok, r.error)
        self.assertIn("hi", r.output)

    def test_nonzero_exit_is_failure(self):
        r = self.tool.run(command="python -c \"import sys; sys.exit(3)\"")
        self.assertFalse(r.ok)
        self.assertEqual(r.meta["returncode"], 3)

    def test_shell_operators_blocked(self):
        r = self.tool.run(command="echo a | echo b")
        self.assertFalse(r.ok)
        self.assertIn("shell operators", r.error)

    def test_sandbox_blocks_system_path(self):
        r = self.tool.run(command="cat /etc/passwd")
        self.assertFalse(r.ok)
        self.assertIn("blocked by sandbox", r.error)

    def test_allowlist_enforced(self):
        ctx = ToolContext(
            project_root=self.root, config=make_config(allowlist=["python"])
        )
        tool = RunCommandTool(ctx)
        r = tool.run(command="ls")
        self.assertFalse(r.ok)

    def test_timeout(self):
        r = self.tool.run(command="python -c \"import time; time.sleep(5)\"", timeout=1)
        self.assertFalse(r.ok)
        self.assertEqual(r.meta["returncode"], 124)


class RunTestsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)

    def _write_suite(self, body: str):
        tdir = self.root / "suite"
        tdir.mkdir(exist_ok=True)
        (tdir / "__init__.py").write_text("")
        (tdir / "test_x.py").write_text(textwrap.dedent(body))

    def test_passing_suite_reports_ok(self):
        self._write_suite(
            """
            import unittest
            class T(unittest.TestCase):
                def test_ok(self): self.assertTrue(True)
            """
        )
        cfg = make_config(test_command="python -m unittest discover -s suite -t .")
        tool = RunTestsTool(ToolContext(project_root=self.root, config=cfg))
        r = tool.run()
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.meta["returncode"], 0)

    def test_failing_suite_reports_failure(self):
        self._write_suite(
            """
            import unittest
            class T(unittest.TestCase):
                def test_bad(self): self.assertTrue(False)
            """
        )
        cfg = make_config(test_command="python -m unittest discover -s suite -t .")
        tool = RunTestsTool(ToolContext(project_root=self.root, config=cfg))
        r = tool.run()
        self.assertFalse(r.ok)
        self.assertNotEqual(r.meta["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
