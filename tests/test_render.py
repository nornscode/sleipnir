from sleipnir.render import (
    Md,
    archived_lines,
    event_lines,
    message_lines,
    session_row,
    space_row,
    text_of,
    title_of,
    tool_summary,
)


def test_title_and_text():
    assert title_of({"first_message": "Fix the tests\nplease", "key": "k"}) == "Fix the tests"
    assert title_of({"first_message": None, "key": "sleipnir-1"}) == "sleipnir-1"
    assert title_of({"first_message": None, "summary": "Task: fix add\nmore", "key": "k"}) == "Task: fix add"
    assert title_of({"first_message": "x" * 60}).endswith("…")
    assert text_of({"$enc": "v1"}) == "[encrypted]"
    assert text_of({"a": 1}) == '{"a": 1}'


def test_session_row_status():
    working = session_row({"id": 1, "first_message": "hi", "status": "awaiting_tools", "run": {}})
    assert "hi" in working and "cyan" in working
    # A parked run shows as needing you even when its process is idle.
    parked = session_row({"id": 1, "first_message": "hi", "status": "stopped", "run": {"status": "waiting"}})
    assert "yellow" in parked
    # A quiet session is not coloured at all, so the two that want the eye
    # are the only two that get it.
    quiet = session_row({"id": 1, "first_message": "hi", "status": "idle", "run": {}})
    assert "cyan" not in quiet and "yellow" not in quiet
    # Long titles are cut to fit a sidebar, not wrapped.
    assert session_row({"first_message": "x" * 40}).endswith("…")


def test_tool_summary():
    assert tool_summary("bash", {"command": "git status"}) == "git status"
    assert tool_summary("edit_file", {"path": "a.py", "old_string": "x"}) == "a.py"
    assert tool_summary("grep", {"pattern": "def", "path": "lib"}) == "/def/ in lib"
    assert tool_summary("other", {"k": "v"}) == '{"k": "v"}'


