# Sleipnir

A coding harness worker for [Norns](https://github.com/nornscode/norns).
It runs on your machine, in your repository, and gives a Norns agent six
tools: `read_file`, `write_file`, `edit_file`, `bash`, `grep`, `glob`.
The agent loop itself runs in Norns, so a session survives the laptop
sleeping, the terminal closing, or the worker restarting, and every step
is in the run log where it can be resumed, inspected, or forked.

Sleipnir is Odin's eight-legged horse: the fastest steed, and the one
that carries a rider between worlds.

## Install

```bash
uv tool install sleipnir        # or: uv sync, inside a clone
```

## Run

From the repository you want the agent to work in:

```bash
export NORNS_URL=http://localhost:4000
export NORNS_API_KEY=nrn_...
export ANTHROPIC_API_KEY=sk-ant-...
sleipnir
```

The worker registers an agent named `sleipnir` (change it with
`--agent`), connects, and serves both the LLM calls and the tools for
its runs. Talk to it with `nornsctl`:

```bash
nornsctl agents send sleipnir "Add a --json flag to the list command"
```

Options: `--root` (repository root, default the current directory),
`--model` (default `claude-sonnet-5`), `--max-steps` (default 200).
Environment: `SLEIPNIR_AGENT`, `SLEIPNIR_MODEL`, `SLEIPNIR_MAX_STEPS`.

### Pin it to a gard

With one worker per repository, pin the worker to a gard so tool calls
for its runs only ever reach this machine:

```bash
nornsctl gards create --name laptop     # prints the gard id and a claim token
export NORNS_GARD=<id> NORNS_GARD_CLAIM_TOKEN=<token>
sleipnir
```

Without a gard the worker serves any run that has no gard, which is fine
when it is the only worker connected.

## Permissions

Reading is free. `bash`, `write_file`, and `edit_file` check an allow
list at `.sleipnir/allow` in the repository, one rule per line:

```
# tool  pattern (fnmatch on the command, or the path)
bash git *
bash uv run pytest*
bash mix *
edit_file *
write_file docs/*
```

A shell command is split into its simple commands (`a && b`, pipes,
subshells) and every one must match a rule. A command containing a
backtick always asks.

Outside the list, the tool returns a permission request with a token.
The agent asks you with `ask_human`, quoting the token and the exact
action, which reaches the dashboard, `nornsctl`, and any chat connector.
Answer:

- `yes` to allow it once,
- `always` to allow it and add a rule (`bash rm *` for a command, `edit_file *` for a file tool),
- anything else to refuse.

The worker reads your answer from the run's own messages, not from the
model, so the model cannot approve on your behalf. `.sleipnir/` is
per-repository; add it to `.gitignore` or commit it to share a team's
rules.

## Configuring it, from inside it

`sleipnir` is also the configuration tool, and the agent can run it
through `bash`:

```bash
sleipnir allow list | add <tool> <pattern> | remove <tool> <pattern>
sleipnir config show | set <key> <value> | unset <key>   # agent, model, max_steps
sleipnir doctor      # connection, keys, gard, allow list
sleipnir docs        # the reference the agent reads
```

Settings live in `.sleipnir/config` and take effect when the worker
restarts. A flag (`sleipnir --model ...`) or `SLEIPNIR_<KEY>` in the
environment overrides the file. Changes to the allow list or to
`.sleipnir/` always ask for permission, whatever the list says, so the
agent cannot grant itself permissions with one "always". The worker
picks up edits to the allow file as they happen.

## Prompts

The system prompt tells the agent to read `AGENTS.md` (or `CLAUDE.md`)
at the root before starting, so project conventions live with the
project, and points it at `sleipnir docs` for the harness itself.

## Limits

- One repository per worker. Paths that resolve outside the root,
  including through symlinks, are refused.
- `bash` output is truncated in the middle above 30k characters, and
  commands are killed after the timeout (default 120s, max 600s). The
  worker's own credentials are removed from the command's environment.
- The Norns SDK trims tool results older than the last two messages
  to 200 characters. That keeps long sessions under the context window
  until compaction lands in Norns; the agent re-reads a file when it
  needs it again.
- `grep` is a Python walk, not ripgrep. It skips build directories and
  binary files and is fine for repositories of tens of thousands of files.

## Development

```bash
uv sync
uv run pytest -q
```
