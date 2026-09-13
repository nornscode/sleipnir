"""What a change actually was.

A tool result that says "edited lib/thing.py: 1 replacement" asks you to
trust an edit you never saw. The diff is the thing worth putting in the
transcript, and the worker is the only place that holds both versions of
the file — so it makes one here, and the client colours it.

The model reads this result too, which is a feature (it confirms what
landed, and catches an edit that matched somewhere unintended) and a cost
in tokens, which is why it is capped.
"""

from __future__ import annotations

import difflib

# Enough to read a real change; past this the transcript and the next
# prompt both stop being about the code.
MAX_DIFF_LINES = 160
CONTEXT = 3


def unified(before: str, after: str, path: str, context: int = CONTEXT) -> str:
    """A unified diff with no file header — the caller's first line says
    which file it is, and repeating it is noise."""
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            lineterm="",
            n=context,
        )
    )
    # difflib's first two lines are the --- / +++ header.
    return "\n".join(lines[2:])


def counts(diff: str) -> tuple[int, int]:
    """(added, removed), ignoring the hunk headers."""
    added = sum(1 for l in diff.splitlines() if l.startswith("+"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-"))
    return added, removed


def cap(diff: str, limit: int = MAX_DIFF_LINES) -> str:
    lines = diff.splitlines()
    if len(lines) <= limit:
        return diff
    return "\n".join(lines[:limit] + [f"… {len(lines) - limit} more diff lines"])


def summary(path: str, before: str, after: str, note: str = "") -> str:
    """The tool result for a change: what happened, then the diff itself.

    The shape is fixed because the client reads it back — first line is
    prose, the rest is a diff.
    """
    diff = unified(before, after, path)
    if not diff.strip():
        return f"{path}: no change"
    added, removed = counts(diff)
    head = f"{path}  +{added} -{removed}"
    if note:
        head += f"  ({note})"
    return head + "\n" + cap(diff)


def split(content: str) -> tuple[str, list[str]]:
    """A result back into (first line, diff lines), or (content, []) when
    it is not one of ours. A diff is recognised by its hunk headers, which
    ordinary tool output does not have at the start of a line."""
    lines = content.splitlines()
    if len(lines) < 2:
        return content, []
    body = lines[1:]
    if not any(l.startswith("@@") for l in body[:2]):
        return content, []
    return lines[0], body
