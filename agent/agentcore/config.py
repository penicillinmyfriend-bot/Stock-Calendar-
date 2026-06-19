"""Configuration loading and validation.

The agent is configured by a single ``config.yaml``. PyYAML is used when it is
installed; otherwise a small built-in parser (:func:`minimal_yaml_load`) handles
the subset of YAML this project uses, so the project has **no required
third-party dependency**.

All paths in the config are resolved relative to the config file's own
directory, and ``project_root`` becomes the agent's sandbox boundary.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# Minimal YAML fallback (used only when PyYAML is unavailable)
# --------------------------------------------------------------------------- #
def _strip_comment(line: str) -> str:
    out, in_single, in_double = [], False, False
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(token: str) -> Any:
    t = token.strip()
    if t == "" or t in ("~", "null", "None"):
        return None
    if t in ("true", "True"):
        return True
    if t in ("false", "False"):
        return False
    if (t[0] == t[-1]) and t[0] in ("'", '"') and len(t) >= 2:
        return t[1:-1]
    if t == "[]":
        return []
    if t == "{}":
        return {}
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def minimal_yaml_load(text: str) -> Any:
    """Parse the indentation-based YAML subset this project uses."""
    lines = []
    for raw in text.splitlines():
        stripped = _strip_comment(raw)
        if stripped.strip() == "":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))

    pos = 0

    def parse_block(min_indent: int) -> Any:
        nonlocal pos
        container: Any = None
        while pos < len(lines):
            indent, content = lines[pos]
            if indent < min_indent:
                break
            if content.startswith("- ") or content == "-":
                if container is None:
                    container = []
                value = content[2:].strip() if content.startswith("- ") else ""
                pos += 1
                if value == "":
                    child_indent = lines[pos][0] if pos < len(lines) else min_indent + 1
                    container.append(parse_block(child_indent))
                else:
                    container.append(_scalar(value))
            else:
                if container is None:
                    container = {}
                key, _, val = content.partition(":")
                key, val = key.strip(), val.strip()
                pos += 1
                if val == "":
                    if pos < len(lines) and lines[pos][0] > indent:
                        container[key] = parse_block(lines[pos][0])
                    else:
                        container[key] = None
                else:
                    container[key] = _scalar(val)
        return container if container is not None else {}

    return parse_block(lines[0][0]) if lines else {}


def load_yaml(text: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
    except ImportError:
        data = minimal_yaml_load(text)
    return data or {}


# --------------------------------------------------------------------------- #
# Typed config
# --------------------------------------------------------------------------- #
@dataclass
class ModelConfig:
    name: str = "qwen2.5-coder"
    host: str = "http://127.0.0.1:11434"
    temperature: float = 0.2
    request_timeout: int = 120


@dataclass
class SessionConfig:
    default_minutes: float = 10
    default_iterations: int = 25


@dataclass
class WebConfig:
    enabled: bool = False
    allowed_hosts: List[str] = field(default_factory=list)
    fetch_timeout: int = 20
    max_bytes: int = 1_000_000


@dataclass
class CommandsConfig:
    allowlist: List[str] = field(default_factory=list)
    denylist: List[str] = field(default_factory=list)
    timeout: int = 120


@dataclass
class TestsConfig:
    command: str = "python -m unittest discover -s agent/tests -t agent"


@dataclass
class Config:
    model: ModelConfig
    session: SessionConfig
    web: WebConfig
    commands: CommandsConfig
    tests: TestsConfig
    project_root: Path
    state_dir: Path
    config_path: Path
    raw: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    @staticmethod
    def default_path() -> Path:
        """``agent/config.yaml`` next to the installed package."""
        return Path(__file__).resolve().parent.parent / "config.yaml"

    @classmethod
    def load(cls, path: Optional[os.PathLike | str] = None) -> "Config":
        config_path = Path(path or os.environ.get("AGENT_CONFIG") or cls.default_path()).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"config not found: {config_path}")
        data = load_yaml(config_path.read_text(encoding="utf-8"))
        return cls.from_dict(data, config_path)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], config_path: Path) -> "Config":
        config_path = Path(config_path).resolve()
        config_dir = config_path.parent

        m = data.get("model", {}) or {}
        s = data.get("session", {}) or {}
        w = data.get("web", {}) or {}
        c = data.get("commands", {}) or {}
        t = data.get("tests", {}) or {}
        p = data.get("paths", {}) or {}

        project_root = (config_dir / str(p.get("project_root", ".."))).resolve()
        state_dir = (project_root / str(p.get("state_dir", "agent/.agent"))).resolve()

        config = cls(
            model=ModelConfig(
                name=str(m.get("name", "qwen2.5-coder")),
                host=str(m.get("host", "http://127.0.0.1:11434")),
                temperature=float(m.get("temperature", 0.2)),
                request_timeout=int(m.get("request_timeout", 120)),
            ),
            session=SessionConfig(
                default_minutes=float(s.get("default_minutes", 10)),
                default_iterations=int(s.get("default_iterations", 25)),
            ),
            web=WebConfig(
                enabled=bool(w.get("enabled", False)),
                allowed_hosts=list(w.get("allowed_hosts", []) or []),
                fetch_timeout=int(w.get("fetch_timeout", 20)),
                max_bytes=int(w.get("max_bytes", 1_000_000)),
            ),
            commands=CommandsConfig(
                allowlist=list(c.get("allowlist", []) or []),
                denylist=list(c.get("denylist", []) or []),
                timeout=int(c.get("timeout", 120)),
            ),
            tests=TestsConfig(
                command=str(t.get("command") or TestsConfig.command),
            ),
            project_root=project_root,
            state_dir=state_dir,
            config_path=config_path,
            raw=data,
        )
        config.validate()
        return config

    def validate(self) -> None:
        from .safety import is_within  # local import to avoid a cycle

        if not self.project_root.exists():
            raise ValueError(f"project_root does not exist: {self.project_root}")
        if not self.project_root.is_dir():
            raise ValueError(f"project_root is not a directory: {self.project_root}")
        if not is_within(self.project_root, self.state_dir):
            raise ValueError(
                f"state_dir {self.state_dir} must be inside project_root {self.project_root}"
            )
        if not self.model.name:
            raise ValueError("model.name must be set")

    def summary(self) -> str:
        return (
            f"model:        {self.model.name} @ {self.model.host}\n"
            f"project_root: {self.project_root}\n"
            f"state_dir:    {self.state_dir}\n"
            f"web access:   {'ON' if self.web.enabled else 'off'}\n"
            f"defaults:     {self.session.default_minutes} min / "
            f"{self.session.default_iterations} iterations\n"
            f"test command: {self.tests.command}"
        )