def test_message_and_event_lines():
    assert message_lines({"role": "user", "content": "go [x]"}) == ["", "[b green]›[/] go \\[x]"]
    lines = message_lines({"role": "assistant", "content": "ok", "tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]})
    assert lines == ["", Md("ok"), "[cyan]⚙ bash[/] ls"]
    assert message_lines({"role": "tool", "name": "bash", "content": "exit code: 0\nfiles", "is_error": True})[0].startswith("  [red]↳[/]")
    assert message_lines({"role": "tool", "name": "ask_human", "content": "yes"}) == ["", "[b green]›[/] yes"]
    assert message_lines({"role": "assistant", "content": "", "tool_calls": [{"name": "ask_human", "arguments": {"question": "Allow rm? [p-1]"}}]}) == ["", "[yellow b]? Allow rm? \\[p-1][/]"]
    assert message_lines({"role": "tool", "name": "bash", "content": "permission required (token p-1)\nbash: rm", "is_error": True}) == []
    assert message_lines({"role": "tool", "name": "wait", "kind": "timer_completed", "content": ""}) == ["  [dim]↳ timer_completed[/dim]"]

    assert event_lines("waiting_for_user", {"question": "Allow rm?"}) == ["", "[yellow b]? Allow rm?[/]"]
    assert event_lines("llm_response", {"content": "", "tool_calls": [{"name": "ask_human", "arguments": {"question": "q"}}]}) == []
    assert event_lines("tool_result", {"name": "ask_human", "content": "always"}) == ["", "[b green]›[/] always"]
    assert event_lines("tool_result", {"name": "bash", "content": "permission required (token p-2)\nbash: ls", "is_error": True}) == []
    completed = event_lines("completed", {"output": "done\nmore"})
    assert completed[:3] == ["", Md("done\nmore"), ""]
    assert str(completed[3]) == "✓ done"          # a Text now: it can carry a link
    bare = event_lines("completed", {"output": ""})
    assert bare[0] == "" and str(bare[1]) == "✓ done"
    assert str(event_lines("error", {"error": "boom"})[0]) == "✗ boom"
    assert event_lines("context_compacted", {"dropped": 7}) == ["[dim]… compacted 7 messages into the summary[/dim]"]
    assert event_lines("tool_result", {"name": "bash", "content": "exit code: 0"}) == ["  [dim]↳[/dim] [dim]bash: exit code: 0[/dim]"]
    assert event_lines("unknown", {}) == []


def test_a_space_and_a_session_do_not_look_alike():
    """Outlined geometry could not carry this: ▢ beside ○ is one small
    hollow shape beside another. The icon names the kind, and it is the
    same icon whatever the row is doing."""
    busy_space = space_row("laptop", [{"status": "awaiting_llm"}])
    quiet_space = space_row("empty", [])
    broken_space = space_row("laptop", [], "pending", here=True)
    session = session_row({"first_message": "hi", "status": "awaiting_llm"})

    assert all("📁" in row for row in (busy_space, quiet_space, broken_space))
    assert "💬" in session
    assert "📁" not in session and "💬" not in busy_space

    assert "laptop" in busy_space and "1 working" in busy_space
    waiting = space_row("laptop", [{"status": "idle", "run": {"status": "waiting"}}])
    assert "1 need you" in waiting


def test_permission_prompt_from_the_workers_request():
    from sleipnir.render import expand_answer, permission_details, question_lines

    request = "permission required (token p-372a2a)\nbash: ls -la\n\nThis action is not in the allow list."
    assert permission_details(request) == ("p-372a2a", "bash", "ls -la")
    known = {"p-372a2a": ("bash", "ls -la")}
    lines = question_lines("Allow bash `ls -la`? (yes / always / no) [p-372a2a]", known)
    assert lines[1] == "[yellow b]⚠ bash wants to run[/]" and lines[2] == "[yellow]    ls -la[/]"
    assert not any("p-372a2a" in l for l in lines)
    # The model's wording alone is enough when the request was not seen.
    assert question_lines("Allow edit_file `calc.py`? (yes / always / no) [p-000000]")[1] == "[yellow b]⚠ edit_file wants to run[/]"
    # A free-form question stays a question.
    assert question_lines("Which branch should I use?") == ["", "[yellow b]? Which branch should I use?[/]"]
    assert expand_answer("a") == "always" and expand_answer("Y") == "yes" and expand_answer("use main") == "use main"


def test_run_event_lines_replays_a_run_in_flight():
    from sleipnir.render import run_event_lines

    events = [
        {"event_type": "run_started", "payload": {}},
        {"event_type": "llm_response", "payload": {"content": "old", "tool_calls": []}},
        {"event_type": "context_compacted", "payload": {"dropped": 3}},
        {"event_type": "llm_response", "payload": {"content": "", "tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]}},
        {"event_type": "tool_result", "payload": {"name": "bash", "content": "exit code: 0"}},
        {"event_type": "run_failed", "payload": {"error": "boom", "error_class": "x"}},
    ]
    replayed = run_event_lines(events)
    # The tool call is still markup; the ending is a Text, so it can link.
    assert replayed[0] == "[cyan]⚙ bash[/] ls"
    assert replayed[1] == "  [dim]↳[/dim] [dim]bash: exit code: 0[/dim]"
    assert str(replayed[2]) == "✗ boom"


def test_spaces_lines():
    from sleipnir.render import spaces_lines

    gards = [{"id": 3, "name": "laptop", "status": "ready"}, {"id": 4, "name": "server", "status": "disconnected"}]
    sessions = [{"gard_id": 3, "status": "awaiting_llm", "run": {}}, {"gard_id": None, "status": "idle", "run": {"status": "waiting"}}]
    lines = spaces_lines(gards, sessions, here=3)
    assert "laptop" in lines[2] and "worker connected" in lines[2] and "1 session, 1 working" in lines[2] and "this checkout" in lines[2]
    assert "server" in lines[3] and "worker gone" in lines[3] and "0 sessions" in lines[3]
    assert "no gard" in lines[4] and "1 session" in lines[4]


def test_a_turn_cut_off_at_the_limit_says_so():
    """The run no longer fails on it, so the transcript is the only place
    the user could learn their answer stops mid-thought."""
    from sleipnir.render import event_lines

    cut = event_lines("llm_response", {"content": "Here is the first half of the fi", "finish_reason": "length"})
    assert any("cut off" in str(line) for line in cut)
    assert any("max_tokens" in str(line) for line in cut)

    whole = event_lines("llm_response", {"content": "all of it", "finish_reason": "stop"})
    assert not any("cut off" in str(line) for line in whole)


def test_a_run_is_something_you_can_click_through_to():
    """The transcript is a summary; the run page is the whole log."""
    from sleipnir import render

    render.set_web_base("http://localhost:4000/")
    try:
        def clicks(lines):
            """The click actions Textual will run, one per linked span."""
            out = []
            for line in lines:
                for span in getattr(line, "spans", []):
                    meta = getattr(span.style, "meta", None) or {}
                    if meta.get("@click"):
                        out.append(meta["@click"])
            return out

        done = render.event_lines("completed", {"output": "", "run_id": 42})
        assert str(done[1]) == "✓ done  run 42"
        assert clicks(done) == ["app.open_url('http://localhost:4000/runs/42')"]

        failed = render.event_lines("error", {"error": "boom", "run_id": 7})
        assert clicks(failed) == ["app.open_url('http://localhost:4000/runs/7')"]

        started = render.event_lines("agent_started", {"run_id": 9})
        assert clicks(started) == ["app.open_url('http://localhost:4000/runs/9')"]
    finally:
        render.set_web_base("")

    # Without a dashboard to point at, it is still readable text.
    plain = render.event_lines("completed", {"output": "", "run_id": 42})
    assert str(plain[1]) == "✓ done  run 42"
    assert not [s for s in plain[1].spans if (getattr(s.style, "meta", None) or {}).get("@click")]


def test_the_archive_lists_what_you_can_get_back():
    lines = "\n".join(archived_lines([
        {"id": 41, "first_message": "try the other approach", "agent_name": "sleipnir", "archived_at": "2026-09-11T18:04:00Z"},
    ]))
    assert "41" in lines
    assert "try the other approach" in lines
    assert "2026-09-11" in lines
    # The way back has to be on screen: an id alone is not a way back.
    assert "/restore" in lines


def test_an_empty_archive_says_how_to_fill_it():
    lines = "\n".join(archived_lines([]))
    assert "nothing archived" in lines
    assert "/archive" in lines


def test_a_space_with_no_worker_says_so_instead_of_looking_busy():
    """The bug this fixes: a space nothing could serve rendered exactly
    like a healthy one, and even claimed a session was working."""
    sessions = [{"id": 1, "status": "running", "run": {}}]

    fine = space_row("missive", sessions, "ready")
    assert "working" in fine
    assert "no worker" not in fine

    broken = space_row("missive", sessions, "pending", here=True)
    assert "no worker" in broken
    # It must stop claiming work is happening — nothing can be.
    assert "working" not in broken
    # The remedy, where the remedy exists.
    assert "/start" in broken


def test_a_space_whose_checkout_is_elsewhere_offers_no_false_remedy():
    away = space_row("laptop", [], "disconnected", here=False)
    assert "no worker" in away
    assert "/start" not in away
    assert "elsewhere" in away
