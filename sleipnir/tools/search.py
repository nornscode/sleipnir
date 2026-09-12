"""grep and glob over the workspace."""

from __future__ import annotations

import fnmatch
import re

from norns import tool

from sleipnir import runtime
from sleipnir.workspace import ToolError, is_binary

MAX_FILE_BYTES = 2_000_000
MAX_LINE_CHARS = 240
MAX_GLOB_RESULTS = 500


@tool
def grep(
    pattern: str, path: str = ".", include: str = "", ignore_case: bool = False, max_results: int = 200
) -> str:
    """Search file contents with a regular expression. path is a file or
    directory (relative to the workspace root); include filters file
    names with a glob such as "*.ex". Output is path:line:text. Files the
    repository ignores are left out, as they are from `git status`."""
    ws = runtime.workspace()
    start = ws.resolve(path)
    if not start.exists():
        raise ToolError(f"{path} does not exist")
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        raise ToolError(f"invalid regular expression: {e}") from e

    limit = max(1, min(max_results, 1000))
    hits: list[str] = []
    files = 0
    for f in ws.walk_files(start):
        if ws.skipped(f):
            continue
        if include and not fnmatch.fnmatchcase(f.name, include):
            continue
        try:
            if f.stat().st_size > MAX_FILE_BYTES or is_binary(f):
                continue
            text = f.read_text(errors="replace")
        except OSError:
            continue
        files += 1
        for n, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                shown = line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + "..."
                hits.append(f"{ws.rel(f)}:{n}:{shown}")
                if len(hits) >= limit:
                    hits.append(f"[stopped at {limit} matches; narrow the pattern or path]")
                    return "\n".join(hits)
    if not hits:
        return f"(no matches in {files} files)"
    return "\n".join(hits)


@tool
def glob(pattern: str, path: str = ".") -> str:
    """Find files by name pattern, such as "**/*.py" or "lib/**/process*.ex",
    under a directory relative to the workspace root. Files the repository
    ignores are left out, as they are from `git status`."""
    ws = runtime.workspace()
    start = ws.resolve(path)
    if not start.is_dir():
        raise ToolError(f"{path} is not a directory")
    visible = ws.git_visible()
    out: list[str] = []
    for p in sorted(start.glob(pattern)):
        if not p.is_file() or ws.skipped(p):
            continue
        if visible is not None and p not in visible:
            continue
        out.append(ws.rel(p))
        if len(out) >= MAX_GLOB_RESULTS:
            out.append(f"[stopped at {MAX_GLOB_RESULTS} files; narrow the pattern]")
            break
    return "\n".join(out) if out else "(no matches)"
