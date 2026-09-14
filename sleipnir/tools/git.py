"""git, for reading history: the one thing an explorer could not do
without bash.

Read-only by construction, so it never asks. Only subcommands that read
are accepted, arguments that would write a file, read one outside the
root, or run a configured program are refused, and the settings that
make a reading command run one are switched off on every call.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess

from norns import tool

from sleipnir import runtime
from sleipnir.tools.shell import HIDDEN_ENV, truncate
from sleipnir.workspace import ToolError

SUBCOMMANDS = {"log", "show", "diff", "blame", "status", "ls-files", "grep", "rev-parse", "shortlog", "describe"}
# Diff machinery that runs a program a config names: switched off where
# the subcommand accepts the switch.
NO_PROGRAMS = {
    "log": ["--no-ext-diff", "--no-textconv"],
    "show": ["--no-ext-diff", "--no-textconv"],
    "diff": ["--no-ext-diff", "--no-textconv"],
    "blame": ["--no-textconv"],
    "grep": ["--no-textconv"],
}
SAFE_CONFIG = ["-c", "core.fsmonitor=false", "-c", "core.pager=cat", "-c", "log.showSignature=false"]
# Writes a file (--output), reads one from anywhere (--no-index, --contents,
# --exclude-from, -O, -f), or runs a program (--ext-diff, --textconv, a
# pager, signature checking).
REFUSED_OPTIONS = (
    "--output", "--no-index", "--contents", "--exclude-from", "--ext-diff", "--textconv",
    "--open-files-in-pager", "--show-signature", "--file", "--git-dir", "--work-tree", "--paginate",
)
REFUSED_SHORT = re.compile(r"\A-(O|f)")
TIMEOUT = 60


def refusal(arg: str) -> str | None:
    """Why an argument is refused, or None."""
    if arg.startswith("--") and arg.split("=", 1)[0] in REFUSED_OPTIONS:
        return f"{arg.split('=', 1)[0]} is not available here"
    if REFUSED_SHORT.match(arg):
        return f"{arg[:2]} is not available here"
    if "%G" in arg:
        return "signature placeholders run gpg and are not available here"
    value = arg.split("=", 1)[1] if arg.startswith("-") and "=" in arg else arg
    if value.startswith(("/", "~")) or ".." in value.split("/"):
        return f"{value} is outside the repository"
    return None


@tool
def git(args: str) -> str:
    """Read the repository's history with git: log, show, diff, blame,
    status, ls-files, grep, rev-parse, shortlog, describe. args is the
    command after `git`, such as "log --oneline -20 -- lib/x.ex" or
    "blame -L 40,60 lib/x.ex". It cannot change anything, so it never
    asks; use bash for git commands that write."""
    try:
        argv = shlex.split(args)
    except ValueError as e:
        raise ToolError(f"cannot parse arguments: {e}") from e
    if argv and argv[0] == "git":
        argv = argv[1:]
    if not argv or argv[0] not in SUBCOMMANDS:
        raise ToolError(f"git {argv[0] if argv else ''} is not a reading command; this tool runs {', '.join(sorted(SUBCOMMANDS))}")
    sub, rest = argv[0], argv[1:]
    for arg in rest:
        reason = refusal(arg)
        if reason:
            raise ToolError(reason)

    env = {k: v for k, v in os.environ.items() if k not in HIDDEN_ENV and not k.startswith("GIT_")}
    env["GIT_PAGER"] = "cat"
    try:
        out = subprocess.run(
            ["git", *SAFE_CONFIG, "--no-pager", sub, *NO_PROGRAMS.get(sub, []), *rest],
            cwd=runtime.workspace().root, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, errors="replace", timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"git {sub} took longer than {TIMEOUT}s; narrow it")
    except OSError as e:
        raise ToolError(f"git is not usable here: {e}") from e
    if out.returncode != 0:
        raise ToolError(truncate((out.stderr or out.stdout).strip() or f"git exited {out.returncode}"))
    return truncate(out.stdout) if out.stdout else "(no output)"
