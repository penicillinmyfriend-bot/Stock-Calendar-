"""Safety primitives: filesystem confinement and command sandboxing.

This module is the security backstop for the whole agent. Two jobs:

1. **Path confinement** -- every file path the agent touches is resolved
   (following symlinks) and verified to live inside the configured project
   root. Anything that escapes is refused.

2. **Command sandboxing** -- before any shell command runs it is screened
   against a hard, code-enforced set of rules *plus* the user's configurable
   allow/deny lists. The hard rules cannot be turned off from config:

   * no ``rm -rf`` (or other destructive ops) outside the project,
   * no referencing system files/paths (``/etc``, ``/usr``, ``/bin`` ...),
   * no piping a download straight into a shell (``curl ... | sh``),
   * no package installs outside the project's own virtualenv,
   * no privilege escalation (``sudo``) or system package managers.

Everything here is pure and deterministic so it can be unit-tested without a
filesystem mutation or a real shell.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Iterable, Optional, Sequence


class SafetyError(Exception):
    """Raised when an operation would violate a safety guarantee."""


# Absolute path prefixes that are considered "system" and always off-limits.
SYSTEM_PATH_PREFIXES: tuple[str, ...] = (
    "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/boot",
    "/sys", "/proc", "/dev", "/var", "/root", "/opt", "/srv",
)

# Programs that perform a privileged or system-wide install / mutation.
_SYSTEM_PACKAGE_MANAGERS = {
    "sudo", "apt", "apt-get", "yum", "dnf", "pacman", "zypper",
    "brew", "snap", "apk", "systemctl", "service",
}

# Pattern: a downloader piped into a shell interpreter.
_DOWNLOAD_PIPE_SHELL = re.compile(
    r"\b(?:curl|wget|fetch|lynx)\b[^|]*\|\s*(?:sudo\s+)?\b(?:sh|bash|zsh|dash|ksh|fish|python\d?)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# Filesystem confinement
# --------------------------------------------------------------------------- #
def is_within(root: os.PathLike | str, target: os.PathLike | str) -> bool:
    """Return True if *target* is *root* itself or nested inside it.

    Both are resolved (symlinks followed) before comparison.
    """
    root_r = Path(os.path.realpath(root))
    target_r = Path(os.path.realpath(target))
    return target_r == root_r or root_r in target_r.parents


def resolve_in_project(project_root: os.PathLike | str, path: os.PathLike | str) -> Path:
    """Resolve *path* and guarantee it lives inside *project_root*.

    Relative paths are taken relative to ``project_root``. Symlinks are
    followed, so a symlink inside the project that points outside it is
    rejected. Returns the resolved absolute :class:`~pathlib.Path`.

    Raises :class:`SafetyError` if the path escapes the project.
    """
    root = Path(os.path.realpath(project_root))
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = root / p
    resolved = Path(os.path.realpath(p))
    if resolved == root or root in resolved.parents:
        return resolved
    raise SafetyError(
        f"path {str(path)!r} resolves to {resolved} which is outside the "
        f"project root {root}"
    )


# --------------------------------------------------------------------------- #
# Command sandboxing
# --------------------------------------------------------------------------- #
def _is_path_like(token: str) -> bool:
    """Heuristic: does this token look like a filesystem path (not a URL)?"""
    if token.startswith(("/", "~", "./", "../")) or token == "..":
        return True
    if "://" in token:  # URL, e.g. https://github.com/...
        return False
    return "/" in token


def _references_system_path(token: str) -> bool:
    expanded = os.path.expanduser(token)
    if not expanded.startswith("/"):
        return False
    norm = os.path.normpath(expanded)
    for prefix in SYSTEM_PATH_PREFIXES:
        if norm == prefix or norm.startswith(prefix + "/"):
            return True
    return False


def check_command(
    command: str,
    *,
    project_root: os.PathLike | str,
    allowlist: Sequence[str] = (),
    denylist: Iterable[str] = (),
    env: Optional[dict] = None,
) -> None:
    """Screen *command* against every safety rule.

    Returns ``None`` if the command is permitted; raises :class:`SafetyError`
    with a human-readable reason otherwise. This function never executes
    anything -- it only inspects the command string.
    """
    if env is None:
        env = dict(os.environ)
    raw = command.strip()
    if not raw:
        raise SafetyError("empty command")

    # 1) User-configured denylist (substring match) -- always wins.
    for needle in denylist:
        if needle and needle in raw:
            raise SafetyError(f"command matches denylist entry {needle!r}")

    # 2) Hard rule: never pipe a download into a shell.
    if _DOWNLOAD_PIPE_SHELL.search(raw):
        raise SafetyError("refusing to pipe a downloaded payload into a shell")

    # Tokenize. Unparseable quoting is treated as suspicious.
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:  # pragma: no cover - defensive
        raise SafetyError(f"could not parse command ({exc})")
    if not tokens:
        raise SafetyError("empty command")

    program = os.path.basename(tokens[0])

    # 3) Hard rule: no privilege escalation / system package managers.
    if program in _SYSTEM_PACKAGE_MANAGERS:
        raise SafetyError(f"{program!r} is a privileged/system command and is blocked")

    # 4) Hard rule: no installs outside the project's own virtualenv.
    _check_installs(tokens, program, env=env)

    # 5) Hard rule: destructive op (rm/dd/mkfs/...) and any path argument must
    #    not reference system paths or escape the project.
    for tok in tokens[1:]:
        if not _is_path_like(tok):
            continue
        if _references_system_path(tok):
            raise SafetyError(f"command references system path {tok!r}")
        # Resolve relative/absolute project paths and ensure they stay inside.
        try:
            resolve_in_project(project_root, tok)
        except SafetyError:
            raise SafetyError(f"command path argument {tok!r} escapes the project")

    # 6) Configurable allowlist: if set, the program must be on it.
    allow = [a for a in allowlist if a]
    if allow and program not in allow:
        raise SafetyError(
            f"program {program!r} is not in the allowed-commands list"
        )


def _check_installs(tokens: Sequence[str], program: str, *, env: dict) -> None:
    """Block package installs that would escape the project's virtualenv."""
    args = set(tokens[1:])

    # npm/yarn/pnpm global installs.
    if program in {"npm", "yarn", "pnpm"}:
        wants_install = bool({"install", "i", "add"} & args)
        is_global = bool({"-g", "--global"} & args)
        if wants_install and is_global:
            raise SafetyError("global npm/yarn install is blocked")

    # pip installs: only allowed inside an active venv or targeting the project.
    is_pip = program in {"pip", "pip3"} or (
        program in {"python", "python3"} and "pip" in tokens
    )
    if is_pip and "install" in tokens:
        if "--user" in args:
            raise SafetyError("'pip install --user' is blocked (escapes the venv)")
        in_venv = bool(env.get("VIRTUAL_ENV"))
        targets_project = bool({"--target", "-t", "--prefix"} & args)
        if not in_venv and not targets_project:
            raise SafetyError(
                "pip install is only allowed inside the project's own virtualenv "
                "(activate ./.venv or pass --target)"
            )
