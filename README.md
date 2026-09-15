# Sleipnir

A coding harness worker for [Norns](https://github.com/nornscode/norns).
It runs on your machine, in your repository, and gives a Norns agent six
tools: `read_file`, `write_file`, `edit_file`, `bash`, `grep`, `glob`, and
`git` for reading history.
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
sleip
```

The first time, it asks for the two keys it needs — your Norns API key,
and an LLM key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) which this
worker uses to make the model calls on your machine. It checks them
against Norns as you go, then keeps them in `~/.sleipnir/env`,
owner-readable and outside every repository, so you answer once and
every space works. `sleip setup` runs the same questions again,
`--force` re-asks for keys already set, and `sleip doctor` checks them.

A repository's own environment still wins, so a checkout can point at a
different Norns:

```bash
export NORNS_URL=http://localhost:4000
export NORNS_API_KEY=nrn_...
export ANTHROPIC_API_KEY=sk-ant-...
sleip
```

Or keep those in the repository: `sleip` reads `--env-file`, then the
repository's `.envrc` through `direnv export` (if direnv is installed and
has allowed it), then its `.env`, then `~/.sleipnir/env`. A variable the
shell already has is never overridden, and the machine-wide file comes
last so a checkout can always override it.

That opens the session client with this repository's worker running in
the same process. Down the left: your spaces, one per checkout with a
worker in it (this one first), each showing how many sessions are
working or waiting on you. Across the top: the sessions of the selected
space, as tabs. Type to talk to the session you are in. When the agent
asks a question, your next line is the answer.

```
/new              start a new session in this space (ctrl+n)
/fork N [message] fork the current session from step N into a new one
/spaces           every space, with whether a worker is in it
/resume           reload the current session and re-attach to its run
/close            hide this session from the tree (ctrl+w); it comes back
/auto [edits|all|off] stop being asked about every command. edits lets
                  file changes through, all lets commands through too;
                  changing the harness itself always asks
/image <path> [text] hand the agent a picture — a screenshot from
                  anywhere on this machine, not just the repository
/rename <name>    name this session; empty puts the guessed name back
/archive          put this session away: the tab goes and stays gone,
                  but nothing is deleted
/archived         the sessions you have put away
/restore N        take one back out of the archive and open it
/delete           delete the current session from Norns (asks once)
/start            start a worker for this space, if its checkout is here
                  (sending into a space with no worker does this too)
/close-space      close this space everywhere (ctrl+g): destroys its
                  gard and stops its worker on every machine
                  (`force` if busy)
/help             this text
/quit             stop looking (ctrl+q). The worker keeps this space
                  open; `sleip stop` closes it in this checkout
```

Sessions survive the client: close it, open it on another machine, and
the same history and state are there. Only the working tree is local,
so a session's tool calls always run on the machine whose worker
started it.

The pieces run alone too: `sleip serve` is the worker without a
client, for a machine you are not sitting at, and `sleip chat` is
the client without a worker.

Workers outlive the window, so a machine collects them — one per
checkout you have opened. `sleip workers` lists every one on this
machine, whichever way it was started:

```
3 workers on this machine
  PID    CHECKOUT               NORNS                  UP      STATE
  50861  ~/projects/missive     http://localhost:4001  2d 3h   connected · older code
  83465  ~/projects/org-mobile  http://localhost:4001  5m      connected
  17689  ~/projects/norns       http://localhost:4001  1h 12m  not connected · older code
```

"older code" means it started before Sleipnir or the SDK last changed.
Stop or restart them by pid, checkout name, or path, or all at once:

```bash
sleip workers restart --stale     # everything running older code
sleip workers stop missive
sleip workers restart --all
```

A restart starts the same worker in its own checkout, with the flags it
was started with and that checkout's environment, and waits for one that
is still draining rather than starting a second beside it. `sleip stop`
still stops this checkout's worker.

Options: `--root` (repository root, default the current directory),
`--agent` (default `sleipnir`, the agent's name in Norns), `--model` (default `claude-sonnet-5`),
`--max-steps` (default 200), `--compact-at` (default 100000),
`--keep` (default 40) and `--max-tokens` (default 32000, the ceiling on
one response — a turn that reaches it comes back cut off and says so). Every option is also a `SLEIPNIR_<NAME>`
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
repository. `/close-space`, or ctrl+g, closes one again: it destroys the gard, so
Norns stops that gard's worker wherever it is running and the space
leaves every client's sidebar. `/quit` does not — the worker keeps this
space open, and `sleip stop` closes it in this checkout. `NORNS_GARD` and `NORNS_GARD_CLAIM_TOKEN` override it, and
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

## The team

The agent does not have to work alone. The worker also serves two
helpers, and the agent decides per task whether to do the work itself or
hand it out:

- **`sleipnir-explore`** reads: `read_file`, `grep`, `glob`, `git`.
  Nothing it is offered can change the repository. The agent sends
  explorers the questions whose answers mean reading a lot, several at
  once when they are independent, and gets back the conclusion rather
  than every file.
- **`sleipnir-code`** is the one helper that changes things. There is one
  per session: Norns reuses its conversation, so it remembers what it was
  asked before, and a second assignment while it is still working is
  refused rather than starting a second writer.

What each can do is set by the worker and enforced by Norns, which offers
an agent only its own tools and refuses a call to any other; only the
agent can launch the helpers. The agent chooses who does the work, never
what they may do. Helpers' changes go through the same allow list, and
when one needs permission it asks you directly — the question appears in
the session that launched it, marked with the helper's name, and your
answer goes to the helper's run. Their conversations are not listed as
sessions of their own.

```bash
sleip config set explore_model claude-haiku-4-5   # empty: the agent's own model
sleip config set code_model claude-opus-5
sleip config set team off                          # the agent works alone
```

`git` refuses subcommands that write, arguments that write a file or read
one outside the repository, and the diff drivers, pagers and signature
checks a repository's config could make it run, so it never asks for
permission. It still runs git with this repository's config, as you do.

## Configuring it, from inside it

`sleip` is also the configuration tool, and the agent can run it
through `bash`:

```bash
sleip setup       # the keys, stored for every space (--force to re-ask)
sleip allow list | add <tool> <pattern> | remove <tool> <pattern>
sleip config show | set <key> <value> | unset <key>   # agent, model, max_steps, compact_at, keep, max_tokens, team, explore_model, code_model
sleip doctor      # connection, keys, gard, allow list
sleip docs        # the reference the agent reads
sleip help        # the commands, in brief
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
