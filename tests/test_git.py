import subprocess

import pytest

from sleipnir import runtime
from sleipnir.permissions import Permissions
from sleipnir.tools.git import git, refusal
from sleipnir.workspace import ToolError


@pytest.fixture
def repo(ws):
    def run(*args):
        subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True)

    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    (ws / "a.txt").write_text("one\n")
    run("add", "a.txt")
    run("commit", "-qm", "first")
    (ws / "a.txt").write_text("one\ntwo\n")
    run("commit", "-qam", "second")
    return ws


def test_git_reads_history(repo):
    assert "second" in git.handler("log --oneline")
    assert "+two" in git.handler("git show HEAD -- a.txt")
    assert "first" in git.handler("log --oneline HEAD~1")
    assert "first" not in git.handler("log --oneline HEAD~1..HEAD")


def test_git_never_asks(repo):
    # An empty allow list: a reading tool must not raise PermissionRequired.
    runtime._permissions = Permissions(None)
    assert git.handler("status --short") == "(no output)"


@pytest.mark.parametrize("args", ["commit -m x", "checkout -b x", "config core.pager evil", "push", "branch -D main", ""])
def test_git_refuses_commands_that_write(repo, args):
    with pytest.raises(ToolError, match="not a reading command"):
        git.handler(args)


@pytest.mark.parametrize(
    "arg",
    ["--output=/tmp/x", "--no-index", "--contents=/etc/passwd", "--ext-diff", "--textconv",
     "-O/tmp/order", "-f", "--format=%G?", "/etc/passwd", "../other", "~/.ssh/id_rsa", "--exclude-from=../x"],
)
def test_git_refuses_arguments_that_escape(arg):
    assert refusal(arg)


@pytest.mark.parametrize("arg", ["main..HEAD", "origin/main...HEAD", "-L", "40,60", "--oneline", "lib/x.ex", "HEAD:lib/x.ex", "-p"])
def test_git_allows_ordinary_arguments(arg):
    assert refusal(arg) is None


def test_git_ignores_a_configured_external_diff(repo):
    # A reading command must not run what the repository's config names.
    marker = repo / "ran"
    subprocess.run(["git", "config", "diff.external", f"touch {marker}; true"], cwd=repo, check=True)
    git.handler("diff HEAD~1")
    git.handler("log -p -1")
    assert not marker.exists()


def test_git_reports_errors(repo):
    with pytest.raises(ToolError, match="unknown revision|bad revision"):
        git.handler("show nosuchref")
