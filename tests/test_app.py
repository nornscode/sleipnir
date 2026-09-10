"""The client against a fake Norns: spaces in the sidebar, a space's
sessions as tabs, sending, answering a question, forking, new sessions."""

from pathlib import Path

import pytest
from textual.widgets import Input, ListView, RichLog, TabbedContent

from sleipnir.app import SleipnirApp, SpaceItem
from sleipnir.widgets import PermissionPrompt


class FakeApi:
    url = "http://norns.test"
    api_key = "k"

    def __init__(self):
        self.calls = []
        self.session_list = [
            {"id": 2, "key": "run_2", "agent_id": 5, "agent_name": "sleipnir", "gard_id": 3, "status": "waiting",
             "first_message": None, "run": {"id": 12, "status": "waiting", "trigger_type": "message", "input": {"user_message": "add a flag"},
                                            "waiting_for": {"question": "Allow bash `rm -rf build`? (yes / always / no) [p-ab12cd]"}}},
            {"id": 1, "key": "run_1", "agent_id": 5, "agent_name": "sleipnir", "gard_id": 3, "status": "idle",
             "first_message": "fix the tests", "run": {"id": 9, "status": "completed", "waiting_for": None}},
            {"id": 7, "key": "run_7", "agent_id": 8, "agent_name": "my-agent", "gard_id": None, "status": "idle",
             "first_message": "Hello! What can you do?", "run": {"id": 30, "status": "completed", "waiting_for": None}},
        ]

    async def sessions(self, limit=100):
        return list(self.session_list)

    async def session(self, session_id):
        s = next(s for s in self.session_list if s["id"] == session_id)
        messages = [{"role": "user", "content": s["first_message"]}, {"role": "assistant", "content": "on it"}]
        if session_id == 2:
            messages = []
        return {**s, "messages": messages}

    async def agents(self):
        return [{"id": 5, "name": "sleipnir"}, {"id": 8, "name": "my-agent"}]

    async def gards(self):
        return [{"id": 3, "name": "laptop", "status": "ready"}]

    async def send_message(self, agent_id, content, *, conversation_key=None, gard_id=None):
        self.calls.append(("send", agent_id, content, conversation_key, gard_id))
        return 20

    async def reply(self, run_id, answer):
        self.calls.append(("reply", run_id, answer))

    async def fork(self, run_id, step, message=None):
        self.calls.append(("fork", run_id, step, message))
        return {"run_id": 30, "agent_id": 5}

    async def run(self, run_id):
        return {"id": run_id, "conversation_id": 1}

    async def run_events(self, run_id):
        return [
            {"event_type": "run_started", "payload": {}},
            {"event_type": "llm_request", "payload": {"messages": []}},
            {"event_type": "llm_response", "payload": {"content": "Looking.", "tool_calls": [{"id": "c1", "name": "bash", "arguments": {"command": "rm -rf build"}}], "step": 1}},
            {"event_type": "tool_call", "payload": {"tool_call_id": "c1", "name": "bash"}},
            {"event_type": "tool_result", "payload": {"tool_call_id": "c1", "name": "bash", "is_error": True,
                                                       "content": "permission required (token p-ab12cd)\nbash: rm -rf build\n\nAsk the user."}},
            {"event_type": "waiting_for_user", "payload": {"question": "Allow bash `rm -rf build`? (yes / always / no) [p-ab12cd]"}},
        ]

    async def delete_session(self, agent_id, key):
        self.calls.append(("delete", agent_id, key))
        self.session_list = [s for s in self.session_list if s["key"] != key]

    async def close(self):
        pass


class FakeStream:
    def __init__(self):
        self.joined = []

    def start(self):
        pass

    async def stop(self):
        pass

    async def join(self, agent_id):
        if agent_id not in self.joined:
            self.joined.append(agent_id)


def log_text(log: RichLog) -> str:
    return "\n".join(strip.text for strip in log.lines)


def make_app(api=None):
    api = api or FakeApi()
    return SleipnirApp(api, agent_name="sleipnir", gard_id=3, root=Path("/tmp/repo"), stream=FakeStream(), poll_seconds=60), api


