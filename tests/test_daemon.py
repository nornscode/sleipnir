"""The detached worker's pid file, and what it lets the client notice."""

import os
from pathlib import Path

from sleipnir import daemon


def write_pid_file(root: Path, text: str) -> None:
    path = daemon.pid_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_the_pid_file_records_which_norns_the_worker_serves(tmp_path):
    # A worker reads its environment once, at launch. The client reads it
    # every start. Without this line nothing can compare the two.
    write_pid_file(tmp_path, f"{os.getpid()}\nhttp://localhost:4000\n")

    assert daemon.running(tmp_path) == os.getpid()
    assert daemon.serving_url(tmp_path) == "http://localhost:4000"


def test_a_pid_file_without_a_url_still_works(tmp_path):
    """Written by an older sleip: a pid and nothing else."""
    write_pid_file(tmp_path, f"{os.getpid()}\n")

    assert daemon.running(tmp_path) == os.getpid()
    assert daemon.serving_url(tmp_path) is None


def test_a_dead_worker_serves_nothing(tmp_path):
    write_pid_file(tmp_path, "999999\nhttp://localhost:4000\n")

    assert daemon.serving_url(tmp_path) is None
    # running() clears the stale file on its way out.
    assert daemon.running(tmp_path) is None
    assert not daemon.pid_path(tmp_path).exists()


def test_nothing_running_here(tmp_path):
    assert daemon.running(tmp_path) is None
    assert daemon.serving_url(tmp_path) is None
