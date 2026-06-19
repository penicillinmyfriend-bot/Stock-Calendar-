# Self-Improving Agent

A small, local, **self-improving** AI agent. It loads a goal and a persistent
roadmap, plans, acts through a set of sandboxed tools, tests every change, and
commits it (or reverts it) — improving its own code, tools, prompts, and config
over repeated sessions.

It is deliberately boring about safety:

- **All inference is local.** The running agent talks only to a local
  [Ollama](https://ollama.com) server (default model `qwen2.5-coder`). It makes
  **no cloud LLM calls**.
- **It stays in its sandbox.** Every file read/write is confined to the
  configured project root; `..`, absolute paths, and symlinks that escape are
  refused.
- **Every change is git-tracked and reversible.** Each change is made on a
  branch, tested, and committed only if the tests pass — otherwise it is
  reverted. `agent rollback` undoes a whole session in one step.
- **You set the budget.** A run stops at the minutes/iterations you approve and
  the agent has no way to extend its own budget.

This project lives in `agent/`, but its **sandbox is the whole repository**
(`project_root: ".."` in `config.yaml`), so it can also work on the rest of the
repo — change `project_root` to `"."` to confine it to this folder only.

---

## Requirements

- **Python 3.10+** and **git** (already required by the repo).
- **[Ollama](https://ollama.com)** running locally, with a model pulled.
- **No Python packages are required.** The agent uses only the standard library
  and talks to Ollama over HTTP. PyYAML is used *if present* but there is a
  built-in YAML fallback, so nothing needs installing.

Optional, project-local only (never system-wide):

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[yaml,dev]"   # PyYAML + pytest, if you want them
```

## Setup & one-command run

```bash
# 1) Start the local model server and pull the model (one time).
ollama serve &
ollama pull qwen2.5-coder

# 2) From the agent/ directory, run one approved, budgeted session:
python -m agentcore run --minutes 10
```

If you installed the package (`pip install -e .`), the console script works too:

```bash
agent run --minutes 10
```

## Approving a session

`run` never starts silently — it prints the plan (branch, project root, model,
web on/off, and budget) and waits for your approval:

```
About to start an autonomous session:
  branch:       agent/work
  project root: /path/to/repo
  model:        qwen2.5-coder @ http://127.0.0.1:11434
  web access:   off
  budget:       budget(0/600s, 0/25 iters)
The agent will make git-tracked, test-gated changes on the branch above.
Approve this session? [y/N]
```

- Type `y` to approve.
- For non-interactive use (cron, CI), pass `--yes`.
- Set the budget with `--minutes N` **or** `--iterations N` (or rely on the
  config defaults if you pass neither). Whichever limit is hit first ends the
  run — this is a **hard stop**; the agent cannot extend it.

The agent works on the `agent/work` branch (override with `--branch`), makes
small test-gated commits, then writes a session summary to `JOURNAL.md` and
exits.

## Checking progress

```bash
agent status   # config, current branch, rollback point, last good commit, last session
agent log      # the full journal
agent log -n 3 # just the last 3 sessions
```

Two files carry progress across runs:

- **`ROADMAP.md`** — the goal and plan. Edit it to steer the agent.
- **`JOURNAL.md`** — one summary per session (what changed, commits, why it stopped).

## Rolling back

Every session records the commit HEAD was at when it started (the *rollback
point*) and every commit that passed tests (the *last good* commit).

```bash
agent rollback              # undo the entire last session (back to its start)
agent rollback --last-good  # reset to the last commit that passed tests
agent rollback --to <ref>   # reset to a specific commit
```

Rollback runs `git reset --hard` on the current branch (after you approve, or
with `--yes`). Because each in-loop change is already committed-or-reverted, the
common case is "undo the last run in one step", which is the default.

## Configuration (`config.yaml`)

| Key | Meaning |
| --- | --- |
| `model.name` / `model.host` | Local Ollama model and server URL. |
| `session.default_minutes` / `default_iterations` | Budget when none is given on the CLI. |
| `paths.project_root` | The sandbox boundary (`".."` = repo root). |
| `paths.state_dir` | Where run state lives (kept inside the project, git-ignored). |
| `web.enabled` | Web access **off by default**; the agent has no other network egress. |
| `web.allowed_hosts` | Optional host allowlist for the web tool when enabled. |
| `commands.allowlist` / `denylist` | Command sandbox policy (on top of hard-coded rules). |
| `commands.timeout` | Per-command timeout. |
| `tests.command` | The command that decides keep-vs-revert (must exit 0 to keep). |

## Guardrails (enforced in code, see `agentcore/safety.py`)

- Filesystem writes are confined to `project_root` (symlink-aware).
- The command sandbox refuses, regardless of config: `rm -rf` (or any path op)
  outside the project, references to system paths (`/etc`, `/usr`, …), piping a
  download into a shell, `sudo`/system package managers, and any install outside
  the project's own virtualenv. Commands run with **no shell** (no pipes,
  redirects, or `&&`).
- No network egress except the optional web tool, and only when
  `web.enabled: true`.
- The session budget is a hard stop; limits are read-only and cannot be raised
  by the running agent.

## Tools available to the agent

`read_file`, `write_file` (project-scoped), `run_command` (sandboxed),
`run_tests`, `git_status`, `git_diff`, and — only when enabled — `web_search` /
`web_fetch`. Committing, branching, and reverting are driven by the harness
around the test gate, so a change can never be committed without passing tests.

## How self-improvement works

The agent's tools let it edit any file in the sandbox — including its own
`agentcore/` source, its prompts, its tools, and `config.yaml`. Each edit goes
through the same loop: **make the change → run the tests → commit if green,
revert if red.** Over sessions it can refactor itself, add new tools, sharpen
its prompts, and tune its config, while `ROADMAP.md` / `JOURNAL.md` keep the
thread of what it is working toward.

## Running the tests

No dependencies needed:

```bash
# from the agent/ directory
python -m unittest discover -s tests -t .

# or, from the repo root (this is the configured test command):
python -m unittest discover -s agent/tests -t agent

# or with pytest, if installed:
pytest
```

## Project layout

```
agent/
├── config.yaml            # model, budget, web on/off, sandbox paths, commands
├── ROADMAP.md             # persistent goal + plan
├── JOURNAL.md             # per-session log
├── agentcore/
│   ├── cli.py             # run / status / log / rollback
│   ├── config.py          # YAML load + validation (+ minimal YAML fallback)
│   ├── llm.py             # local Ollama HTTP client (stdlib only)
│   ├── budget.py          # minutes/iterations budget + hard stop
│   ├── safety.py          # path confinement + command sandbox
│   ├── persistence.py     # ROADMAP / JOURNAL / run state
│   ├── orchestrator.py    # the plan→act→test→commit/revert loop
│   └── tools/             # fs, shell, git, web tools + registry
└── tests/                 # unit + end-to-end tests (stdlib unittest)
```
