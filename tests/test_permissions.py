import re

import pytest

from sleipnir.permissions import (
    PermissionDenied,
    PermissionRequired,
    Permissions,
    Rule,
    classify,
    request_message,
    rule_for,
    shell_segments,
)


def test_shell_segments():
    assert shell_segments("git status && rm -rf build") == ["git status", "rm -rf build"]
    assert shell_segments("echo $(rm -rf /)") == ["echo $", "rm -rf /"]
    assert shell_segments("cat a | grep b; ls") == ["cat a", "grep b", "ls"]
    assert shell_segments('git commit -m "fix: a && b"') == ["git commit -m fix: a && b"]
    assert shell_segments("echo `rm -rf /`") == []


def test_rules_and_allowed(tmp_path):
    p = Permissions(tmp_path / "allow")
    p.add_rules([Rule.parse("bash git *"), Rule.parse("bash uv run pytest*")])
    assert p.allowed("bash", "git status")
    assert p.allowed("bash", "git status && uv run pytest -q")
    assert not p.allowed("bash", "git status && rm -rf build")
    assert not p.allowed("bash", "echo `rm -rf /`")
    assert p.allowed("read_file", "anything")
    assert not p.allowed("write_file", "x")
    # Persisted and reloaded.
    assert (tmp_path / "allow").read_text() == "bash git *\nbash uv run pytest*\n"
    assert Permissions(tmp_path / "allow").rules == p.rules


def test_rule_for():
    assert rule_for("write_file", "a/b") == [Rule("write_file", "*")]
    assert rule_for("bash", "git status && rm -rf x") == [
        Rule("bash", "git *"), Rule("bash", "git"), Rule("bash", "rm *"), Rule("bash", "rm"),
    ]


def test_classify():
    assert classify("yes") == "once"
    assert classify("  Yes, go ahead") == "once"
    assert classify("ok") == "once"
    assert classify("always") == "always"
    assert classify("Always allow git") == "always"
    assert classify("no") == "deny"
    assert classify("yesterday") == "deny"
    assert classify({"$enc": "v1"}) == "deny"


