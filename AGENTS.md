# AGENTS.md

Sleipnir is a coding harness worker for Norns — see README.md for the pitch.
This file is for whoever (human or agent) is hacking on sleipnir's own
source, not the target repositories it runs in.

## Setup and tests

```
uv sync
uv run pytest -q
```

There is no linter or formatter configured (no ruff, black, or mypy
config in this repo) — don't invent one or assume a `make lint` exists.

## Layout

`sleipnir/` is the package:

- `cli.py` — the `sleip`/`sleipnir` entrypoint, argument parsing, subcommands.
- `app.py` — the Textual client (spaces, sessions, the `HELP` text).
- `worker.py` — the agent loop: tools, the LLM task, the run.
- `tools/` — the tool implementations (`files.py`, `edit.py`, `shell.py`,
  `search.py`, `git.py`) that back read_file/write_file/edit_file/bash/
  grep/glob/git.
- `permissions.py` — the allow-list and the ask_human approval loop.
- `docs.py` — the `DOCS` string, what `sleip docs` hands the agent as its
  reference to the client it's running in.
- `prompt.py` — `SYSTEM_PROMPT`, what the agent is told at the start of a
  run (including to read the *target* repo's own AGENTS.md — an unrelated
  concern from this file), and `TEAM_PROMPT`, appended when the team
  feature (below) is on. `section()` pulls a heading out of
  `SYSTEM_PROMPT` verbatim for reuse in a helper's own prompt, so the
  rules stay word for word instead of a copy that drifts.
- `config.py` — per-repository settings (`.sleipnir/config`).
- `gard.py` — the claim that ties a worker to its repository's runs.
- `workers.py` — every worker on this machine: the registry each one
  writes itself into, and the `sleip workers` list/stop/restart it backs.
- `daemon.py` — running a worker as a background process.

`tests/` mirrors `sleipnir/` roughly file-for-file (`test_x.py` for
`sleipnir/x.py`).

## Conventions

Read a few existing files before changing one; match what's there.
Broadly: dataclasses for structured state, type hints throughout,
minimal diffs (don't reformat or rename code the task didn't ask you to
touch), and docstrings/comments that justify a decision rather than
restate the code. If asked to describe a change, write the commit
message in the same terse, plain-declarative, reasoning-forward voice
the rest of the codebase uses — no fluff, no marketing tone.

## Keep three places in sync

This product's own interface is documented by hand in three places:

- `sleipnir/app.py`'s `HELP` string — what `/help` actually prints.
- `sleipnir/docs.py`'s `DOCS` string — what the agent reads via `sleip docs`.
- `README.md`'s command list, near the top.

Adding or changing a client command means updating all three. Several
past commits updated only the first two and left README.md stale — don't
repeat that.

## The team

The worker can hand work to two extra agents alongside the main one:
`sleipnir-explore` (read-only tools) and `sleipnir-code` (the one that
writes). `config.py`'s `team` setting turns this on or off;
`explore_model`/`code_model` pick their models. `worker.py`'s
`build_agents()` wires the three together with `allowed_tools`, and
`prompt.py`'s `TEAM_PROMPT` is what tells the main agent it has them.
README.md's "The team" section is the user-facing account of the same
thing — keep it in step with `worker.py` and `TEAM_PROMPT` if either
changes.

## Known issue

`uv run pytest -q` currently has 3 pre-existing failures in
`tests/test_worker.py`: `TypeError: Agent.__init__() got an unexpected
keyword argument 'allowed_tools'`. The installed norns-sdk doesn't yet
support the `allowed_tools` kwarg the team feature relies on. This is
pre-existing, not something to fix by ripping the feature out — flag it
if it blocks a task, don't paper over it silently.

## Permissions apply here too

If this checkout has `.sleipnir/allow`, it governs what bash/write_file/
edit_file can do here without asking — the same mechanism `permissions.py`
implements for the product. Obey it like any other agent would; it isn't
just a thing you're reading about.
