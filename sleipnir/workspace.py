"""Workspace root and path safety.

Every tool resolves paths against one root, the repository the harness
was started in. A path that resolves outside it (including through a
symlink) is refused.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Directories never worth showing a model or searching through.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".eggs",
    "dist",
    "build",
    "_build",
    "deps",
    ".elixir_ls",
    "target",
    ".sleipnir",
}


class ToolError(Exception):
    """A tool failure the model should read and act on."""


class Workspace:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        """Resolve a workspace-relative (or absolute) path, refusing escapes."""
        p = (self.root / path).resolve()
        if p != self.root and self.root not in p.parents:
            raise ToolError(f"{path} is outside the workspace root {self.root}")
        return p

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root))

    def skipped(self, p: Path) -> bool:
        return any(part in SKIP_DIRS for part in p.relative_to(self.root).parts)

    def git_visible(self) -> set[Path] | None:
        """The files git would show: tracked, plus untracked and not ignored.

        A hard-coded skip list cannot know that this repository ignores
        `App/DerivedData` or `.build`, so a search walked hundreds of
        build artifacts and the model had to work out on its own that
        `git ls-files` was the real answer. Git already knows; ask it.

        None when this is not a git checkout, or git is not usable here —
        then the skip list is all we have.
        """
        try:
            out = subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                cwd=self.root, capture_output=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        return {self.root / name.decode("utf-8", "replace") for name in out.stdout.split(b"\0") if name}

    def walk_files(self, start: Path, respect_gitignore: bool = True):
        """Yield files under start, depth-first and sorted.

        Ignored files are left out the way they are left out of `git
        status`; SKIP_DIRS covers whatever is not in a git checkout.
        """
        if start.is_file():
            yield start
            return
        visible = self.git_visible() if respect_gitignore else None
        for dirpath, dirnames, filenames in os.walk(start):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                f = Path(dirpath) / name
                if visible is not None and f not in visible:
                    continue
                yield f


def is_binary(p: Path, sniff: int = 8192) -> bool:
    try:
        with open(p, "rb") as f:
            return b"\0" in f.read(sniff)
    except OSError:
        return True