@pytest.mark.asyncio
async def test_spaces_tabs_send_reply_and_fork():
    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        sidebar = app.query_one("#sidebar", ListView)
        items = list(sidebar.query(SpaceItem))
        # This checkout's space first, the no-gard bucket last.
        assert [i.space.name for i in items] == ["laptop", "no gard"]
        assert app.current_space == 3 and app.agent_id == 5

        # The tabs are this space's sessions, oldest on the left; the newest is active and loaded.
        tabs = app.query_one("#tabs", TabbedContent)
        assert [p.id for p in tabs.query("TabPane")] == ["s1", "s2"]
        assert tabs.active == "s2"
        assert app.stream.joined == [5]
        assert app.tabs["s2"].question.startswith("Allow bash `rm -rf build`")
        log2 = app.query_one("#log-2", RichLog)
        # The run in flight is replayed from its log: the message, the model's
        # turn, and the permission request as a prompt, without the token.
        assert "add a flag" in log_text(log2) and "Looking." in log_text(log2)
        assert app.tabs["s2"].title == "add a flag"
        assert "bash wants to run" in log_text(log2) and "rm -rf build" in log_text(log2)
        assert "p-ab12cd" not in log_text(log2)

        # The parked session shows the selector, focused; a key answers it.
        selector = app.query_one(PermissionPrompt)
        assert selector.display and (selector.tool, selector.subject) == ("bash", "rm -rf build")
        assert app.focused is not None and app.focused.id == "perm-options"
        await pilot.press("down", "enter")
        await pilot.pause()
        assert api.calls[-1] == ("reply", 12, "always")
        assert app.tabs["s2"].question is None
        assert not selector.display
        prompt = app.query_one("#prompt", Input)
        assert prompt.placeholder.startswith("message") and app.focused is prompt

        # Switch tab, type: the message goes to that session on this space's gard.
        tabs.active = "s1"
        await pilot.pause(0.3)
        assert "fix the tests" in log_text(app.query_one("#log-1", RichLog))
        prompt.value = "run the tests"
        await prompt.action_submit()
        await pilot.pause()
        assert api.calls[-1] == ("send", 5, "run the tests", "run_1", 3)
        assert app.tabs["s1"].run_id == 20

        # Live events land in the tab; the completion does not repeat the model's text.
        await app.on_agent_event(5, "llm_response", {"run_id": 20, "content": "Running.", "tool_calls": []})
        await app.on_agent_event(5, "completed", {"run_id": 20, "output": "Running."})
        await pilot.pause(0.3)
        text = log_text(app.query_one("#log-1", RichLog))
        assert text.count("Running.") == 1 and "✓ done" in text

        # A status change updates the space row in place. (Norns now shows run 20 as the latest.)
        api.session_list[1]["status"] = "awaiting_tools"
        api.session_list[1]["run"] = {"id": 20, "status": "running", "waiting_for": None}
        await app.refresh_sessions().wait()
        await pilot.pause()
        assert list(sidebar.query(SpaceItem))[0] is items[0]
        assert "1 working" in items[0].markup

        # /spaces lists the gards with whether a worker is in them.
        await app.command("/spaces")
        await pilot.pause(0.3)
        assert "laptop" in log_text(app.query_one("#log-1", RichLog)) and "worker connected" in log_text(app.query_one("#log-1", RichLog))

        # /fork on the current run opens the fork's session.
        await app.command("/fork 3 try again")
        await pilot.pause()
        assert ("fork", 20, 3, "try again") in api.calls

        # Selecting the other space swaps the tabs.
        await app.select_space(0)
        await pilot.pause(0.3)
        assert [p.id for p in tabs.query("TabPane")] == ["s7"]
        assert 8 in app.stream.joined

        # /delete asks once, then removes the session from Norns and the tabs.
        await app.command("/delete")
        assert not any(c[0] == "delete" for c in api.calls)
        await app.command("/delete")
        await pilot.pause(0.3)
        assert ("delete", 8, "run_7") in api.calls
        assert "s7" not in app.tabs and 7 not in app.sessions


@pytest.mark.asyncio
async def test_new_session_starts_from_the_first_line():
    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app.new_tab()
        await pilot.pause(0.3)
        prompt = app.query_one("#prompt", Input)
        prompt.value = "hello there"
        await prompt.action_submit()
        await pilot.pause()
        kind, agent_id, content, key, gard_id = api.calls[-1]
        assert (kind, agent_id, content, gard_id) == ("send", 5, "hello there", 3)
        assert key.startswith("sleipnir-")
        # When the session shows up in the list it replaces the "new" tab.
        api.session_list.insert(0, {"id": 3, "key": key, "agent_id": 5, "agent_name": "sleipnir", "gard_id": 3, "status": "running",
                                    "first_message": "hello there", "run": {"id": 21, "status": "running", "waiting_for": None}})
        await app.refresh_sessions().wait()
        await pilot.pause(0.3)
        tabs = app.query_one("#tabs", TabbedContent)
        assert "new" not in app.tabs and "s3" in app.tabs
        assert tabs.active == "s3"
        assert app.tabs["s3"].title == "hello there"
        assert "hello there" in log_text(app.query_one("#log-3", RichLog))

        # A long title is cut for the tab strip, and /close drops the tab.
        api.session_list[0]["first_message"] = "x" * 40
        await app.refresh_sessions().wait()
        assert app.tabs["s3"].title.endswith("…") and len(app.tabs["s3"].title) == 22
        await app.command("/close")
        await pilot.pause()
        assert "s3" not in app.tabs
