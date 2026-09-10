import os

import pytest

from sleipnir.permissions import PermissionRequired
from sleipnir.tools.files import edit_file, read_file, write_file
from sleipnir.workspace import ToolError


def test_read_and_write(ws, allow):
    allow("write_file *")
    assert write_file.handler("a/b.txt", "one\ntwo\nthree\n") == "wrote 14 chars to a/b.txt"
    assert read_file.handler("a/b.txt") == "one\ntwo\nthree"


def test_read_offset_and_limit(ws):
    (ws / "f.txt").write_text("\n".join(str(i) for i in range(1, 11)))
    assert read_file.handler("f.txt", offset=3, limit=2) == "3\n4\n[lines 3-4 of 10; continue with offset=5]"
    assert read_file.handler("f.txt", offset=9) == "9\n10\n[lines 9-10 of 10]"


def test_read_truncates_huge_file(ws):
    (ws / "big.txt").write_text("x" * 1000 + "\n" + ("y" * 1000 + "\n") * 100)
    out = read_file.handler("big.txt")
    assert "continue with offset=" in out
    assert len(out) < 70_000


def test_read_rejects_binary_and_missing(ws):
    (ws / "bin").write_bytes(b"\x00\x01\x02")
    with pytest.raises(ToolError, match="binary"):
        read_file.handler("bin")
    with pytest.raises(ToolError, match="not a file"):
        read_file.handler("nope.txt")


def test_paths_cannot_escape_root(ws, tmp_path_factory):
    with pytest.raises(ToolError, match="outside the workspace"):
        read_file.handler("../../etc/passwd")
    outside = tmp_path_factory.mktemp("outside") / "secret"
    outside.write_text("s")
    os.symlink(outside, ws / "link")
    with pytest.raises(ToolError, match="outside the workspace"):
        read_file.handler("link")


def test_write_requires_permission(ws):
    with pytest.raises(PermissionRequired, match=r"permission required \(token p-[0-9a-f]{6}\)\nwrite_file: x.txt"):
        write_file.handler("x.txt", "hi")
    assert not (ws / "x.txt").exists()


def test_edit_exact(ws, allow):
    allow("edit_file *")
    (ws / "f.py").write_text("def a():\n    return 1\n")
    assert edit_file.handler("f.py", "return 1", "return 2") == "edited f.py: 1 replacement"
    assert (ws / "f.py").read_text() == "def a():\n    return 2\n"


def test_edit_ambiguous_fails_with_lines(ws, allow):
    allow("edit_file *")
    (ws / "f.py").write_text("x = 1\ny = 2\nx = 1\n")
    with pytest.raises(ToolError, match=r"matches 2 times \(lines 1, 3\)"):
        edit_file.handler("f.py", "x = 1", "x = 9")
    assert edit_file.handler("f.py", "x = 1", "x = 9", replace_all=True) == "edited f.py: 2 replacements"
    assert (ws / "f.py").read_text() == "x = 9\ny = 2\nx = 9\n"


def test_edit_tolerates_indent_shift(ws, allow):
    allow("edit_file *")
    (ws / "f.py").write_text("class A:\n    def m(self):\n        if x:\n            go()\n        done()\n")
    # The model quotes the block at a different indent and with trailing spaces.
    out = edit_file.handler(
        "f.py",
        "if x:   \n    go()\n",
        "if x:\n    go()\n    more()\n",
    )
    assert out == "edited f.py: 1 replacement"
    assert (ws / "f.py").read_text() == (
        "class A:\n    def m(self):\n        if x:\n            go()\n            more()\n        done()\n"
    )


def test_edit_missing_gives_hint(ws, allow):
    allow("edit_file *")
    (ws / "f.py").write_text("def compute_total(items):\n    pass\n")
    with pytest.raises(ToolError, match="closest line is 1"):
        edit_file.handler("f.py", "def compute_totals(items):", "def total(items):")
