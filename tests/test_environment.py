import json
import os
from types import SimpleNamespace

import pytest

from sleipnir import environment
from sleipnir.cli import main


@pytest.fixture
def export(monkeypatch):
    monkeypatch.setattr(environment.shutil, "which", lambda name: "/bin/direnv")
    def configure(values, code=0):
        def run(args, **kwargs):
            assert args == ["/bin/direnv", "export", "json"]
            return SimpleNamespace(returncode=code, stdout=values, stderr="secret")
        monkeypatch.setattr(environment.subprocess, "run", run)
    return configure


def test_export_and_unset(tmp_path, monkeypatch, export):
    monkeypatch.setenv("PROJECT_TEST", "old")
    monkeypatch.setenv("REMOVED_TEST", "old")
    export(json.dumps({"PROJECT_TEST": "hello\nworld", "REMOVED_TEST": None}))
    environment.load(tmp_path)
    assert os.environ["PROJECT_TEST"] == "hello\nworld"
    assert "REMOVED_TEST" not in os.environ


@pytest.mark.parametrize("output,code", [("{}", 1), ("oops", 0), ('{"X": 3}', 0), ("[]", 0)])
def test_failed_export_does_not_leak_output(tmp_path, export, output, code):
    export(output, code)
    with pytest.raises(ValueError) as error:
        environment.load(tmp_path)
    assert "secret" not in str(error.value)


def test_missing_direnv(tmp_path, monkeypatch):
    monkeypatch.setattr(environment.shutil, "which", lambda name: None)
    environment.load(tmp_path)
    (tmp_path / ".envrc").write_text("export X=y")
    child = tmp_path / "child"
    child.mkdir()
    with pytest.raises(ValueError, match="not installed"):
        environment.load(child)


def test_start_loads_selected_root_before_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEIPNIR_MODEL", "inherited")
    def load(root):
        assert root == tmp_path
        monkeypatch.setenv("SLEIPNIR_MODEL", "project")
    monkeypatch.setattr(environment, "load", load)
    calls = []
    monkeypatch.setattr("sleipnir.cli.cmd_start", lambda root, settings, **kw: calls.append(settings) or 0)
    assert main(["--root", str(tmp_path), "serve"]) == 0
    assert calls[-1]["model"] == "project"
    assert main(["--root", str(tmp_path), "serve", "--model", "flag"]) == 0
    assert calls[-1]["model"] == "flag"
