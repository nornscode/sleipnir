import pytest

from sleipnir.tools.search import glob, grep
from sleipnir.workspace import ToolError


@pytest.fixture
def tree(ws):
    (ws / "lib").mkdir()
    (ws / "lib" / "a.ex").write_text("defmodule A do\n  def hello, do: :world\nend\n")
    (ws / "lib" / "b.py").write_text("def hello():\n    return 'world'\n")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "c.py").write_text("def hello(): pass\n")
    (ws / "img.bin").write_bytes(b"hello\x00hello")
    return ws


def test_grep_finds_lines_and_skips_junk(tree):
    out = grep.handler("hello")
    assert out.splitlines() == ["lib/a.ex:2:  def hello, do: :world", "lib/b.py:1:def hello():"]


def test_grep_include_and_ignore_case(tree):
    assert grep.handler("HELLO", include="*.py", ignore_case=True) == "lib/b.py:1:def hello():"
    assert grep.handler("HELLO", include="*.py") == "(no matches in 1 files)"


def test_grep_limits_and_validates(tree):
    out = grep.handler("hello", max_results=1)
    assert out.endswith("[stopped at 1 matches; narrow the pattern or path]")
    with pytest.raises(ToolError, match="invalid regular expression"):
        grep.handler("(")


def test_glob(tree):
    assert glob.handler("**/*.py") == "lib/b.py"
    assert glob.handler("*.ex", path="lib") == "lib/a.ex"
    assert glob.handler("*.rs") == "(no matches)"


def _git_repo(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def test_search_leaves_out_what_the_repository_ignores(tmp_path, monkeypatch):
    """A hard-coded skip list cannot know this repo ignores DerivedData, so
    a search crawled hundreds of build artifacts and the model had to work
    out for itself that `git ls-files` was the real answer."""
    root = _git_repo(tmp_path)
    (root / ".gitignore").write_text("DerivedData/\n*.log\n")
    (root / "RootView.swift").write_text("struct RootView { // needle\n}\n")
    (root / "noise.log").write_text("needle\n")
    (root / "DerivedData").mkdir()
    (root / "DerivedData" / "Build.swift").write_text("// needle\n")

    from sleipnir import runtime
    from sleipnir.workspace import Workspace

    monkeypatch.setattr(runtime, "workspace", lambda: Workspace(root))

    found = glob.handler("**/*.swift")
    assert "RootView.swift" in found
    assert "DerivedData" not in found

    hits = grep.handler("needle")
    assert "RootView.swift" in hits
    assert "DerivedData" not in hits and "noise.log" not in hits

    # An ignored file is still readable when the model asks for it by name:
    # this filters searching, not access.
    # Filtering search is not blocking access: read_file still opens it.
    assert (root / "DerivedData" / "Build.swift").is_file()


def test_search_still_works_outside_a_git_checkout(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("needle\n")

    from sleipnir import runtime
    from sleipnir.workspace import Workspace

    monkeypatch.setattr(runtime, "workspace", lambda: Workspace(tmp_path))
    assert "a.py" in glob.handler("**/*.py")
    assert "a.py" in grep.handler("needle")
