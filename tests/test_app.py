"""The client against a fake Norns: spaces in the sidebar, a space's
sessions as tabs, sending, answering a question, forking, new sessions."""

from pathlib import Path

import pytest
from textual.widgets import Input, ListView, RichLog, TabbedContent

from sleipnir.api import ApiError
from sleipnir.app import SleipnirApp, SpaceItem
from sleipnir.widgets import PermissionPrompt


class FakeApi:
    url = "http://norns.test"
    api_key = "k"

    def __init__(self):
        self.calls = []
        self.gard_list = [{"id": 3, "name": "laptop", "status": "ready"}]
        self.destroy_conflict = False
        self.run_outcomes = {}
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
        if (s.get("run") or {}).get("status") in ("pending", "running", "waiting"):
            # Norns writes the turn to the conversation when the run ends.
            return {**s, "messages": []}
        return {
            **s,
            "messages": [
                {"role": "user", "content": s["first_message"], "run_id": (s.get("run") or {}).get("id")},
                {"role": "assistant", "content": "on it", "run_id": (s.get("run") or {}).get("id")},
            ],
            "runs": self.run_outcomes.get(session_id, [
                {"id": (s.get("run") or {}).get("id"), "status": (s.get("run") or {}).get("status")},
            ]),
        }

    async def agents(self):
        return [{"id": 5, "name": "sleipnir"}, {"id": 8, "name": "my-agent"}]

    async def gards(self):
        return list(self.gard_list)

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

    async def destroy_gard(self, gard_id, *, force=False):
        self.calls.append(("destroy_gard", gard_id, force))
        if self.destroy_conflict and not force:
            raise ApiError(409, "gard has an active run — pass force=true to destroy anyway")
        for g in self.gard_list:
            if g["id"] == gard_id:
                g["status"] = "destroyed"

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


@pytest.mark.asyncio
async def test_the_first_message_is_shown_once():
    """The new tab echoes the line it was started from; adding the pane
    must not also load the same message back off the run in flight."""
    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app.new_tab()
        await pilot.pause(0.3)
        prompt = app.query_one("#prompt", Input)
        prompt.value = "hello?"
        await prompt.action_submit()
        await pilot.pause()
        key = api.calls[-1][3]
        api.session_list.insert(0, {
            "id": 3, "key": key, "agent_id": 5, "agent_name": "sleipnir", "gard_id": 3,
            "status": "running", "first_message": None,
            "run": {"id": 21, "status": "running", "trigger_type": "message",
                    "input": {"user_message": "hello?"}, "waiting_for": None},
        })
        await app.refresh_sessions().wait()
        await pilot.pause(0.3)
        assert log_text(app.query_one("#log-3", RichLog)).count("hello?") == 1


@pytest.mark.asyncio
async def test_closing_a_tab_keeps_it_closed_across_a_poll():
    """ctrl+w only closes the tab locally — the session lives on in Norns —
    so a poll that still sees it must not bring the tab straight back."""
    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        tabs = app.query_one("#tabs", TabbedContent)
        assert [p.id for p in tabs.query("TabPane")] == ["s1", "s2"]

        tabs.active = "s1"
        await app.close_active_tab()
        await pilot.pause()
        assert [p.id for p in tabs.query("TabPane")] == ["s2"]

        # Norns still has the session; a poll must not resurrect the tab.
        await app.refresh_sessions().wait()
        await pilot.pause(0.3)
        assert [p.id for p in tabs.query("TabPane")] == ["s2"]
        assert "s1" not in app.tabs

        # Re-selecting the space (its own or, here, round-tripping through
        # the other one) is what brings a closed tab back.
        await app.select_space(0)
        await pilot.pause(0.3)
        await app.select_space(3)
        await pilot.pause(0.3)
        assert [p.id for p in tabs.query("TabPane")] == ["s1", "s2"]


@pytest.mark.asyncio
async def test_a_gard_first_seen_later_is_named():
    """A space created after this client started is still a name, not an id."""
    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        api.gard_list.append({"id": 9, "name": "missive", "status": "ready"})
        api.session_list.append({
            "id": 11, "key": "run_11", "agent_id": 5, "agent_name": "sleipnir", "gard_id": 9,
            "status": "idle", "first_message": "hello", "run": {"id": 40, "status": "completed", "waiting_for": None},
        })
        await app.refresh_sessions().wait()
        await pilot.pause(0.3)
        assert app.spaces[9].name == "missive"


@pytest.mark.asyncio
async def test_close_space_confirms_then_destroys_the_gard(isolated_home):
    """Closing a space destroys its gard — Norns kicks its workers — and
    forgets it locally so the next `sleip` there starts a new one."""
    from sleipnir import gard as gard_store
    from sleipnir.widgets import ConfirmClose

    isolated_home.mkdir(parents=True, exist_ok=True)
    gard_store._save({"http://norns.test|/tmp/repo": {"id": 3, "claim_token": "t", "name": "laptop"}})

    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        assert app.current_space == 3

        await pilot.press("ctrl+g")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConfirmClose)
        # "Keep it" is under the cursor, so enter alone never closes a space.
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert not [c for c in api.calls if c[0] == "destroy_gard"]
        assert 3 in app.spaces

        await pilot.press("ctrl+g")
        await pilot.pause(0.3)
        await pilot.press("down", "enter")
        await pilot.pause(0.3)
        assert ("destroy_gard", 3, False) in api.calls
        assert 3 not in app.spaces
        assert gard_store.stored("http://norns.test", Path("/tmp/repo")) is None


@pytest.mark.asyncio
async def test_close_space_can_be_escaped(isolated_home):
    from sleipnir.widgets import ConfirmClose

    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+g")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConfirmClose)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert not [c for c in api.calls if c[0] == "destroy_gard"]
        assert 3 in app.spaces


