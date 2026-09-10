"""bash, run from the workspace root."""

from __future__ import annotations

import os
import signal
import subprocess

from norns import tool

from sleipnir import runtime
from sleipnir.workspace import ToolError

MAX_OUTPUT_CHARS = 30_000
MAX_TIMEOUT = 600
# Worker credentials stay out of the shell the model drives.
HIDDEN_ENV = {"NORNS_API_KEY", "NORNS_GARD_CLAIM_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"}


def truncate(output: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(output) <= limit:
        return output
    half = limit // 2
    return output[:half] + f"\n... [{len(output) - limit} chars truncated] ...\n" + output[-half:]


@tool(side_effect=True)
def bash(command: str, timeout_seconds: int = 120, approval: str = "") -> str:
    """Run a shell command from the workspace root and return its exit
    code and output. Use it for tests, builds, git, and anything the
    file tools cannot do. Long output is truncated in the middle. Leave
    approval empty unless a previous call asked for permission."""
    if not command.strip():
        raise ToolError("command is empty")
    runtime.permissions().check("bash", command, approval)
    ws = runtime.workspace()
    timeout = max(1, min(timeout_seconds, MAX_TIMEOUT))
    env = {k: v for k, v in os.environ.items() if k not in HIDDEN_ENV}

    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=ws.root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, _ = proc.communicate()
        return f"exit code: timed out after {timeout}s (killed)\n{truncate(out or '')}"
    return f"exit code: {proc.returncode}\n{truncate(out or '')}"
