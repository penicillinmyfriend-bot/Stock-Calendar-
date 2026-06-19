"""Command-line interface.

Commands:

* ``agent run --minutes N`` / ``--iterations N`` -- run one approved session.
* ``agent status``  -- show config, branch, last session, and rollback point.
* ``agent log``     -- print the journal (optionally the last N sessions).
* ``agent rollback``-- reset the repo to a known-good commit in one step.

``run`` requires explicit approval (an interactive ``y`` or ``--yes``) because
it autonomously modifies the repository.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .budget import Budget
from .config import Config
from .llm import OllamaClient
from .orchestrator import DEFAULT_BRANCH, Orchestrator
from .persistence import Persistence
from .tools.git_tools import Git


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _persistence(cfg: Config) -> Persistence:
    config_dir = Path(cfg.config_path).parent
    return Persistence(
        roadmap_path=config_dir / "ROADMAP.md",
        journal_path=config_dir / "JOURNAL.md",
        state_dir=cfg.state_dir,
    )


def _approve(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Refusing to proceed without approval. Re-run with --yes.", file=sys.stderr)
        return False
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _load_config(args) -> Config:
    return Config.load(getattr(args, "config", None))


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_run(args) -> int:
    cfg = _load_config(args)
    budget = Budget.from_config(cfg, minutes=args.minutes, iterations=args.iterations)

    print("About to start an autonomous session:")
    print(f"  branch:       {args.branch}")
    print(f"  project root: {cfg.project_root}")
    print(f"  model:        {cfg.model.name} @ {cfg.model.host}")
    print(f"  web access:   {'ON' if cfg.web.enabled else 'off'}")
    print(f"  budget:       {budget}")
    print("The agent will make git-tracked, test-gated changes on the branch above.")

    if not _approve("Approve this session?", args.yes):
        print("Aborted: session not approved.")
        return 1

    llm = OllamaClient(
        host=cfg.model.host,
        model=cfg.model.name,
        temperature=cfg.model.temperature,
        timeout=cfg.model.request_timeout,
    )
    if not args.skip_model_check and not llm.is_available():
        print(
            f"Cannot reach Ollama at {cfg.model.host}.\n"
            f"Start it with `ollama serve` and pull the model: "
            f"`ollama pull {cfg.model.name}`.",
            file=sys.stderr,
        )
        return 2

    orch = Orchestrator(cfg, llm, branch=args.branch, logger=_log_line)
    result = orch.run(budget)

    print("\n=== Session summary ===")
    print(result.summary.strip())
    return 0


def _log_line(message: str) -> None:
    print(f"[agent] {message}")


def cmd_status(args) -> int:
    cfg = _load_config(args)
    git = Git(cfg.project_root)
    persistence = _persistence(cfg)
    state = persistence.load_state()

    print(cfg.summary())
    print("-" * 40)
    if git.is_repo():
        print(f"current branch: {git.current_branch()}")
        print(f"HEAD:           {git.head_hash()[:8]}")
    else:
        print("current branch: (not a git repository)")
    print(f"rollback point: {(state.session_start_commit or '(none)')[:8]}")
    print(f"last good:      {(state.last_good_commit or '(none)')[:8]}")
    if state.last_session:
        s = state.last_session
        print(
            f"last session:   {s.get('timestamp', '?')} — {s.get('stop_reason', '?')} "
            f"({len(s.get('commits', []))} commit(s))"
        )
    else:
        print("last session:   (none yet)")
    return 0


def cmd_log(args) -> int:
    cfg = _load_config(args)
    persistence = _persistence(cfg)
    text = persistence.read_journal()
    if not text.strip():
        print("(journal is empty)")
        return 0
    if args.n:
        from .persistence import JOURNAL_SEPARATOR
        entries = [e for e in text.split(JOURNAL_SEPARATOR) if e.strip()]
        text = JOURNAL_SEPARATOR.join(entries[-args.n :])
    print(text.strip())
    return 0


def cmd_rollback(args) -> int:
    cfg = _load_config(args)
    git = Git(cfg.project_root)
    persistence = _persistence(cfg)
    state = persistence.load_state()

    if not git.is_repo():
        print("Not a git repository; nothing to roll back.", file=sys.stderr)
        return 2

    if args.to:
        target: Optional[str] = args.to
        label = f"commit {args.to}"
    elif args.last_good:
        target = state.last_good_commit
        label = "last good commit"
    else:
        target = state.session_start_commit
        label = "pre-session snapshot (undo the last session)"

    if not target:
        print(f"No {label} recorded yet; nothing to roll back to.", file=sys.stderr)
        return 1

    print(f"Rollback target: {label} -> {target[:8]}")
    print(f"This will `git reset --hard` on branch {git.current_branch()} and discard "
          "uncommitted changes.")
    if not _approve("Proceed with rollback?", args.yes):
        print("Aborted: rollback not approved.")
        return 1

    try:
        git.reset_hard(target)
    except Exception as exc:
        print(f"Rollback failed: {exc}", file=sys.stderr)
        return 2
    print(f"Rolled back to {git.head_hash()[:8]}.")
    return 0


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"agent {__version__}")
    parser.add_argument("--config", help="Path to config.yaml (defaults to the bundled one).")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Run one approved, budgeted session.")
    p_run.add_argument("--minutes", type=float, help="Wall-clock budget for this run.")
    p_run.add_argument("--iterations", type=int, help="Iteration budget for this run.")
    p_run.add_argument("--branch", default=DEFAULT_BRANCH, help="Work branch to commit on.")
    p_run.add_argument("--yes", action="store_true", help="Approve the session non-interactively.")
    p_run.add_argument("--skip-model-check", action="store_true",
                       help="Don't probe Ollama before starting.")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="Show config, branch, and last session.")
    p_status.set_defaults(func=cmd_status)

    p_log = sub.add_parser("log", help="Print the session journal.")
    p_log.add_argument("-n", type=int, default=0, help="Show only the last N sessions.")
    p_log.set_defaults(func=cmd_log)

    p_rb = sub.add_parser("rollback", help="Reset the repo to a known-good commit.")
    p_rb.add_argument("--to", help="Reset to a specific commit/ref.")
    p_rb.add_argument("--last-good", action="store_true",
                      help="Reset to the last commit that passed tests.")
    p_rb.add_argument("--yes", action="store_true", help="Approve the rollback non-interactively.")
    p_rb.set_defaults(func=cmd_rollback)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - top-level guard
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
