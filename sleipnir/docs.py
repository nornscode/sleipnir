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

- The left column is a tree of the **spaces**: one per repository
  checkout with a worker running in it, this one first, each showing
  whether it has a worker and what its sessions are doing. A space with
  no worker says so in red — nothing it is told can run until one starts.
  Runs with no gard belong to other agents on this Norns and are not
  listed; the exception is a worker started with --no-gard, which serves
  exactly those and so is shown them.
- A space is created by running `sleip` in a checkout, and no other
  way: on first start there it creates that repository's gard and
  remembers it in ~/.sleipnir/gards.json. There is no command for it,
  in the client or the CLI, so if the user asks how to start a new
  space, the answer is to open a terminal in that repository and run
  `sleip`. It then appears in every client's sidebar (ctrl+r to
  refresh one that is already open). `/new` starts a new session in
  the space you are already in, which is a different thing.
- The worker runs beside the client, not inside it: closing the window
  leaves the space open and the work running. `sleip stop` stops this
  checkout's worker, `sleip serve` starts one without a client, and
  `/start` in the client starts one for any space whose checkout is on
  this machine — which is what a space that never answers usually needs.
- Closing a space is `/close-space` or ctrl+g, and it is the opposite of starting
  one: it destroys the gard, so Norns stops that gard's worker wherever
  it runs — this machine or another — and the space disappears from
  every client. `/quit` does not do this; it stops the worker in front
  of you and leaves the space, which is why it is still there next
  time. Sessions in a closed space stay in Norns but nothing can serve
  them again, because only a worker claiming that gard could, and the
  gard is gone. Either way it asks first, in a screen of its own, with
  "Keep it" under the cursor so enter alone never closes a space.
  `/close-space force` closes one with a run still going.
- The key is the path, not the repository: a git worktree is a
  checkout of its own, so two worktrees of one repository are two
  spaces with two working trees, and a subdirectory started in by
  mistake is its own space too. The name is the directory's own name.
- Under each space are its **sessions**, one row each: every session of
  every space is visible at once, and opening one in another space does
  not close the one you were reading. Each is a Norns conversation with
  its own history and run.
- The box along the bottom is where the user types. What they write
  there becomes your next message, and when you ask something with
  ask_human their next line is the answer.
- The row under it carries the keys on the left and, on the right, what
  the sidebar cannot say: where you are, and whether anything is waiting.
- Every run in the transcript is a link: "done", a failure, and the line
  that starts a run all open that run's page in the Norns dashboard,
  where the whole event log is. Click it, or tell the user it is there.

Commands the user types in that box (they are the client's, not yours):

    /new              start a new session in this space (ctrl+n)
    /fork N [message] fork this session from step N into a new one
    /spaces           every space, with whether a worker is in it
    /resume           reload this session and re-attach to its run
    /close            hide this session from the tree (ctrl+w); it comes back
    /rename <name>    name this session; the name is stored on the session,
                      so every client shows it. Empty restores the guess
    /archive          put this session away: the tab goes and stays gone
                      across restarts, but nothing is deleted
    /archived         the sessions put away, with their ids
    /restore N        take one back out of the archive and open it
    /delete           delete this session from Norns (asks once)
    /start            start a worker for this space, if its checkout is here.
                      Sending into a space with no worker starts one too, so
                      this is for starting one before there is anything to say
    /close-space      close this space everywhere (ctrl+g)
    /help             that list
    /quit             leave; the worker stops, sessions live on in Norns

Keys: ctrl+n new session, ctrl+w close, ctrl+g close space,
ctrl+r refresh, ctrl+q quit. Tab moves focus into the tree, where
arrows walk it and enter opens a session or folds a space.

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
    sleip serve     start the worker in the background and return; --foreground
                    holds the terminal instead, which is what a container wants
    sleip chat      the client alone, without a worker
    sleip stop      stop this checkout's worker
    sleip allow     the allow list, above
    sleip config    settings, below
    sleip setup     ask for the keys and store them for every space
    sleip doctor    check the connection, keys, gard, and allow list
    sleip docs      this text
    sleip help      the commands, in brief

Anywhere: --root <dir> (repository root, default the current
directory), --env-file <file>, --version. run, serve and chat also take
--agent, --model, --max-steps, --compact-at, --keep and --no-gard (do
not pin the worker to a per-repository gard).

## Keys

sleip needs two: NORNS_API_KEY, which authenticates the client and the
worker to Norns, and an LLM key (ANTHROPIC_API_KEY, or OPENAI_API_KEY),
which this worker uses to make the model calls. The model calls happen
here, on the developer's machine — Norns dispatches the task and never
sees the LLM key.

`sleip setup` asks for them, checks them against Norns, and writes them
to ~/.sleipnir/env, owner-readable and outside every repository, so one
answer serves every space. Starting sleip without them runs the same
questions. `sleip setup --force` asks again for keys already set. A
repository's own .envrc or .env still overrides that file, which is how
one checkout points at a different Norns.

Never write a key into the repository on the user's behalf, and never
echo one back: they are secrets, and .sleipnir/ may be committed.

## When a turn is cut off

max_tokens is the ceiling on a single response, not on the history —
compaction handles the history. A turn that reaches the ceiling comes
back truncated: the run completes, the transcript says "cut off at the
response limit", and what you wrote stops mid-thought. Writing a large
file in one go is what usually does it. Carry on where it stopped, or
raise the ceiling with `sleip config set max_tokens <n>` and restart the
worker.

## Configuring the harness

Run these through bash from the repository root:

- sleip allow list | add <tool> <pattern> | remove <tool> <pattern>
- sleip config show | set <key> <value> | unset <key>
  keys: agent (name in Norns), model, max_steps, compact_at (input
  tokens at which the history is folded into a summary), keep (messages
  kept verbatim after that), max_tokens (the ceiling on one response)
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
