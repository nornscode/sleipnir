"""The team in the client: a helper's work and questions show in the
session that launched it, and its conversation is not a session."""

import pytest
from textual.widgets import RichLog

from sleipnir.render import helper_label, is_helper_session, tool_result_lines, tool_summary
from sleipnir.widgets import PermissionPrompt, Prompt
from tests.test_app import FakeApi, log_text, make_app, session_ids_under, show


class TeamApi(FakeApi):
    def __init__(self):
        super().__init__()
        self.run_rows: dict[int, dict] = {}

    async def run(self, run_id):
        return self.run_rows.get(run_id, {"id": run_id, "conversation_id": 1})

    async def agents(self):
        return [{"id": 5, "name": "sleipnir"}, {"id": 6, "name": "sleipnir-explore"},
                {"id": 7, "name": "sleipnir-code"}, {"id": 8, "name": "my-agent"}]


QUESTION = "Allow bash `make build`? (yes / always / no) [p-cd34ef]"


@pytest.mark.asyncio
async def test_a_helpers_work_and_question_show_in_the_session_that_launched_it():
    api = TeamApi()
    # Session 1's run 9 launched the coder, whose run is 41.
    api.run_rows[41] = {"id": 41, "agent_id": 7, "parent_run_id": 9, "status": "running"}
    app, api = make_app(api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        assert {6, 7} <= set(app.stream.joined)
        key = await show(app, 1)
        tab = app.tabs[key]

        await app.on_agent_event(7, "agent_started", {"run_id": 41})
        await app.on_agent_event(7, "llm_response", {"run_id": 41, "content": "Building now.", "tool_calls": [
            {"id": "c1", "name": "bash", "arguments": {"command": "make build"}}]})
        await app.on_agent_event(7, "tool_result", {"run_id": 41, "name": "bash", "is_error": True,
                                                    "content": "permission required (token p-cd34ef)\nbash: make build\n\nAsk the user."})
        await app.on_agent_event(7, "waiting_for_user", {"run_id": 41, "question": QUESTION})
        await pilot.pause(0.1)

        text = log_text(app.query_one("#log-1", RichLog))
        assert "code ⚙ bash make build" in text
        assert "code asks you" in text
        # What the helper concluded arrives as the launch's result; its
        # thinking aloud is not the session's.
        assert "Building now." not in text
        assert tab.question_run == 41
        assert app.query_one(PermissionPrompt).display

        # The session's own run is not waiting — it is waiting on the coder —
        # and a poll must not take the coder's question away.
        await app._sync_tabs()
        assert tab.question == QUESTION and tab.question_run == 41

        await app.on_prompt_submitted(Prompt.Submitted("y"))
        assert ("reply", 41, "yes") in api.calls
        assert tab.question is None and tab.question_run is None

        await app.on_agent_event(7, "completed", {"run_id": 41, "output": "Built."})
        await pilot.pause(0.1)
        assert "code ✓ done" in log_text(app.query_one("#log-1", RichLog))


@pytest.mark.asyncio
async def test_a_helper_conversation_is_not_a_session_but_its_question_is_the_sessions():
    api = TeamApi()
    api.session_list.append({
        "id": 60, "key": "subagent:1", "agent_id": 7, "agent_name": "sleipnir-code", "gard_id": 3, "status": "waiting",
        "first_message": "make the change",
        "run": {"id": 41, "status": "waiting", "parent_run_id": 9, "waiting_for": {"question": QUESTION}},
    })
    app, api = make_app(api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        assert 60 not in session_ids_under(app, 3)
        assert 1 in session_ids_under(app, 3)
        # The session the coder works for is the one that needs you.
        assert app.sessions[1].get("helper_waiting")

        key = await show(app, 1)
        await app._sync_tabs()
        await pilot.pause(0.1)
        tab = app.tabs[key]
        assert tab.question == QUESTION and tab.question_run == 41
        assert "code asks you" in log_text(app.query_one("#log-1", RichLog))

        await app.on_prompt_submitted(Prompt.Submitted("no"))
        assert ("reply", 41, "no") in api.calls
        # Norns has not caught up yet: the next poll must not ask again.
        await app._sync_tabs()
        assert tab.question is None


@pytest.mark.asyncio
async def test_reopening_a_session_finds_a_helper_already_waiting():
    api = TeamApi()
    api.session_list[1]["run"] = {"id": 9, "status": "running", "waiting_for": None}
    api.run_rows[41] = {"id": 41, "agent_id": 7, "parent_run_id": 9, "status": "waiting", "waiting_for": {"question": QUESTION}}
    launched = [{"event_type": "subagent_launched", "payload": {"child_run_id": "41", "child_agent_name": "sleipnir-code"}}]

    async def run_events(run_id):
        return launched if run_id == 9 else []

    api.run_events = run_events
    app, api = make_app(api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        key = await show(app, 1)
        tab = app.tabs[key]
        assert tab.question_run == 41
        assert app.helper_runs[41] == (1, "code")


def test_helper_names_and_launches_read_as_the_team():
    assert helper_label("sleipnir-explore") == "explore"
    assert helper_label("mine-code") == "code"
    assert helper_label("my-agent") == "my-agent"
    assert is_helper_session({"key": "subagent_c1_42"}) and is_helper_session({"key": "subagent:7"})
    assert not is_helper_session({"key": "sleipnir-20260914-101500"})
    assert tool_summary("launch_agent", {"agent_name": "sleipnir-explore", "message": "Where is auth checked?\nList files."}) \
        == "explore: Where is auth checked?"
    # A helper's report shows as what it said, not as the name of its kind.
    [line] = tool_result_lines("launch_agent", "Auth is checked in lib/auth.ex:40.", "subagent_completed")
    assert "lib/auth.ex:40" in line
    assert "subagent_busy" in tool_result_lines("launch_agent", "", "subagent_busy")[0]


def test_a_helpers_change_says_whose_it_is():
    from sleipnir.render import helper_event_lines

    diff = "README.md  +1 -0\n@@ -1,1 +1,2 @@\n # Sleipnir\n+a line"
    lines = helper_event_lines("code", "tool_result", {"name": "edit_file", "content": diff})
    assert lines[0].startswith("  [magenta]code[/magenta] ") and "README.md" in lines[0]
    assert all("[magenta]code" not in line for line in lines[1:])
