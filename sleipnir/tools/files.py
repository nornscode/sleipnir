"""read_file, write_file, edit_file, rooted at the workspace."""

from __future__ import annotations

from norns import tool

from sleipnir import runtime
from sleipnir.tools.edit import apply_edit
from sleipnir.workspace import ToolError, is_binary

MAX_READ_CHARS = 60_000


@tool
def read_file(path: str, offset: int = 1, limit: int = 0) -> str:
    """Read a file in the workspace. Paths are relative to the workspace
    root. offset is the 1-based first line to return and limit the number
    of lines (0 for all). Large files are truncated; the tail of the
    output says where to continue from."""
    ws = runtime.workspace()
    p = ws.resolve(path)
    if not p.is_file():
        raise ToolError(f"{path} is not a file")
    if is_binary(p):
        raise ToolError(f"{path} is a binary file")

    lines = p.read_text(errors="replace").splitlines()
    total = len(lines)
    start = max(offset, 1) - 1
    end = total if limit <= 0 else min(total, start + limit)
    chunk = lines[start:end]

    out, used = [], 0
    for i, line in enumerate(chunk):
        used += len(line) + 1
        if used > MAX_READ_CHARS:
            end = start + i
            break
        out.append(line)

    text = "\n".join(out)
    if start > 0 or end < total:
        text += f"\n[lines {start + 1}-{end} of {total}"
        if end < total:
            text += f"; continue with offset={end + 1}"
        text += "]"
    return text if text else "(empty file)"


@tool(side_effect=True)
def write_file(path: str, content: str, approval: str = "") -> str:
    """Create or overwrite a file in the workspace, creating parent
    directories. Prefer edit_file for changes to an existing file. Leave
    approval empty unless a previous call asked for permission."""
    ws = runtime.workspace()
    p = ws.resolve(path)
    rel = ws.rel(p) if p != ws.root else "."
    runtime.permissions().check("write_file", rel, approval)
    if p.is_dir():
        raise ToolError(f"{path} is a directory")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {len(content)} chars to {rel}"


@tool(side_effect=True)
def edit_file(
    path: str, old_string: str, new_string: str, replace_all: bool = False, approval: str = ""
) -> str:
    """Replace old_string with new_string in a file. old_string must match
    exactly once; include enough surrounding lines to make it unique, or
    set replace_all to change every occurrence. Whitespace-only
    differences in indentation are tolerated. Leave approval empty
    unless a previous call asked for permission."""
    ws = runtime.workspace()
    p = ws.resolve(path)
    rel = ws.rel(p)
    runtime.permissions().check("edit_file", rel, approval)
    if not p.is_file():
        raise ToolError(f"{path} is not a file")
    text = p.read_text()
    new_text, n = apply_edit(text, old_string, new_string, replace_all)
    p.write_text(new_text)
    return f"edited {rel}: {n} replacement{'s' if n != 1 else ''}"
