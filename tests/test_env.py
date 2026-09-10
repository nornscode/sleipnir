import json
import os

from sleipnir.env import direnv_export, load_env, parse_env_file


def test_parse_env_file():
    text = """
# comment
export NORNS_URL=http://x:4000
NORNS_API_KEY="nrn_a b"  # trailing
KEY2='single'
PLAIN=value # comment
BAD LINE
1BAD=x
EMPTY=
"""
    assert parse_env_file(text) == {
        "NORNS_URL": "http://x:4000",
        "NORNS_API_KEY": "nrn_a b",
        "KEY2": "single",
        "PLAIN": "value",
        "EMPTY": "",
    }


def test_load_env_precedence(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("A=dotenv\nB=dotenv\nC=dotenv\n")
    extra = tmp_path / "extra.env"
    extra.write_text("A=file\n")
    monkeypatch.setenv("C", "process")
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("B", raising=False)
    monkeypatch.delenv("DIRENV_DIR", raising=False)
    monkeypatch.setattr("sleipnir.env.direnv_export", lambda root: {"B": "direnv", "DIRENV_DIR": "x", "GONE": None})

    applied = load_env(tmp_path, extra)
    assert os.environ["A"] == "file" and os.environ["B"] == "direnv" and os.environ["C"] == "process"
    assert applied == {"A": str(extra), "B": ".envrc (direnv)"}
    assert "DIRENV_DIR" not in os.environ and "GONE" not in os.environ


def test_direnv_export_uses_direnv_when_present(tmp_path, monkeypatch):
    (tmp_path / ".envrc").write_text("export X=1\n")
    monkeypatch.setattr("sleipnir.env.shutil.which", lambda name: "/usr/bin/direnv")

    class Proc:
        returncode = 0
        stdout = json.dumps({"X": "1"})

    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        return Proc()

    monkeypatch.setattr("sleipnir.env.subprocess.run", run)
    assert direnv_export(tmp_path) == {"X": "1"}
    assert seen["cmd"] == ["direnv", "export", "json"] and seen["cwd"] == tmp_path

    monkeypatch.setattr("sleipnir.env.shutil.which", lambda name: None)
    assert direnv_export(tmp_path) == {}
