import pytest

from sleipnir import runtime


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
