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
