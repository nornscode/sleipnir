"""Sleipnir: a coding harness worker for Norns."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sleipnir")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"