def _messages(token, answer, tool="bash", subject="rm -rf build", question=None):
    q = question if question is not None else f"Allow bash `rm -rf build`? (yes / always / no) [{token}]"
    return [
        {"role": "user", "content": "clean the build dir"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": tool, "arguments": {"command": subject}}]},
        {"role": "tool", "tool_call_id": "c1", "name": tool, "content": request_message(token, tool, subject)},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c2", "name": "ask_human", "arguments": {"question": q}}]},
        {"role": "tool", "tool_call_id": "c2", "name": "ask_human", "content": answer},
    ]


def test_approval_loop_once(tmp_path):
    p = Permissions(tmp_path / "allow")
    with pytest.raises(PermissionRequired) as exc:
        p.check("bash", "rm -rf build")
    token = next(iter(p.pending))
    assert f"(token {token})" in str(exc.value)

    # Retrying before the user answered is refused.
    with pytest.raises(PermissionDenied, match="no answer from the user"):
        p.check("bash", "rm -rf build", approval=token)

    p.observe(_messages(token, "yes"))
    p.check("bash", "rm -rf build", approval=token)  # proceeds
    # Using it twice is a fresh request for the same action, not a dead end:
    # a live token to quote is what the agent needs to make progress.
    with pytest.raises(PermissionRequired, match="already been used") as again:
        p.check("bash", "rm -rf build", approval=token)
    assert re.search(r"\(token (p-[0-9a-f]{6})\)", str(again.value)).group(1) != token
    assert p.rules == []


def test_approval_loop_always_adds_rules(tmp_path):
    p = Permissions(tmp_path / "allow")
    with pytest.raises(PermissionRequired):
        p.check("bash", "rm -rf build")
    token = next(iter(p.pending))
    p.observe(_messages(token, "always"))
    p.check("bash", "rm -rf build", approval=token)
    assert Rule("bash", "rm *") in p.rules
    p.check("bash", "rm -rf other")  # now allowed without asking


def test_approval_loop_deny(tmp_path):
    p = Permissions(tmp_path / "allow")
    with pytest.raises(PermissionRequired):
        p.check("bash", "rm -rf build")
    token = next(iter(p.pending))
    p.observe(_messages(token, "no"))
    with pytest.raises(PermissionDenied, match="declined"):
        p.check("bash", "rm -rf build", approval=token)


def test_token_bound_to_action_and_survives_restart(tmp_path):
    p = Permissions(tmp_path / "allow")
    with pytest.raises(PermissionRequired):
        p.check("bash", "rm -rf build")
    token = next(iter(p.pending))

    # A fresh worker learns the request and the answer from the messages.
    fresh = Permissions(tmp_path / "allow")
    fresh.observe(_messages(token, "yes"))

    # An answer covers the action it was asked about and no other. Running
    # something else with that token asks about *that* — the command the
    # user is about to be shown is the one that would actually run.
    with pytest.raises(PermissionRequired) as wrong:
        fresh.check("bash", "rm -rf /", approval=token)
    assert "rm -rf /" in str(wrong.value) and "different action" in str(wrong.value)
    reissued = re.search(r"\(token (p-[0-9a-f]{6})\)", str(wrong.value)).group(1)
    assert fresh.pending[reissued] == ("bash", "rm -rf /")

    fresh.check("bash", "rm -rf build", approval=token)

    with pytest.raises(PermissionRequired, match="not one this worker issued"):
        Permissions(tmp_path / "allow").check("bash", "rm -rf build", approval="p-000000")


def test_answer_without_token_in_question_is_ignored(tmp_path):
    p = Permissions(tmp_path / "allow")
    with pytest.raises(PermissionRequired):
        p.check("bash", "rm -rf build")
    token = next(iter(p.pending))
    p.observe(_messages(token, "yes", question="Shall I continue?"))
    with pytest.raises(PermissionDenied, match="no answer"):
        p.check("bash", "rm -rf build", approval=token)


def test_answer_binds_by_subject_when_token_is_dropped(tmp_path):
    p = Permissions(tmp_path / "allow")
    with pytest.raises(PermissionRequired):
        p.check("bash", "rm -rf build")
    token = next(iter(p.pending))
    p.observe(_messages(token, "always", question="Allow bash `rm -rf build`? (yes / always / no)"))
    p.check("bash", "rm -rf build", approval=token)
    assert Rule("bash", "rm *") in p.rules


def test_subject_binding_needs_a_unique_open_request(tmp_path):
    p = Permissions(tmp_path / "allow")
    for _ in range(2):
        with pytest.raises(PermissionRequired):
            p.check("bash", "rm -rf build")
    t1, t2 = list(p.pending)
    p.observe(_messages(t1, "yes", question="Allow bash `rm -rf build`?"))
    with pytest.raises(PermissionDenied, match="no answer"):
        p.check("bash", "rm -rf build", approval=t2)


def test_an_always_answer_is_honoured_even_if_the_agent_wanders_off(tmp_path):
    """What made the loop in the screenshot so bad: the agent asked about
    one command, then ran another, so the rule the user's "always" had
    earned was never written. They chose "always allow" and nothing was
    allowed — twice."""
    p = Permissions(tmp_path / "allow")
    with pytest.raises(PermissionRequired):
        p.check("bash", "ls -la")
    token = next(iter(p.pending))

    p.observe(_messages(token, "always"))
    # The rule exists on the strength of the answer alone; no retry needed.
    assert Rule("bash", "ls *") in p.rules
    p.check("bash", "ls -R")  # allowed, without asking


def test_a_stale_token_does_not_trap_the_agent_in_a_loop(tmp_path):
    """The whole failure, end to end: ask about one command, answer it,
    then attempt a different one. Two calls, not an unbounded loop."""
    p = Permissions(tmp_path / "allow")
    with pytest.raises(PermissionRequired):
        p.check("bash", "ls -la && find . | sort")
    first = next(iter(p.pending))
    p.observe(_messages(first, "yes"))

    with pytest.raises(PermissionRequired) as exc:
        p.check("bash", "find . -type d | wc -l", approval=first)
    second = re.search(r"\(token (p-[0-9a-f]{6})\)", str(exc.value)).group(1)

    p.observe(_messages(second, "yes"))
    p.check("bash", "find . -type d | wc -l", approval=second)  # proceeds


def test_auto_mode_is_the_allow_list_at_its_widest(tmp_path):
    """Not a new mechanism and not a flag in memory: rules on disk, which
    is how it reaches a worker in another process at all."""
    allow = tmp_path / "allow"
    p = Permissions(allow)
    assert p.auto() == "off"

    assert p.set_auto("edits") == "edits"
    p.check("edit_file", "lib/thing.py")       # no longer asks
    p.check("write_file", "lib/new.py")
    with pytest.raises(PermissionRequired):    # commands still do
        p.check("bash", "rm -rf build")

    assert p.set_auto("all") == "all"
    p.check("bash", "rm -rf build")
    assert p.auto() == "all"

    # A second process reads the level off the file, which is the point.
    assert Permissions(allow).auto() == "all"

    assert p.set_auto("off") == "off"
    assert Permissions(allow).auto() == "off"
    with pytest.raises(PermissionRequired):
        p.check("edit_file", "lib/thing.py")


def test_no_level_of_auto_lets_the_agent_widen_its_own_powers(tmp_path):
    """The floor under every level: an agent that could run `sleip allow
    add` unasked could grant itself anything."""
    p = Permissions(tmp_path / "allow")
    p.set_auto("all")

    with pytest.raises(PermissionRequired):
        p.check("bash", "sleip allow add bash *")
    with pytest.raises(PermissionRequired):
        p.check("write_file", ".sleipnir/allow")


def test_auto_off_clears_whichever_way_it_was_turned_on(tmp_path):
    p = Permissions(tmp_path / "allow")
    p.set_auto("all")
    p.set_auto("off")
    # "all" adds the edits rules too; off must take all of them back out.
    assert p.rules == []
