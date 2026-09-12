"""The agent's reference has to describe the harness it is actually in."""

import re

from sleipnir.app import HELP
from sleipnir.cli import SUBCOMMANDS, main
from sleipnir.docs import DOCS
from sleipnir.prompt import SYSTEM_PROMPT


def test_docs_name_every_subcommand():
    for command in SUBCOMMANDS:
        assert f"sleip {command}" in DOCS, command


def test_docs_name_every_slash_command():
    for slash in sorted(set(re.findall(r"^\s+(/\w+)", HELP, re.M))):
        assert slash in DOCS, slash


def test_docs_describe_the_client():
    for word in ("spaces", "sessions", "tree", "ctrl+n"):
        assert word in DOCS, word


def test_prompt_places_the_agent_in_the_client():
    for word in ("sleip", "spaces", "sessions", "sleip docs"):
        assert word in SYSTEM_PROMPT, word


def test_help_lists_the_commands(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "help"]) == 0
    out = capsys.readouterr().out
    for command in SUBCOMMANDS:
        assert command in out, command
