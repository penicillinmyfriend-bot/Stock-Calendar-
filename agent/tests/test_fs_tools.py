"""Tests for the project-scoped filesystem tools."""

import tempfile
import unittest
from pathlib import Path

from agentcore.tools.base import ToolContext
from agentcore.tools.fs import ReadFileTool, WriteFileTool


class FsToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.ctx = ToolContext(project_root=self.root)
        self.read = ReadFileTool(self.ctx)
        self.write = WriteFileTool(self.ctx)
        self.addCleanup(self.tmp.cleanup)

    def test_write_then_read(self):
        r = self.write.run(path="notes/a.txt", content="hello")
        self.assertTrue(r.ok, r.error)
        self.assertTrue((self.root / "notes" / "a.txt").exists())
        rr = self.read.run(path="notes/a.txt")
        self.assertTrue(rr.ok, rr.error)
        self.assertEqual(rr.output, "hello")

    def test_append_mode(self):
        self.write.run(path="log.txt", content="a")
        self.write.run(path="log.txt", content="b", mode="append")
        self.assertEqual(self.read.run(path="log.txt").output, "ab")

    def test_overwrite_default(self):
        self.write.run(path="x.txt", content="first")
        self.write.run(path="x.txt", content="second")
        self.assertEqual(self.read.run(path="x.txt").output, "second")

    def test_read_missing_file_fails_gracefully(self):
        r = self.read.run(path="nope.txt")
        self.assertFalse(r.ok)
        self.assertIn("no such file", r.error)

    def test_invalid_mode_rejected(self):
        r = self.write.run(path="x.txt", content="y", mode="bogus")
        self.assertFalse(r.ok)

    def test_write_outside_project_blocked(self):
        r = self.write.run(path="../escape.txt", content="x")
        self.assertFalse(r.ok)
        self.assertIn("outside", r.error)
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_read_outside_project_blocked(self):
        r = self.read.run(path="/etc/passwd")
        self.assertFalse(r.ok)

    def test_max_bytes_truncates(self):
        self.write.run(path="big.txt", content="abcdefghij")
        r = self.read.run(path="big.txt", max_bytes=3)
        self.assertEqual(r.output, "abc")


if __name__ == "__main__":
    unittest.main()
