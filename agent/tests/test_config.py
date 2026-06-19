"""Tests for config loading, the minimal YAML fallback, and validation."""

import tempfile
import unittest
from pathlib import Path

from agentcore import config as configmod
from agentcore.config import Config, minimal_yaml_load

SAMPLE = """\
model:
  name: qwen2.5-coder
  host: http://127.0.0.1:11434
  temperature: 0.2
session:
  default_minutes: 10
  default_iterations: 25
paths:
  project_root: "."
  state_dir: ".agent"
web:
  enabled: false
  allowed_hosts: []
commands:
  allowlist:
    - python
    - git
  denylist:
    - "rm -rf /"
    - ":(){"
  timeout: 60
tests:
  command: "python -m unittest"
"""


class MinimalYamlTests(unittest.TestCase):
    def test_parses_nested_maps_and_lists(self):
        data = minimal_yaml_load(SAMPLE)
        self.assertEqual(data["model"]["name"], "qwen2.5-coder")
        self.assertEqual(data["session"]["default_iterations"], 25)
        self.assertEqual(data["commands"]["allowlist"], ["python", "git"])
        self.assertEqual(data["web"]["allowed_hosts"], [])
        self.assertFalse(data["web"]["enabled"])

    def test_strips_inline_comments(self):
        data = minimal_yaml_load("name: value   # a comment\n")
        self.assertEqual(data["name"], "value")

    def test_preserves_hash_inside_quotes(self):
        data = minimal_yaml_load('k: "a#b"\n')
        self.assertEqual(data["k"], "a#b")

    def test_scalar_types(self):
        data = minimal_yaml_load("i: 5\nf: 1.5\nb: true\nn: null\n")
        self.assertEqual(data["i"], 5)
        self.assertEqual(data["f"], 1.5)
        self.assertIs(data["b"], True)
        self.assertIsNone(data["n"])

    @unittest.skipUnless(
        __import__("importlib").util.find_spec("yaml"), "PyYAML not installed"
    )
    def test_matches_pyyaml(self):
        import yaml
        self.assertEqual(minimal_yaml_load(SAMPLE), yaml.safe_load(SAMPLE))


class ConfigLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.cfg_path = self.root / "config.yaml"
        self.cfg_path.write_text(SAMPLE)
        self.addCleanup(self.tmp.cleanup)

    def test_load_and_resolve_paths(self):
        cfg = Config.load(self.cfg_path)
        self.assertEqual(cfg.model.name, "qwen2.5-coder")
        self.assertEqual(cfg.project_root, self.root)
        self.assertEqual(cfg.state_dir, self.root / ".agent")
        self.assertEqual(cfg.commands.allowlist, ["python", "git"])
        self.assertEqual(cfg.session.default_minutes, 10)

    def test_minimal_loader_path(self):
        # Force the fallback parser even if PyYAML is installed.
        orig = configmod.load_yaml
        configmod.load_yaml = lambda text: minimal_yaml_load(text)
        try:
            cfg = Config.load(self.cfg_path)
            self.assertEqual(cfg.model.host, "http://127.0.0.1:11434")
        finally:
            configmod.load_yaml = orig

    def test_state_dir_outside_root_rejected(self):
        bad = self.root / "bad.yaml"
        bad.write_text('paths:\n  project_root: "."\n  state_dir: "../outside"\n')
        with self.assertRaises(ValueError):
            Config.load(bad)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            Config.load(self.root / "nope.yaml")

    def test_defaults_when_keys_missing(self):
        bare = self.root / "bare.yaml"
        bare.write_text('paths:\n  project_root: "."\n')
        cfg = Config.load(bare)
        self.assertEqual(cfg.model.name, "qwen2.5-coder")
        self.assertFalse(cfg.web.enabled)


if __name__ == "__main__":
    unittest.main()
