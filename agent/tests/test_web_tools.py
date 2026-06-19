"""Tests that the web tools are OFF by default and properly gated.

These never touch the network: when web access is disabled (the default) the
tools must refuse before making any request.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agentcore.tools import build_registry
from agentcore.tools.base import ToolContext
from agentcore.tools.web import WebFetchTool, WebSearchTool


def web_config(enabled=False, allowed_hosts=None):
    return SimpleNamespace(
        web=SimpleNamespace(
            enabled=enabled,
            allowed_hosts=allowed_hosts or [],
            fetch_timeout=5,
            max_bytes=1000,
        )
    )


class WebGatingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)

    def test_disabled_by_default_fetch(self):
        ctx = ToolContext(project_root=self.root, config=web_config(enabled=False))
        r = WebFetchTool(ctx).run(url="https://example.com")
        self.assertFalse(r.ok)
        self.assertIn("disabled", r.error)

    def test_disabled_by_default_search(self):
        ctx = ToolContext(project_root=self.root, config=web_config(enabled=False))
        r = WebSearchTool(ctx).run(query="anything")
        self.assertFalse(r.ok)
        self.assertIn("disabled", r.error)

    def test_non_http_scheme_rejected_when_enabled(self):
        ctx = ToolContext(project_root=self.root, config=web_config(enabled=True))
        r = WebFetchTool(ctx).run(url="file:///etc/passwd")
        self.assertFalse(r.ok)
        self.assertIn("scheme", r.error)

    def test_host_allowlist_enforced(self):
        cfg = web_config(enabled=True, allowed_hosts=["example.com"])
        ctx = ToolContext(project_root=self.root, config=cfg)
        r = WebFetchTool(ctx).run(url="https://evil.test/x")
        self.assertFalse(r.ok)
        self.assertIn("allowed_hosts", r.error)

    def test_registry_excludes_web_when_disabled(self):
        ctx = ToolContext(project_root=self.root, config=web_config(enabled=False))
        reg = build_registry(ctx)
        self.assertNotIn("web_fetch", reg.names())
        self.assertNotIn("web_search", reg.names())

    def test_registry_includes_web_when_enabled(self):
        ctx = ToolContext(project_root=self.root, config=web_config(enabled=True))
        reg = build_registry(ctx)
        self.assertIn("web_fetch", reg.names())
        self.assertIn("web_search", reg.names())


if __name__ == "__main__":
    unittest.main()
