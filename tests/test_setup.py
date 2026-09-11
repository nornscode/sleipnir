"""The wizard: what it stores, where, and what it refuses to do."""

import os
import stat

import pytest

from sleipnir import setup
from sleipnir.env import load_env


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway ~/.sleipnir, so a test never reads the real one."""
    monkeypatch.setenv("SLEIPNIR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(setup, "USER_ENV", tmp_path / "home" / "env")
    return tmp_path / "home" / "env"


def answers(monkeypatch, typed, secrets):
    it, sec = iter(typed), iter(secrets)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))
    monkeypatch.setattr(setup, "getpass", lambda *_: next(sec))


def test_configured_needs_both_keys(monkeypatch):
    monkeypatch.setenv("NORNS_API_KEY", "nrn_x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert setup.configured() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    assert setup.configured() is True
    monkeypatch.setenv("NORNS_API_KEY", "   ")
    assert setup.configured() is False


def test_run_stores_keys_privately(home, monkeypatch, capsys):
    for k in ("NORNS_API_KEY", "NORNS_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(setup, "interactive", lambda: True)
    monkeypatch.setattr(setup, "check", lambda url, key: (True, f"connected to {url}"))
    answers(monkeypatch, ["http://localhost:4000", "anthropic"], ["nrn_secret", "sk-ant-secret"])

    assert setup.run() == 0
    written = home.read_text()
    assert "NORNS_API_KEY=nrn_secret" in written
    assert "ANTHROPIC_API_KEY=sk-ant-secret" in written
    assert stat.S_IMODE(home.stat().st_mode) == 0o600
    # and applied to this process, so startup can carry straight on
    assert os.environ["NORNS_API_KEY"] == "nrn_secret"
    # never echoed back
    assert "nrn_secret" not in capsys.readouterr().out


def test_run_refuses_without_a_terminal(home, monkeypatch, capsys):
    monkeypatch.setattr(setup, "interactive", lambda: False)
    assert setup.run() == 1
    assert "not a terminal" in capsys.readouterr().err
    assert not home.exists()


def test_user_env_is_the_lowest_layer(home, tmp_path, monkeypatch):
    """A repository's own .env wins, so a checkout can point elsewhere."""
    for k in ("NORNS_URL", "NORNS_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("sleipnir.env.USER_ENV", home)
    home.parent.mkdir(parents=True, exist_ok=True)
    home.write_text("NORNS_URL=http://machine-wide\nNORNS_API_KEY=nrn_global\n")
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("NORNS_URL=http://this-repo\n")

    sources = load_env(root)
    assert os.environ["NORNS_URL"] == "http://this-repo"
    assert os.environ["NORNS_API_KEY"] == "nrn_global"
    assert sources["NORNS_URL"] == ".env"
    assert "sleip setup" in sources["NORNS_API_KEY"]


def test_mask_never_shows_a_whole_key():
    assert setup.mask("sk-ant-api03-abcdefghijklmnop") == "sk-ant…mnop"
    assert setup.mask("short") == "set"
