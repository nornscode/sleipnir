"""`sleip workers`: every worker on this machine, and stopping or
restarting them without hunting for them."""

import os
from pathlib import Path

import pytest

from sleipnir import daemon, workers
from sleipnir.cli import build_parser, main, serve_flags
from sleipnir.permissions import always_asks


@pytest.fixture
def live(monkeypatch):
    """Every recorded pid is a running worker, except those added here."""
    dead: set[int] = set()
    monkeypatch.setattr(workers, "is_worker_process", lambda pid: pid not in dead)
    return dead


def worker(pid, root, **kw):
    return workers.Worker(
        pid=pid, root=Path(root), url=kw.get("url", "http://localhost:4001"),
        worker_id=kw.get("worker_id", f"sleipnir-x-{pid}"), gard_id=kw.get("gard_id"),
        started=kw.get("started", 1000.0), flags=kw.get("flags", []),
    )


def test_a_worker_is_listed_until_its_process_is_gone(live, tmp_path):
    workers.register(worker(101, tmp_path / "a", flags=["--no-gard"]))
    workers.register(worker(102, tmp_path / "b"))
    assert [(w.pid, w.flags) for w in workers.listed()] == [(101, ["--no-gard"]), (102, [])]

    live.add(101)
    assert [w.pid for w in workers.listed()] == [102]
    assert not (workers.REGISTRY / "101.json").exists()


def test_a_record_that_cannot_be_read_is_dropped(live):
    workers.REGISTRY.mkdir(parents=True, exist_ok=True)
    (workers.REGISTRY / "5.json").write_text("{nope")
    assert workers.listed() == []
    assert not (workers.REGISTRY / "5.json").exists()


def test_a_record_does_not_outlive_a_reused_pid():
    # This test's own pid is alive, but it is not a worker.
    assert not workers.is_worker_process(os.getpid())


def test_workers_are_chosen_by_pid_name_or_path(tmp_path):
    a, b = worker(1, tmp_path / "missive"), worker(2, tmp_path / "org-mobile")
    chosen, unmatched = workers.select([a, b], ["missive", "2", str(tmp_path / "missive"), "nope"])
    assert chosen == [a, b]
    assert unmatched == ["nope"]


def test_the_listing_says_what_norns_says_and_which_run_older_code(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    a = worker(1, tmp_path / "missive", worker_id="w-a", started=500.0)
    b = worker(2, tmp_path / "org-mobile", worker_id="w-b", started=1500.0)
    c = worker(3, tmp_path / "other", url="http://localhost:4000", worker_id="w-c", started=1500.0)
    view = workers.NornsView(
        "http://localhost:4001",
        {"w-a": {"worker_id": "w-a", "gard": 9, "draining": False},
         "w-far": {"worker_id": "w-far", "gard": 12, "draining": True}},
        {9: "missive", 12: "laptop"},
    )
    lines = workers.table_lines([a, b, c], now=2000.0, changed_at=1000.0, norns=view, norns_url="http://localhost:4001")
    text = "\n".join(lines)

    def row(pid):
        return next(line for line in lines if line.strip().startswith(f"{pid} "))

    assert "~/missive" in row(1)
    assert "connected" in row(1) and "not connected" not in row(1) and "older code" in row(1)
    assert "not connected" in row(2) and "older code" not in row(2)
    # Served by another Norns: this one cannot say whether it is connected.
    assert "connected" not in row(3)
    assert "restart --stale" in text
    assert "w-far  laptop · draining" in text


def test_nothing_running_says_how_to_start_one():
    assert "no workers" in workers.table_lines([], now=0, changed_at=0)[0]


def test_restart_starts_the_same_worker_in_the_environment_it_is_given(tmp_path, monkeypatch):
    old = worker(7, tmp_path / "missive", flags=["--model", "claude-opus-5"])
    calls = {}
    monkeypatch.setattr(daemon, "stop_pid", lambda pid, timeout=0: (True, f"worker stopped (pid {pid})"))

    def start(root, flags, url=None, env=None):
        calls.update(root=root, flags=flags, env=env)
        workers.register(worker(8, root, url="http://localhost:4001"))
        return 8, "worker running"

    monkeypatch.setattr(daemon, "start", start)
    message = workers.restart(old, {"PATH": "/bin"})
    assert message.endswith("restarted (pid 8)")
    assert calls == {"root": old.root, "flags": ["--model", "claude-opus-5"], "env": {"PATH": "/bin"}}


def test_a_restart_that_lands_on_another_norns_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "stop_pid", lambda pid, timeout=0: (True, "stopped"))

    def start(root, flags, url=None, env=None):
        workers.register(worker(8, root, url="http://localhost:4000"))
        return 8, "worker running"

    monkeypatch.setattr(daemon, "start", start)
    assert "now serving http://localhost:4000 (was http://localhost:4001)" in workers.restart(worker(7, tmp_path / "x"), {})


def test_a_worker_still_draining_is_not_restarted_beside_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "stop_pid", lambda pid, timeout=0: (False, "worker (pid 7) is still draining"))
    monkeypatch.setattr(daemon, "start", lambda *a, **k: pytest.fail("started a second worker"))
    assert "not starting another" in workers.restart(worker(7, tmp_path / "x"), {})


def test_stopping_needs_to_be_told_which(capsys, live, tmp_path):
    workers.register(worker(101, tmp_path / "a"))
    assert main(["--root", str(tmp_path), "workers", "stop"]) == 1
    assert "--all" in capsys.readouterr().err


def test_a_restart_does_not_carry_this_checkouts_environment(tmp_path, monkeypatch, live):
    (tmp_path / ".env").write_text("NORNS_URL=http://from-this-checkout\n")
    monkeypatch.delenv("NORNS_URL", raising=False)
    workers.register(worker(101, tmp_path / "a"))
    seen = {}
    monkeypatch.setattr(workers, "restart", lambda w, env: seen.update(env=env) or "~/a: restarted (pid 9)")
    try:
        assert main(["--root", str(tmp_path), "workers", "restart", "--all"]) == 0
    finally:
        os.environ.pop("NORNS_URL", None)
    assert "NORNS_URL" not in seen["env"]


def test_restart_stale_leaves_current_workers_alone(tmp_path, monkeypatch, live, capsys):
    workers.register(worker(101, tmp_path / "old", started=10.0))
    workers.register(worker(102, tmp_path / "new", started=10_000_000_000.0))
    monkeypatch.setattr(workers, "restart", lambda w, env: f"{w.root.name}: restarted (pid 1)")
    assert main(["--root", str(tmp_path), "workers", "restart", "--stale"]) == 0
    out = capsys.readouterr().out
    assert "old: restarted" in out and "new" not in out


def test_a_worker_keeps_the_flags_it_was_started_with():
    args = build_parser().parse_args(["serve", "--foreground", "--model", "claude-opus-5", "--max-steps", "50", "--no-gard"])
    assert serve_flags(args) == ["--model", "claude-opus-5", "--max-steps", "50", "--no-gard"]


def test_stopping_workers_from_inside_one_always_asks():
    assert always_asks("bash", "sleip workers restart --all")
    assert always_asks("bash", "sleip stop")
    assert not always_asks("bash", "sleip workers")