@pytest.mark.asyncio
async def test_close_space_needs_force_while_a_run_is_going(isolated_home):
    app, api = make_app()
    api.destroy_conflict = True
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app.command("/close-space")
        await pilot.pause(0.3)
        await pilot.press("down", "enter")
        await pilot.pause(0.3)
        assert 3 in app.spaces              # refused, so still there
        await app.command("/close-space force")
        await pilot.pause(0.3)
        await pilot.press("down", "enter")
        await pilot.pause(0.3)
        assert ("destroy_gard", 3, True) in api.calls
        assert 3 not in app.spaces


@pytest.mark.asyncio
async def test_a_gard_closed_elsewhere_disappears():
    """Destroy is a soft delete: the row stays, so the client has to hide
    it, and the sessions nothing can serve any more."""
    app, api = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        assert 3 in app.spaces and app.spaces[3].sessions
        # Another instance closed it. Nothing tells this client but the
        # next poll, so the poll is what has to notice.
        api.gard_list[0]["status"] = "destroyed"
        await app.refresh_sessions().wait()
        await pilot.pause(0.3)
        assert 3 not in app.spaces


@pytest.mark.asyncio
async def test_another_instance_sees_the_message_it_did_not_send():
    """Nothing on the wire carries the user's turn, so an instance that did
    not type it learns of it when the session's run changes."""
    api = FakeApi()
    watcher, _ = make_app(api)
    async with watcher.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        tab = watcher.tabs["s1"]
        watcher.query_one(TabbedContent).active = "s1"
        await pilot.pause(0.3)
        assert tab.loaded

        # Somewhere else, someone sends into the same session.
        api.session_list[1]["run"] = {
            "id": 99, "status": "running", "trigger_type": "message",
            "input": {"user_message": "have another look"}, "waiting_for": None,
        }
        await watcher.refresh_sessions().wait()
        await pilot.pause(0.3)
        assert log_text(watcher.query_one("#log-1", RichLog)).count("have another look") == 1

        # A later poll of the same run must not say it again.
        await watcher.refresh_sessions().wait()
        await pilot.pause(0.3)
        assert log_text(watcher.query_one("#log-1", RichLog)).count("have another look") == 1


@pytest.mark.asyncio
async def test_the_instance_that_sent_it_shows_it_once():
    api = FakeApi()
    app, _ = make_app(api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app.query_one(TabbedContent).active = "s1"
        await pilot.pause(0.3)
        prompt = app.query_one("#prompt", Input)
        prompt.value = "one more thing"
        await prompt.action_submit()
        await pilot.pause(0.3)
        # send_message returns run 20; the session row catches up to it.
        api.session_list[1]["run"] = {
            "id": 20, "status": "running", "trigger_type": "message",
            "input": {"user_message": "one more thing"}, "waiting_for": None,
        }
        await app.refresh_sessions().wait()
        await pilot.pause(0.3)
        assert log_text(app.query_one("#log-1", RichLog)).count("one more thing") == 1


@pytest.mark.asyncio
async def test_a_finished_run_reads_the_same_however_it_was_loaded():
    """Watching a run end shows "done"; the conversation row does not record
    that, so a tab opened afterwards has to add it back."""
    api = FakeApi()
    app, _ = make_app(api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app.query_one(TabbedContent).active = "s1"      # its run is completed
        await pilot.pause(0.3)
        assert "done" in log_text(app.query_one("#log-1", RichLog))


@pytest.mark.asyncio
async def test_a_failed_run_says_why_when_loaded():
    api = FakeApi()
    api.session_list[1]["run"] = {
        "id": 9, "status": "failed", "waiting_for": None,
        "failure_metadata": {"error": "the worker went away"},
    }
    app, _ = make_app(api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app.query_one(TabbedContent).active = "s1"
        await pilot.pause(0.3)
        assert "the worker went away" in log_text(app.query_one("#log-1", RichLog))


@pytest.mark.asyncio
async def test_run_boundaries_come_from_the_stored_turns():
    """A session with runs behind it reads the same as it did live: each
    run's ending where it ended, whoever is looking."""
    api = FakeApi()
    api.session_list[1]["run"] = {"id": 40, "status": "completed", "waiting_for": None}
    api.run_outcomes[1] = [
        {"id": 38, "status": "completed"},
        {"id": 39, "status": "failed"},
        {"id": 40, "status": "completed"},
    ]

    async def session(session_id):
        return {
            **api.session_list[1],
            "runs": api.run_outcomes[1],
            "messages": [
                {"role": "user", "content": "one", "run_id": 38},
                {"role": "assistant", "content": "did one", "run_id": 38},
                {"role": "user", "content": "two", "run_id": 39},
                {"role": "user", "content": "three", "run_id": 40},
                {"role": "assistant", "content": "did three", "run_id": 40},
            ],
        }

    api.session = session
    app, _ = make_app(api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app.query_one(TabbedContent).active = "s1"
        await pilot.pause(0.3)
        text = log_text(app.query_one("#log-1", RichLog))
        # Two completed runs and the failed one between them.
        assert text.count("done") == 2
        assert "run failed" in text
        assert text.index("did one") < text.index("run failed") < text.index("did three")


@pytest.mark.asyncio
async def test_turns_stored_before_runs_were_stamped_still_end():
    """Old conversations have no run ids; the session's own run still says
    how the last one finished."""
    api = FakeApi()

    async def session(session_id):
        return {
            **api.session_list[1],
            "runs": [],
            "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        }

    api.session = session
    app, _ = make_app(api)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app.query_one(TabbedContent).active = "s1"
        await pilot.pause(0.3)
        assert log_text(app.query_one("#log-1", RichLog)).count("done") == 1
