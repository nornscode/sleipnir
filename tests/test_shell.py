import os

import pytest

from sleipnir.permissions import PermissionRequired
from sleipnir.tools.shell import bash, truncate


def test_bash_runs_in_root(ws, allow):
    allow("bash pwd", "bash echo *", "bash exit *")
    assert bash.handler("pwd") == f"exit code: 0\n{ws.resolve()}\n"
    assert bash.handler("echo hi >&2; exit 3") == "exit code: 3\nhi\n"


def test_bash_hides_worker_secrets(ws, allow, monkeypatch):
    allow("bash printenv *")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("SOME_OTHER", "visible")
    assert bash.handler("printenv ANTHROPIC_API_KEY") == "exit code: 1\n"
    assert bash.handler("printenv SOME_OTHER") == "exit code: 0\nvisible\n"


def test_bash_timeout_kills_process_group(ws, allow):
    allow("bash sleep *", "bash sh *")
    out = bash.handler("sh -c 'sleep 30' & sleep 30", timeout_seconds=1)
    assert out.startswith("exit code: timed out after 1s (killed)")


def test_bash_asks_for_unlisted_commands(ws, allow):
    allow("bash git *")
    with pytest.raises(PermissionRequired, match="bash: git status && rm -rf build"):
        bash.handler("git status && rm -rf build")


def test_truncate_keeps_head_and_tail():
    out = truncate("a" * 100 + "b" * 100, limit=50)
    assert out.startswith("a" * 25) and out.endswith("b" * 25) and "150 chars truncated" in out
