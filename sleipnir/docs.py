"""The AI-facing reference, printed by `sleipnir docs`."""

DOCS = """# Sleipnir reference

Sleipnir is the coding harness you are running in. Its loop runs in
Norns; this process, on the developer's machine, serves your tools and
LLM calls. The working directory is the repository root and every path
is relative to it.

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
list says. To add a rule, run `sleipnir allow add <tool> <pattern>`
through bash and expect a permission request.

## Configuring the harness

Run these through bash from the repository root:

- sleipnir allow list | add <tool> <pattern> | remove <tool> <pattern>
- sleipnir config show | set <key> <value> | unset <key>
  keys: agent (name in Norns), model, max_steps
- sleipnir doctor: checks the connection, keys, and config
- sleipnir docs: this text

Config lives in .sleipnir/config and takes effect when the worker
restarts. A flag or SLEIPNIR_<KEY> in the environment overrides it.
"""
