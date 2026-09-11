import pytest

from sleipnir import runtime


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Never read or write the developer's own ~/.sleipnir.

    `sleip setup` stores keys machine-wide and load_env reads them, so
    without this a test would see whoever is running it.
    """
    home = tmp_path_factory.mktemp("sleipnir-home")
    monkeypatch.setenv("SLEIPNIR_HOME", str(home))
    monkeypatch.setattr("sleipnir.env.SLEIPNIR_HOME", home)
    monkeypatch.setattr("sleipnir.env.USER_ENV", home / "env")
    monkeypatch.setattr("sleipnir.setup.USER_ENV", home / "env")
    monkeypatch.setattr("sleipnir.gard.STORE", home / "gards.json")
    return home


@pytest.fixture
def ws(tmp_path):
    """A configured workspace in tmp_path with an empty allow list."""
    runtime.configure(tmp_path)
    return tmp_path


@pytest.fixture
def allow(ws):
    """Add allow rules to the workspace's permission set."""

    def _allow(*lines):
        from sleipnir.permissions import Rule

        runtime.permissions().add_rules([Rule.parse(l) for l in lines])

    return _allow
