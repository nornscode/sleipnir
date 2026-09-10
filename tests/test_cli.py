import pytest

from sleipnir import config
from sleipnir.cli import main
from sleipnir.permissions import PermissionRequired, Permissions, always_asks
from sleipnir.tools.files import write_file
from sleipnir.tools.shell import bash


def test_allow_add_list_remove(tmp_path, capsys):
    root = str(tmp_path)
    assert main(["--root", root, "allow", "list"]) == 0
    assert "(no rules" in capsys.readouterr().out
    assert main(["--root", root, "allow", "add", "bash", "git *"]) == 0
    assert main(["--root", root, "allow", "add", "bash", "git *"]) == 0
    assert "already present" in capsys.readouterr().out
    main(["--root", root, "allow", "list"])
    assert capsys.readouterr().out == "bash git *\n"
    assert main(["--root", root, "allow", "remove", "bash", "git *"]) == 0
    assert main(["--root", root, "allow", "remove", "bash", "git *"]) == 1
    assert (tmp_path / ".sleipnir" / "allow").read_text() == ""


def test_config_set_show_unset(tmp_path, capsys, monkeypatch):
    root = str(tmp_path)
    monkeypatch.delenv("SLEIPNIR_MODEL", raising=False)
    assert main(["--root", root, "config", "set", "model", "claude-opus-5"]) == 0
    assert main(["--root", root, "config", "set", "max_steps", "lots"]) == 1
    main(["--root", root, "config", "show"])
    out = capsys.readouterr().out
    assert "model = claude-opus-5  (file)" in out
    assert "max_steps = 200  (default)" in out
    monkeypatch.setenv("SLEIPNIR_MODEL", "from-env")
    assert config.resolve(tmp_path)["model"] == "from-env"
    assert config.resolve(tmp_path, {"model": "from-flag"})["model"] == "from-flag"
    assert main(["--root", root, "config", "unset", "model"]) == 0
    monkeypatch.delenv("SLEIPNIR_MODEL")
    assert config.resolve(tmp_path)["model"] == "claude-sonnet-5"


def test_docs_and_doctor(tmp_path, capsys, monkeypatch):
    assert main(["docs"]) == 0
    assert "# Sleipnir reference" in capsys.readouterr().out
    for k in ("NORNS_URL", "NORNS_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "NORNS_GARD"):
        monkeypatch.delenv(k, raising=False)
    assert main(["--root", str(tmp_path), "doctor"]) == 1
    out = capsys.readouterr().out
    assert "FAIL NORNS_URL is not set" in out and "problems found" in out


def test_self_configuration_always_asks(ws, allow):
    allow("bash sleipnir *", "bash git *", "bash true", "write_file *", "edit_file *")
    assert always_asks("bash", "git status && sleipnir allow add bash 'rm *'")
    assert not always_asks("bash", "sleipnir docs")
    assert always_asks("write_file", ".sleipnir/allow")
    with pytest.raises(PermissionRequired):
        bash.handler("sleipnir allow add bash 'rm *'")
    with pytest.raises(PermissionRequired):
        write_file.handler(".sleipnir/allow", "bash rm *")
    assert bash.handler("sleipnir docs 2>/dev/null; true").startswith("exit code: 0")


def test_always_never_adds_a_self_config_rule(tmp_path):
    from tests.test_permissions import _messages

    p = Permissions(tmp_path / "allow")
    with pytest.raises(PermissionRequired):
        p.check("bash", "sleipnir config set model x")
    token = next(iter(p.pending))
    p.observe(_messages(token, "always", subject="sleipnir config set model x"))
    p.check("bash", "sleipnir config set model x", approval=token)
    assert p.rules == []


def test_allow_file_edits_are_picked_up_live(tmp_path):
    p = Permissions(tmp_path / "allow")
    assert not p.allowed("bash", "git status")
    (tmp_path / "allow").write_text("bash git *\n")
    assert p.allowed("bash", "git status")


def test_bare_invocation_means_run(monkeypatch):
    calls = []
    monkeypatch.setattr("sleipnir.cli.cmd_start", lambda root, settings, *, mode, use_gard: calls.append((mode, use_gard, settings)) or 0)
    assert main(["--agent", "x", "--root", "."]) == 0
    assert calls[0][0] == "run" and calls[0][1] is True and calls[0][2]["agent"] == "x"
    assert main(["serve", "--no-gard"]) == 0
    assert calls[1][:2] == ("serve", False)
    assert main(["chat"]) == 0
    assert calls[2][0] == "chat"
