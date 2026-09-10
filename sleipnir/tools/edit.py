"""String replacement with a whitespace-tolerant fallback.

The model quotes a block to replace. Exact match first; failing that, a
line-based match that ignores trailing whitespace and a uniform
indentation shift, so a block copied from a file rendered at a
different indent still lands. Anything ambiguous fails with the
candidate line numbers rather than guessing.
"""

from __future__ import annotations

import difflib
import textwrap

from sleipnir.workspace import ToolError


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _normalise(lines: list[str]) -> str:
    return textwrap.dedent("\n".join(l.rstrip() for l in lines))


def _line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def apply_edit(text: str, old: str, new: str, replace_all: bool = False) -> tuple[str, int]:
    """Return (new_text, replacements) or raise ToolError."""
    if old == "":
        raise ToolError("old_string is empty; use write_file to create or overwrite a file")
    if old == new:
        raise ToolError("old_string and new_string are identical; nothing to do")

    count = text.count(old)
    if count == 1 or (count > 1 and replace_all):
        return text.replace(old, new), count
    if count > 1:
        lines = []
        start = 0
        while (i := text.find(old, start)) != -1:
            lines.append(_line_of_offset(text, i))
            start = i + 1
        shown = ", ".join(str(n) for n in lines[:10])
        raise ToolError(
            f"old_string matches {count} times (lines {shown}); include more surrounding "
            "context so it matches once, or pass replace_all=true"
        )

    return _fuzzy(text, old, new, replace_all)


def _fuzzy(text: str, old: str, new: str, replace_all: bool) -> tuple[str, int]:
    old_lines = old.split("\n")
    if old.endswith("\n"):
        old_lines = old_lines[:-1]
    text_lines = text.split("\n")
    k = len(old_lines)
    target = _normalise(old_lines)

    hits = [i for i in range(len(text_lines) - k + 1) if _normalise(text_lines[i : i + k]) == target]

    if not hits:
        hint = _closest(text_lines, old_lines[0])
        raise ToolError(f"old_string not found in file{hint}")
    if len(hits) > 1 and not replace_all:
        shown = ", ".join(str(i + 1) for i in hits[:10])
        raise ToolError(
            f"old_string matches {len(hits)} times after ignoring whitespace (lines {shown}); "
            "include more surrounding context so it matches once, or pass replace_all=true"
        )

    new_lines = new.split("\n")
    if new.endswith("\n") and new_lines[-1] == "":
        new_lines = new_lines[:-1]
    old_base = next((_leading_ws(l) for l in old_lines if l.strip()), "")

    out = text_lines
    for i in reversed(hits):
        window = out[i : i + k]
        shift = next((_leading_ws(l) for l in window if l.strip()), "")
        out = out[:i] + _reindent(new_lines, old_base, shift) + out[i + k :]
    return "\n".join(out), len(hits)


def _reindent(lines: list[str], base: str, shift: str) -> list[str]:
    result = []
    for l in lines:
        if not l.strip():
            result.append(l)
        elif l.startswith(base):
            result.append(shift + l[len(base) :])
        else:
            result.append(shift + l.lstrip())
    return result


def _closest(text_lines: list[str], first: str) -> str:
    needle = first.strip()
    if not needle:
        return ""
    candidates = {l.strip(): n for n, l in enumerate(text_lines, 1) if l.strip()}
    near = difflib.get_close_matches(needle, list(candidates), n=1, cutoff=0.6)
    if not near:
        return "; re-read the file and copy the block exactly"
    return f"; the closest line is {candidates[near[0]]}: {near[0]!r}. Re-read the file and copy the block exactly"
