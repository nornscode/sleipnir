"""Every worker on this machine, and the means to stop or restart them.

A worker is started from its checkout — by `sleip`, by /start in the
client, by `sleip serve` — and afterwards nothing knew where they all
were: stopping them meant finding them in ps. So a worker writes a record
of itself to ~/.sleipnir/workers/ when it starts serving and removes it
when it stops, and `sleip workers` reads that directory. A record whose
process has gone is dropped the next time anyone looks.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sleipnir import daemon
from sleipnir.env import SLEIPNIR_HOME

REGISTRY = SLEIPNIR_HOME / "workers"
# The SDK drains for up to 30s before it lets go.
STOP_TIMEOUT = 35.0
# How long a restart waits for the new worker to say where it is serving.
REGISTER_WAIT = 10.0


@dataclass
class Worker:
    pid: int
    root: Path
    url: str
    worker_id: str
    gard_id: int | None
    started: float
    # The serve flags it was started with, so a restart starts the same worker.
    flags: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {**asdict(self), "root": str(self.root)}

    @classmethod
    def from_json(cls, data: dict) -> Worker:
        return cls(
            pid=int(data["pid"]), root=Path(data["root"]), url=str(data.get("url") or ""),
            worker_id=str(data.get("worker_id") or ""), gard_id=data.get("gard_id"),
            started=float(data["started"]), flags=[str(f) for f in data.get("flags") or []],
        )


def new_worker_id(root: Path) -> str:
    """NORNS_WORKER_ID when a provisioner set one; else a fresh id per start,
    as the SDK would make, but saying which checkout it serves."""
    return os.environ.get("NORNS_WORKER_ID") or f"sleipnir-{root.name}-{uuid.uuid4().hex[:8]}"


def register(worker: Worker) -> None:
    REGISTRY.mkdir(parents=True, exist_ok=True)
    (REGISTRY / f"{worker.pid}.json").write_text(json.dumps(worker.to_json(), indent=2))


def unregister(pid: int) -> None:
    (REGISTRY / f"{pid}.json").unlink(missing_ok=True)


def is_worker_process(pid: int) -> bool:
    """Alive, and still a worker. Pids are reused, and a record that
    outlived its process must not aim `stop` at whatever took the number."""
    if not daemon.alive(pid):
        return False
    try:
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell; the record is all we have
    return "sleip" in command and "serve" in command.split()


def listed() -> list[Worker]:
    """The workers running on this machine, by checkout."""
    found = []
    for path in sorted(REGISTRY.glob("*.json")) if REGISTRY.is_dir() else []:
        try:
            worker = Worker.from_json(json.loads(path.read_text()))
        except (OSError, ValueError, KeyError, TypeError):
            path.unlink(missing_ok=True)
            continue
        if not is_worker_process(worker.pid):
            path.unlink(missing_ok=True)
            continue
        found.append(worker)
    return sorted(found, key=lambda w: (str(w.root), w.pid))


def code_changed_at() -> float:
    """When the code a worker loads last changed: sleipnir's or the SDK's.
    A worker started before then is running something older than a fresh
    one would, which is exactly the worker that wants a restart."""
    import norns

    import sleipnir

    newest = 0.0
    for package in (sleipnir, norns):
        for f in Path(package.__file__).parent.rglob("*.py"):
            try:
                newest = max(newest, f.stat().st_mtime)
            except OSError:
                pass
    return newest


def select(workers: list[Worker], targets: list[str]) -> tuple[list[Worker], list[str]]:
    """The workers named by pid, checkout name, or checkout path, and the
    targets that named none."""
    chosen: list[Worker] = []
    unmatched: list[str] = []
    for target in targets:
        path = Path(target).expanduser()
        by_path = path.is_absolute() or os.sep in target
        hits = [
            w for w in workers
            if target == str(w.pid) or target == w.root.name or (by_path and w.root == path.resolve())
        ]
        if not hits:
            unmatched.append(target)
        chosen += [w for w in hits if w not in chosen]
    return chosen, unmatched


def display_root(root: Path) -> str:
    home = str(Path.home())
    text = str(root)
    return "~" + text[len(home):] if text == home or text.startswith(home + os.sep) else text


def stop(worker: Worker, timeout: float = STOP_TIMEOUT) -> tuple[bool, str]:
    stopped, message = daemon.stop_pid(worker.pid, timeout)
    if stopped:
        unregister(worker.pid)
        daemon.running(worker.root)  # clears the checkout's pid file if it was this one
    return stopped, message


def restart(worker: Worker, env: dict[str, str]) -> str:
    """Stop a worker and start it again from its checkout, with its flags.

    `env` is the environment to start it in. The new worker loads its own
    checkout's .envrc and .env, which only fill in what `env` lacks, so the
    caller leaves out whatever it loaded for somewhere else.
    """
    where = display_root(worker.root)
    stopped, message = stop(worker)
    if not stopped:
        return f"{where}: {message} — not starting another beside it; restart it again once it has stopped"
    pid, started = daemon.start(worker.root, worker.flags, url=worker.url, env=env)
    if pid is None:
        return f"{where}: stopped, but the new worker did not start — {started}"
    new = wait_for(pid)
    if new is None:
        return f"{where}: restarted (pid {pid}) but it has not started serving — see {daemon.log_path(worker.root)}"
    if new.url.rstrip("/") != worker.url.rstrip("/"):
        return f"{where}: restarted (pid {pid}), now serving {new.url} (was {worker.url})"
    return f"{where}: restarted (pid {pid})"


def wait_for(pid: int, timeout: float = REGISTER_WAIT) -> Worker | None:
    """The record a new worker writes once it has its gard and is about
    to connect; None if it died first or took too long."""
    path = REGISTRY / f"{pid}.json"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return Worker.from_json(json.loads(path.read_text()))
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if not daemon.alive(pid):
            return None
        time.sleep(0.2)
    return None


@dataclass
class NornsView:
    """What one Norns says is connected: {worker_id: entry}, and gard names."""

    url: str
    connected: dict[str, dict]
    gard_names: dict[int, str]


def norns_view(url: str, api_key: str) -> NornsView | None:
    import asyncio

    from sleipnir.api import NornsApi

    async def fetch():
        api = NornsApi(url, api_key)
        try:
            return await api.workers(), await api.gards()
        finally:
            await api.close()

    try:
        connected, gards = asyncio.run(fetch())
    except Exception:
        return None
    return NornsView(
        url.rstrip("/"),
        {c["worker_id"]: c for c in connected or [] if c.get("worker_id")},
        {g["id"]: g.get("name") or str(g["id"]) for g in gards or []},
    )


def uptime(seconds: float) -> str:
    s = int(max(seconds, 0))
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def table_lines(
    workers: list[Worker], *, now: float, changed_at: float,
    norns: NornsView | None = None, norns_url: str | None = None,
) -> list[str]:
    """`sleip workers`. Norns speaks only for the workers serving its url;
    a worker pointed at another Norns shows no connection state at all
    rather than a wrong one."""
    lines: list[str] = []
    if not workers:
        lines.append("no workers on this machine. `sleip` in a checkout starts one, or `sleip serve`.")
    else:
        rows = [("PID", "CHECKOUT", "NORNS", "UP", "STATE")]
        for w in workers:
            state = []
            if norns is not None and w.url.rstrip("/") == norns.url:
                entry = norns.connected.get(w.worker_id)
                state.append("not connected" if entry is None else ("draining" if entry.get("draining") else "connected"))
            if w.started < changed_at:
                state.append("older code")
            rows.append((str(w.pid), display_root(w.root), w.url or "?", uptime(now - w.started), " · ".join(state)))
        widths = [max(len(r[i]) for r in rows) for i in range(4)]
        count = len(workers)
        lines.append(f"{count} worker{'s' if count != 1 else ''} on this machine")
        for r in rows:
            lines.append("  " + "  ".join(r[i].ljust(widths[i]) for i in range(4)) + "  " + r[4])
        if any(w.started < changed_at for w in workers):
            lines.append("")
            lines.append("older code: started before sleipnir or the SDK last changed — `sleip workers restart --stale`")
    if norns is not None:
        local = {w.worker_id for w in workers}
        others = [c for wid, c in sorted(norns.connected.items()) if wid not in local]
        if others:
            lines.append("")
            lines.append(f"connected to {norns.url} from elsewhere:")
            for c in others:
                gard = c.get("gard")
                gard_id = gard.get("id") if isinstance(gard, dict) else gard
                where = norns.gard_names.get(gard_id, f"gard {gard_id}") if gard_id is not None else "no gard"
                lines.append(f"  {c['worker_id']}  {where}{' · draining' if c.get('draining') else ''}")
    elif norns_url:
        lines.append("")
        lines.append(f"(could not ask {norns_url} which workers are connected)")
    return lines
