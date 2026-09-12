"""The worker as a background process, so a checkout being open does not
cost a terminal.

A worker is "this checkout is open"; the client is "I am looking at it".
They are not the same lifetime, and tying them together is what made a
space go quiet the moment its window closed.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from sleipnir.runtime import SLEIPNIR_DIR

PID_FILE = "worker.pid"
LOG_FILE = "sleipnir.log"


def pid_path(root: Path) -> Path:
    return root / SLEIPNIR_DIR / PID_FILE


def log_path(root: Path) -> Path:
    return root / SLEIPNIR_DIR / LOG_FILE


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's, but running
    return True


def running(root: Path) -> int | None:
    """The pid of this checkout's worker, if one is actually running."""
    try:
        pid = int(pid_path(root).read_text().strip())
    except (OSError, ValueError):
        return None
    if alive(pid):
        return pid
    pid_path(root).unlink(missing_ok=True)  # it died without cleaning up
    return None


def start(root: Path, argv_extra: list[str] | None = None) -> tuple[int | None, str]:
    """Start the worker detached, unless one is already serving this root.

    Returns (pid, message). The child is `sleip serve --foreground` in a
    session of its own, so closing this terminal does not take it down.
    """
    existing = running(root)
    if existing:
        return existing, f"worker already running (pid {existing})"

    log = log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("a")
    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "sleipnir.cli", "--root", str(root), "serve", "--foreground"]
            + (argv_extra or []),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=handle,
            start_new_session=True,  # survives this terminal
            cwd=str(root),
        )
    finally:
        handle.close()

    # A worker that cannot connect dies in the first second; say so now
    # rather than leaving a pid file pointing at nothing.
    time.sleep(0.6)
    if child.poll() is not None:
        return None, f"worker exited immediately — see {log}"

    pid_path(root).write_text(f"{child.pid}\n")
    return child.pid, f"worker running (pid {child.pid}), logging to {log}"


def stop(root: Path, timeout: float = 15.0) -> str:
    """Ask this checkout's worker to drain and stop."""
    pid = running(root)
    if pid is None:
        return "no worker running for this checkout"

    try:
        os.kill(pid, signal.SIGTERM)  # the SDK drains on SIGTERM
    except OSError as e:
        return f"could not signal the worker (pid {pid}): {e}"

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not alive(pid):
            pid_path(root).unlink(missing_ok=True)
            return f"worker stopped (pid {pid})"
        time.sleep(0.2)
    return f"worker (pid {pid}) is still draining; it will stop on its own"
