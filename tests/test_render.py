from sleipnir.render import event_lines, message_lines, session_label, text_of, title_of, tool_summary


def test_title_and_text():
    assert title_of({"first_message": "Fix the tests\nplease", "key": "k"}) == "Fix the tests"
    assert title_of({"first_message": None, "key": "sleipnir-1"}) == "sleipnir-1"
    assert title_of({"first_message": None, "summary": "Task: fix add\nmore", "key": "k"}) == "Task: fix add"
    assert title_of({"first_message": "x" * 60}).endswith("…")
    assert text_of({"$enc": "v1"}) == "[encrypted]"
    assert text_of({"a": 1}) == '{"a": 1}'


def test_session_label_status():
    s = {"id": 1, "first_message": "hi", "agent_name": "sleipnir", "status": "awaiting_tools", "gard_id": 7, "run": {}}
    label = session_label(s, {7: "laptop"})
    assert "◑" in label and "running tools" in label and "sleipnir @ laptop" in label
    # A parked run shows as needing you even when its process is idle.
    s = {"id": 1, "first_message": "hi", "agent_name": "a", "status": "stopped", "run": {"status": "waiting"}}
    assert "needs you" in session_label(s)


def test_tool_summary():
    assert tool_summary("bash", {"command": "git status"}) == "git status"
    assert tool_summary("edit_file", {"path": "a.py", "old_string": "x"}) == "a.py"
    assert tool_summary("grep", {"pattern": "def", "path": "lib"}) == "/def/ in lib"
    assert tool_summary("other", {"k": "v"}) == '{"k": "v"}'


def test_message_and_event_lines():
    assert message_lines({"role": "user", "content": "go [x]"}) == ["", "[b green]›[/] go \\[x]"]
    lines = message_lines({"role": "assistant", "content": "ok", "tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]})
    assert lines == ["", "ok", "[cyan]⚙ bash[/] ls"]
    assert message_lines({"role": "tool", "name": "bash", "content": "exit code: 0\nfiles", "is_error": True})[0].startswith("  [red]↳[/]")
    assert message_lines({"role": "tool", "name": "ask_human", "content": "yes"}) == ["", "[b green]›[/] yes"]
    assert message_lines({"role": "assistant", "content": "", "tool_calls": [{"name": "ask_human", "arguments": {"question": "Allow rm? [p-1]"}}]}) == ["", "[yellow b]? Allow rm? \\[p-1][/]"]
    assert message_lines({"role": "tool", "name": "bash", "content": "permission required (token p-1)\nbash: rm", "is_error": True}) == []
    assert message_lines({"role": "tool", "name": "wait", "kind": "timer_completed", "content": ""}) == ["  [dim]↳ timer_completed[/dim]"]

    assert event_lines("waiting_for_user", {"question": "Allow rm?"}) == ["", "[yellow b]? Allow rm?[/]"]
    assert event_lines("llm_response", {"content": "", "tool_calls": [{"name": "ask_human", "arguments": {"question": "q"}}]}) == []
    assert event_lines("tool_result", {"name": "ask_human", "content": "always"}) == ["", "[b green]›[/] always"]
    assert event_lines("tool_result", {"name": "bash", "content": "permission required (token p-2)\nbash: ls", "is_error": True}) == []
    assert event_lines("completed", {"output": "done\nmore"}) == ["", "done\nmore", "", "[green]✓ done[/green]"]
    assert event_lines("completed", {"output": ""}) == ["", "[green]✓ done[/green]"]
    assert event_lines("error", {"error": "boom"}) == ["[red]✗ boom[/red]"]
    assert event_lines("context_compacted", {"dropped": 7}) == ["[dim]… compacted 7 messages into the summary[/dim]"]
    assert event_lines("tool_result", {"name": "bash", "content": "exit code: 0"}) == ["  [dim]↳[/dim] [dim]bash: exit code: 0[/dim]"]
    assert event_lines("unknown", {}) == []


def test_space_label():
    from sleipnir.render import space_label

    label = space_label("laptop", [{"status": "awaiting_llm"}, {"status": "idle", "run": {"status": "waiting"}}])
    assert "●" in label and "laptop" in label and "2 sessions · 1 working · 1 need you" in label
    assert "○" in space_label("empty", [])


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
    assert run_event_lines(events) == [
        "[cyan]⚙ bash[/] ls",
        "  [dim]↳[/dim] [dim]bash: exit code: 0[/dim]",
        "[red]✗ boom[/red]",
    ]
