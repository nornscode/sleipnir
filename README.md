# Sleipnir

A coding harness worker for [Norns](https://github.com/nornscode/norns).
It runs on your machine, in your repository, and gives a Norns agent six
tools: `read_file`, `write_file`, `edit_file`, `bash`, `grep`, `glob`.
The agent loop itself runs in Norns, so a session survives the laptop
sleeping, the terminal closing, or the worker restarting, and every step
is in the run log where it can be resumed, inspected, or forked. The
same command is the client you talk to it through.

Sleipnir is Odin's eight-legged horse: the fastest steed, and the one
that carries a rider between worlds.

## Install

```bash
uv tool install sleipnir        # or: uv sync, inside a clone
```

That installs `sleip`, and `sleipnir` as an alias.

## Run

From the repository you want the agent to work in:

```bash
export NORNS_URL=http://localhost:4000
export NORNS_API_KEY=nrn_...
export ANTHROPIC_API_KEY=sk-ant-...
sleip
```

Or keep those in the repository: `sleip` reads `--env-file`, then the
repository's `.envrc` through `direnv export` (if direnv is installed and
has allowed it), then its `.env`. A variable the shell already has is
never overridden.

That opens the session client with this repository's worker running in
the same process. Down the left: your spaces, one per checkout with a
worker in it (this one first), each showing how many sessions are
working or waiting on you. Across the top: the sessions of the selected
space, as tabs. Type to talk to the session you are in. When the agent
asks a question, your next line is the answer.

```
/new              start a new session in this space (ctrl+n)
/spaces           every space, with whether a worker is in it
/close            close the current tab (ctrl+w); the session lives on
/delete           delete the current session from Norns (asks once)
/fork N [message] fork the current session from step N into a new one
/resume           reload the current session and re-attach to its run
/help             the commands
/quit             leave; the worker stops with you, sessions live on in Norns
```

Sessions survive the client: close it, open it on another machine, and
the same history and state are there. Only the working tree is local,
so a session's tool calls always run on the machine whose worker
started it.

The pieces run alone too: `sleip serve` is the worker without a
client, for a machine you are not sitting at, and `sleip chat` is
the client without a worker.

Options: `--root` (repository root, default the current directory),
`--agent` (default `sleipnir`, the agent's name in Norns), `--model` (default `claude-sonnet-5`),
`--max-steps` (default 200), `--compact-at` (default 100000) and
`--keep` (default 40). Every option is also a `SLEIPNIR_<NAME>`
environment variable or a `.sleipnir/config` setting.

### Repository environment variables

Sleipnir automatically loads [direnv](https://direnv.net/)'s environment
from the selected repository (including `--root`) before starting the
client or worker. No shell hook is required. Install direnv, then create
an `.envrc` in your repository:

```bash
export NORNS_URL=http://localhost:4000
export NORNS_API_KEY=nrn_...
export ANTHROPIC_API_KEY=sk-ant-...
export DATABASE_URL=postgres://localhost/myapp
```

Run `direnv allow` in that repository, then `sleip`. To use a `.env`
file instead, put `dotenv` in `.envrc`; you can copy `.env.example` to
`.env` and fill it in. Keep files containing secrets out of git.

Direnv's exported values and unsets apply to the inherited environment;
command-line flags still override settings. `sleip doctor` and
`sleip config show` load the same environment. Restart Sleipnir after
changing variables, and re-run `direnv allow` if `.envrc` changes.
An unapproved or failing `.envrc` stops startup with an error.
Shell tools inherit project variables, with the worker's credential
variables still removed. Without direnv or an `.envrc`, the inherited
environment works as before.

### Spaces are gards

Each repository gets its own gard on first start, so runs started from
this checkout only ever reach the worker running in it, and every gard
is a space in the sidebar. Sessions no gard serves share a "no gard"
space. The gard's
claim token is kept in `~/.sleipnir/gards.json`, never in the
repository. `NORNS_GARD` and `NORNS_GARD_CLAIM_TOKEN` override it, and
`--no-gard` turns it off, in which case the worker serves any run that
has no gard.

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

`sleip` is also the configuration tool, and the agent can run it
through `bash`:

```bash
sleip allow list | add <tool> <pattern> | remove <tool> <pattern>
sleip config show | set <key> <value> | unset <key>   # agent, model, max_steps, compact_at, keep
sleip doctor      # connection, keys, gard, allow list
sleip docs        # the reference the agent reads
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
project, and points it at `sleip docs` for the harness itself.

## Limits

- One repository per worker. Paths that resolve outside the root,
  including through symlinks, are refused.
- `bash` output is truncated in the middle above 30k characters, and
  commands are killed after the timeout (default 120s, max 600s). The
  worker's own credentials are removed from the command's environment.
- Long sessions are compacted by Norns, not trimmed: once a response
  reports `compact_at` input tokens, everything but the last `keep`
  messages is folded into a summary that this worker writes and Norns
  carries forward. The summary and the fold are in the run log as a
  `context_compacted` event.
- `grep` is a Python walk, not ripgrep. It skips build directories and
  binary files and is fine for repositories of tens of thousands of files.

## Development

```bash
uv sync
uv run pytest -q
```
