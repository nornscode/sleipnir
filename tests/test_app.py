"""The client against a fake Norns: sidebar, opening a session, sending,
answering a question, forking."""

from pathlib import Path

import pytest
from textual.widgets import Input, ListView, RichLog, TabbedContent

from sleipnir.app import SessionItem, SleipnirApp


class FakeApi:
    url = "http://norns.test"
    api_key = "k"

    def __init__(self):
        self.calls = []
        self.session_list = [
            {"id": 1, "key": "run_1", "agent_id": 5, "agent_name": "sleipnir", "gard_id": 3, "status": "idle",
             "first_message": "fix the tests", "run": {"id": 9, "status": "completed", "waiting_for": None}},
            {"id": 2, "key": "run_2", "agent_id": 5, "agent_name": "sleipnir", "gard_id": 3, "status": "waiting",
             "first_message": "add a flag", "run": {"id": 12, "status": "waiting", "waiting_for": {"question": "Allow bash `rm`?"}}},
        ]

    async def sessions(self, limit=100):
        return list(self.session_list)

    async def session(self, session_id):
        s = next(s for s in self.session_list if s["id"] == session_id)
        return {**s, "messages": [{"role": "user", "content": s["first_message"]}, {"role": "assistant", "content": "on it"}]}

    async def agents(self):
        return [{"id": 5, "name": "sleipnir"}]

    async def gards(self):
        return [{"id": 3, "name": "laptop"}]

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
        self.joined.append(agent_id)


def log_text(log: RichLog) -> str:
    return "\n".join(strip.text for strip in log.lines)


def make_app(api=None):
    api = api or FakeApi()
    return SleipnirApp(api, agent_name="sleipnir", gard_id=3, root=Path("/tmp/repo"), stream=FakeStream(), poll_seconds=60), api


@pytest.mark.asyncio
async def test_sidebar_open_send_reply_and_fork():
    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sidebar = app.query_one("#sidebar", ListView)
        assert [item.session["id"] for item in sidebar.query(SessionItem)] == [1, 2]
        assert app.agent_id == 5

        # Open the first session: a tab with its history, joined to the agent's events.
        await app.open_session(api.session_list[0])
        await pilot.pause(0.3)
        assert app.query_one("#tabs", TabbedContent).active == "s1"
        assert app.stream.joined == [5]
        log = app.query_one("#log-1", RichLog)
        assert "fix the tests" in log_text(log)

        # Typing sends to that session, pinned to this repo's gard.
        prompt = app.query_one("#prompt", Input)
        prompt.value = "run the tests"
        await prompt.action_submit()
        await pilot.pause()
        assert api.calls[-1] == ("send", 5, "run the tests", "run_1", 3)
        assert app.tabs["s1"].run_id == 20

        # A live event for that run lands in the tab.
        await app.on_agent_event(5, "llm_response", {"run_id": 20, "content": "Running.", "tool_calls": []})
        await pilot.pause(0.3)
        assert "Running." in log_text(log)

        # The parked session: the next line answers the question.
        await app.open_session(api.session_list[1])
        await pilot.pause(0.3)
        assert app.tabs["s2"].question == "Allow bash `rm`?"
        prompt.value = "always"
        await prompt.action_submit()
        await pilot.pause()
        assert api.calls[-1] == ("reply", 12, "always")
        assert app.tabs["s2"].question is None

        # /fork on the current run opens the fork's session.
        await app.command("/fork 3 try again")
        await pilot.pause()
        assert ("fork", 12, 3, "try again") in api.calls


@pytest.mark.asyncio
async def test_new_session_starts_from_the_first_line():
    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.new_tab()
        await pilot.pause()
        prompt = app.query_one("#prompt", Input)
        prompt.value = "hello there"
        await prompt.action_submit()
        await pilot.pause()
        kind, agent_id, content, key, gard_id = api.calls[-1]
        assert (kind, agent_id, content, gard_id) == ("send", 5, "hello there", 3)
        assert key.startswith("sleipnir-")
        # When the session shows up in the list it replaces the "new" tab.
        api.session_list.append({"id": 3, "key": key, "agent_id": 5, "agent_name": "sleipnir", "gard_id": 3, "status": "running",
                                 "first_message": "hello there", "run": {"id": 21, "status": "running", "waiting_for": None}})
        await app.refresh_sessions().wait()
        await pilot.pause()
        assert "new" not in app.tabs and "s3" in app.tabs
        assert app.query_one("#tabs", TabbedContent).active == "s3"
