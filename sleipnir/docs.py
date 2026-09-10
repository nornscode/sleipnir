"""The AI-facing reference, printed by `sleip docs`."""

DOCS = """# Sleipnir reference

Sleipnir is the coding harness you are running in. Its loop runs in
Norns; this process, on the developer's machine, is both the client they
are looking at and the worker that serves your tools and LLM calls. The
working directory is the repository root and every path is relative to
it.

## Where you are running

You are one session inside `sleip`, a full-screen terminal client open
in front of the developer right now. Its layout:

- The left column is the **spaces**: one per repository checkout with a
  worker running in it, this one first, each showing how many of its
  sessions are working or waiting on the user. Sessions that no gard
  serves share a "no gard" space.
- The tabs across the top are the **sessions** of the selected space.
  Each is a Norns conversation with its own history and run.
- The box along the bottom is where the user types. What they write
  there becomes your next message, and when you ask something with
  ask_human their next line is the answer.
- The status bar under it counts spaces, sessions, how many are working
  and how many need the user, then names this checkout and the agent.

Commands the user types in that box (they are the client's, not yours):

    /new              start a new session in this space (ctrl+n)
    /fork N [message] fork this session from step N into a new one
    /spaces           every space, with whether a worker is in it
    /resume           reload this session and re-attach to its run
    /close            close the tab (ctrl+w); the session lives on
    /delete           delete this session from Norns (asks once)
    /help             that list
    /quit             leave; the worker stops, sessions live on in Norns

Keys: ctrl+n new session, ctrl+w close tab, ctrl+r refresh, ctrl+q quit.

Because the loop is in Norns and not in this process, the session
outlives the client: closing it, the terminal, or the worker leaves the
history and state intact, and `sleip` reopens them. Only the working
tree is local, so a session's tool calls always run on the machine whose
worker started it.

## Tools

- read_file(path, offset=1, limit=0): file contents; large files are
  cut and the tail says where to continue. Never needs permission.
- grep(pattern, path=".", include="", ignore_case=false, max_results=200):
  regex search; output is path:line:text. Never needs permission.
- glob(pattern, path="."): files by name, e.g. "**/*.ex". Never needs
  permission.
- edit_file(path, old_string, new_string, replace_all=false, approval=""):
  replace one exact block; whitespace-only indent differences are
  tolerated; ambiguous matches fail with line numbers.
- write_file(path, content, approval=""): create or overwrite a file.
- bash(command, timeout_seconds=120, approval=""): run a command from
  the root; returns the exit code and output, truncated in the middle
  when long. Your worker's credentials are not in its environment.

## Permissions

edit_file, write_file, and bash check the allow list at .sleipnir/allow.
Outside it, the tool answers "permission required" with a token such as
p-1a2b3c. Then:

1. Ask the user with ask_human. The question must contain the exact
   action and the token in square brackets:
   Allow bash `rm -rf build`? (yes / always / no) [p-1a2b3c]
2. The user answers yes (once), always (adds a rule), or no.
3. Retry the same call with approval="p-1a2b3c".

A token is valid for that one action. The worker reads the user's real
answer from the conversation; retrying without one is refused. Do not
work around a refusal.

## Allow list

.sleipnir/allow has one rule per line: `tool pattern`, where pattern is
an fnmatch glob over the shell command (bash) or the path (file tools).
A shell command is split into simple commands (a && b, pipes, subshells)
and each must match a rule. A command with a backtick always asks.

    bash git *
    bash uv run pytest*
    edit_file *
    write_file docs/*

Changes to the allow list or to .sleipnir/ always ask, whatever the
list says. To add a rule, run `sleip allow add <tool> <pattern>`
through bash and expect a permission request.

## The sleip command

That is the whole surface; there is nothing else to discover.

    sleip           the client with this repository's worker (the default)
    sleip run       the same thing, named
    sleip serve     the worker alone, headless, for a machine nobody sits at
    sleip chat      the client alone, without a worker
    sleip allow     the allow list, above
    sleip config    settings, below
    sleip doctor    check the connection, keys, gard, and allow list
    sleip docs      this text
    sleip help      the commands, in brief

Anywhere: --root <dir> (repository root, default the current
directory), --env-file <file>, --version. run, serve and chat also take
--agent, --model, --max-steps, --compact-at, --keep and --no-gard (do
not pin the worker to a per-repository gard).

## Configuring the harness

Run these through bash from the repository root:

- sleip allow list | add <tool> <pattern> | remove <tool> <pattern>
- sleip config show | set <key> <value> | unset <key>
  keys: agent (name in Norns), model, max_steps, compact_at (input
  tokens at which the history is folded into a summary), keep (messages
  kept verbatim after that)
- sleip doctor: checks the connection, keys, and config
- sleip docs: this text

Config lives in .sleipnir/config and takes effect when the worker
restarts. A flag or SLEIPNIR_<KEY> in the environment overrides it.
NORNS_URL, NORNS_API_KEY and the LLM key come from the process
environment, `--env-file`, the repository's .envrc (through direnv), or
its .env, in that order.
Startup loads the repository's approved direnv environment, including
when --root is used. Define exports in .envrc, or use `dotenv` there to
load .env. The user must approve .envrc with `direnv allow`; restart the
worker after environment changes. Project variables reach bash, except
for the worker credential variables. doctor and config show also load
direnv; config edits and allow-list commands do not.
"""
