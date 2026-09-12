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


def _read_pid_file(root: Path) -> tuple[int, str | None] | None:
    """(pid, url) from the pid file. The url line is what the worker was
    started against; older files have only a pid."""
    try:
        lines = pid_path(root).read_text().splitlines()
        pid = int(lines[0].strip())
    except (OSError, ValueError, IndexError):
        return None
    url = lines[1].strip() if len(lines) > 1 and lines[1].strip() else None
    return pid, url


def running(root: Path) -> int | None:
    """The pid of this checkout's worker, if one is actually running."""
    entry = _read_pid_file(root)
    if entry is None:
        return None
    pid, _ = entry
    if alive(pid):
        return pid
    pid_path(root).unlink(missing_ok=True)  # it died without cleaning up
    return None


def serving_url(root: Path) -> str | None:
    """Which Norns this checkout's running worker was started against.

    A worker reads its environment once, at launch. Point the client
    somewhere else and the two drift apart silently — the client shows a
    healthy space that no worker is listening to. This is what lets the
    client notice.
    """
    entry = _read_pid_file(root)
    if entry is None:
        return None
    pid, url = entry
    return url if alive(pid) else None


def start(root: Path, argv_extra: list[str] | None = None, url: str | None = None) -> tuple[int | None, str]:
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

    url = url or os.environ.get("NORNS_URL") or ""
    pid_path(root).write_text(f"{child.pid}\n{url}\n")
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
