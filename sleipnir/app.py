"""The session client: every session across every gard down the side, the
one you are in on the right, your worker in the same process."""

from __future__ import annotations

import asyncio
import logging
import shlex
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, Label, ListItem, ListView, RichLog, Static, TabbedContent, TabPane

from sleipnir.api import ApiError, NornsApi
from sleipnir.render import event_lines, message_lines, session_label, title_of
from sleipnir.stream import AgentStream

logger = logging.getLogger("sleipnir.app")

HELP = """[b]sleipnir[/b] — sessions on the left, the one you are in on the right.
Type to talk to the agent of this repository; when it asks a question, your next line answers it.

  /new              start a new session in this repository
  /fork N [message] fork the current session from step N into a new one
  /resume           reload the current session and re-attach to its run
  /help             this text
  /quit             leave (the worker stops with you; sessions live on in Norns)

Keys: ctrl+n new session · ctrl+r refresh · ctrl+q quit"""


@dataclass
class Tab:
    """An open session and what we know about it."""

    session_id: int
    agent_id: int
    key: str
    run_id: int | None = None
    question: str | None = None
    seen_runs: set[int] = field(default_factory=set)


class SessionItem(ListItem):
    def __init__(self, session: dict, gard_names: dict[int, str]):
        super().__init__(Label(session_label(session, gard_names), markup=True))
        self.session = session


class SleipnirApp(App):
    CSS = """
    #sidebar { width: 36; border-right: solid $primary-background; }
    #sidebar ListItem { padding: 0 1; }
    #main { width: 1fr; }
    #tabs { height: 1fr; }
    RichLog { height: 1fr; padding: 0 1; }
    #prompt { dock: bottom; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    """

    BINDINGS = [
        Binding("ctrl+n", "new_session", "New"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        api: NornsApi,
        *,
        agent_name: str,
        gard_id: int | None,
        root: Path,
        worker: threading.Thread | None = None,
        on_exit=None,
        stream: AgentStream | None = None,
        poll_seconds: float = 2.0,
    ):
        super().__init__()
        self.api = api
        self.agent_name = agent_name
        self.gard_id = gard_id
        self.root = root
        self.worker_thread = worker
        self.on_exit = on_exit
        self.stream = stream
        self.poll_seconds = poll_seconds
        self.tabs: dict[str, Tab] = {}
        self.sessions: dict[int, dict] = {}
        self.gard_names: dict[int, str] = {}
        self.agent_id: int | None = None
        self._pending_key: str | None = None
        self._pending_text: str | None = None

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield ListView(id="sidebar")
            with Vertical(id="main"):
                yield TabbedContent(id="tabs")
                yield Static("", id="status")
        yield Input(placeholder="message the agent, or /help", id="prompt")
        yield Footer()

    async def on_mount(self) -> None:
        self.title = f"sleipnir · {self.root.name}"
        if self.worker_thread is not None:
            self.worker_thread.start()
        if self.stream is None:
            self.stream = AgentStream(self.api.url, self.api.api_key, self.on_agent_event)
        self.stream.start()
        self.set_interval(self.poll_seconds, self.refresh_sessions)
        await self.refresh_sessions().wait()
        self.query_one("#prompt", Input).focus()

    async def on_unmount(self) -> None:
        if self.stream:
            await self.stream.stop()
        await self.api.close()
        if self.on_exit:
            self.on_exit()

    # -- sessions ----------------------------------------------------------

    @work(exclusive=True, group="sessions")
    async def refresh_sessions(self) -> None:
        try:
            sessions = await self.api.sessions()
            if self.agent_id is None or not self.gard_names:
                await self._learn_agent_and_gards()
        except Exception as e:
            self.set_status(f"cannot reach Norns: {e}")
            return

        self.sessions = {s["id"]: s for s in sessions}
        listview = self.query_one("#sidebar", ListView)
        highlighted = listview.highlighted_child
        current = highlighted.session["id"] if isinstance(highlighted, SessionItem) else None
        await listview.clear()
        for s in sessions:
            await listview.append(SessionItem(s, self.gard_names))
        if current is not None:
            for i, s in enumerate(sessions):
                if s["id"] == current:
                    listview.index = i
                    break

        # Open tabs learn about runs started elsewhere.
        for tab in self.tabs.values():
            s = self.sessions.get(tab.session_id)
            run = (s or {}).get("run") or {}
            if run.get("id") and run["id"] != tab.run_id:
                tab.run_id = run["id"]
            if run.get("status") == "waiting" and (run.get("waiting_for") or {}).get("question"):
                if tab.question != run["waiting_for"]["question"]:
                    tab.question = run["waiting_for"]["question"]
                    self.log_lines(tab, event_lines("waiting_for_user", {"question": tab.question}))
            elif run.get("status") != "waiting":
                tab.question = None

        # A session we just started shows up: open it in place of the "new" tab.
        if self._pending_key:
            for s in sessions:
                if s["key"] == self._pending_key:
                    self._pending_key = None
                    await self.close_new_tab()
                    await self.open_session(s, replay=False)
                    if self._pending_text:
                        self.log_line(self.tabs[f"s{s['id']}"], f"[b green]›[/] {self._pending_text}")
                        self._pending_text = None
                    break

        waiting = sum(1 for s in sessions if (s.get("run") or {}).get("status") == "waiting")
        thinking = sum(1 for s in sessions if s.get("status") in ("running", "awaiting_llm", "awaiting_tools"))
        gard = f"gard {self.gard_names.get(self.gard_id, self.gard_id)}" if self.gard_id else "no gard"
        self.set_status(f"{len(sessions)} sessions · {thinking} working · {waiting} need you · {gard} · agent {self.agent_name}")

    async def _learn_agent_and_gards(self) -> None:
        for a in await self.api.agents():
            if a.get("name") == self.agent_name:
                self.agent_id = a["id"]
        try:
            self.gard_names = {g["id"]: g.get("name") or str(g["id"]) for g in await self.api.gards()}
        except ApiError:
            self.gard_names = {}

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, SessionItem):
            await self.open_session(event.item.session)

    async def open_session(self, session: dict, *, replay: bool = True) -> None:
        pane_id = f"s{session['id']}"
        tabs = self.query_one("#tabs", TabbedContent)
        if pane_id in self.tabs:
            tabs.active = pane_id
            self.query_one("#prompt", Input).focus()
            return

        run = session.get("run") or {}
        tab = Tab(session_id=session["id"], agent_id=session["agent_id"], key=session["key"], run_id=run.get("id"))
        self.tabs[pane_id] = tab
        log = RichLog(wrap=True, markup=True, highlight=False, id=f"log-{session['id']}")
        await tabs.add_pane(TabPane(title_of(session), log, id=pane_id))
        tabs.active = pane_id
        await self.stream.join(session["agent_id"])

        if replay:
            try:
                full = await self.api.session(session["id"])
            except Exception as e:
                self.log_line(tab, f"[red]could not load session: {e}[/red]")
                full = session
            for msg in full.get("messages") or []:
                self.log_lines(tab, message_lines(msg))
            if run.get("status") == "waiting" and (run.get("waiting_for") or {}).get("question"):
                tab.question = run["waiting_for"]["question"]
                self.log_lines(tab, event_lines("waiting_for_user", {"question": tab.question}))
            elif run.get("status") in ("running",):
                self.log_line(tab, "[dim]— run in progress; attached —[/dim]")
        self.query_one("#prompt", Input).focus()

    def active_tab(self) -> Tab | None:
        return self.tabs.get(self.query_one("#tabs", TabbedContent).active or "")

    # -- live events -------------------------------------------------------

    async def on_agent_event(self, agent_id: int, event: str, payload: dict) -> None:
        run_id = payload.get("run_id")
        tab = next((t for t in self.tabs.values() if t.run_id == run_id and t.agent_id == agent_id), None)
        if tab is None:
            # A run we have not mapped yet (started elsewhere, or just now): learn it.
            self.refresh_sessions()
            return
        if event == "waiting_for_user":
            tab.question = payload.get("question")
        elif event in ("tool_result", "completed", "error") and tab.question and event != "tool_result":
            tab.question = None
        elif event == "tool_result" and payload.get("name") == "ask_human":
            tab.question = None
        self.log_lines(tab, event_lines(event, payload))
        if event in ("completed", "error", "waiting_for_user"):
            self.refresh_sessions()

    # -- input -------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            await self.command(text)
            return
        tab = self.active_tab()
        if tab is None or tab.session_id == 0:
            await self.start_session(text)
            return
        if tab.question and tab.run_id:
            try:
                await self.api.reply(tab.run_id, text)
                self.log_line(tab, f"[b green]›[/] {text}")
                tab.question = None
            except ApiError as e:
                self.log_line(tab, f"[red]{e.message}[/red]")
            return
        await self.send(tab, text)

    async def send(self, tab: Tab, text: str) -> None:
        gard = self.gard_id if tab.agent_id == self.agent_id else None
        try:
            run_id = await self.api.send_message(tab.agent_id, text, conversation_key=tab.key, gard_id=gard)
        except ApiError as e:
            self.log_line(tab, f"[red]{e.message}[/red]")
            return
        tab.run_id = run_id
        self.log_line(tab, f"[b green]›[/] {text}")

    async def start_session(self, text: str) -> None:
        if self.agent_id is None:
            await self._learn_agent_and_gards()
        if self.agent_id is None:
            self.notify(f"agent {self.agent_name} is not registered yet; is the worker running?", severity="error")
            return
        key = f"sleipnir-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            await self.api.send_message(self.agent_id, text, conversation_key=key, gard_id=self.gard_id)
        except ApiError as e:
            self.notify(e.message, severity="error")
            return
        self._pending_key = key
        self._pending_text = text
        self.log_line(None, "[dim]starting…[/dim]")
        self.refresh_sessions()

    async def close_new_tab(self) -> None:
        if "new" in self.tabs:
            self.tabs.pop("new", None)
            try:
                await self.query_one("#tabs", TabbedContent).remove_pane("new")
            except Exception:
                pass

    async def command(self, text: str) -> None:
        try:
            parts = shlex.split(text)
        except ValueError:
            parts = text.split()
        cmd, args = parts[0].lower(), parts[1:]
        tab = self.active_tab()
        if cmd in ("/quit", "/q", "/exit"):
            self.exit()
        elif cmd == "/help":
            self.log_line(tab, HELP)
        elif cmd == "/new":
            await self.new_tab()
        elif cmd == "/resume":
            if tab is None:
                self.notify("no session open")
                return
            await self.resume(tab)
        elif cmd == "/fork":
            if tab is None or tab.run_id is None:
                self.notify("open a session with a run first", severity="warning")
                return
            if not args or not args[0].isdigit():
                self.notify("usage: /fork <step> [message]", severity="warning")
                return
            message = " ".join(args[1:]) or None
            try:
                result = await self.api.fork(tab.run_id, int(args[0]), message)
            except ApiError as e:
                self.notify(e.message, severity="error")
                return
            self.log_line(tab, f"[dim]— forked at step {args[0]} into run {result.get('run_id')} —[/dim]")
            forked = await self.api.run(result["run_id"])
            for s in await self.api.sessions():
                if s["id"] == forked.get("conversation_id"):
                    await self.open_session(s, replay=True)
                    break
            self.refresh_sessions()
        else:
            self.notify(f"unknown command {cmd}; try /help", severity="warning")

    async def resume(self, tab: Tab) -> None:
        pane_id = f"s{tab.session_id}"
        tabs = self.query_one("#tabs", TabbedContent)
        await tabs.remove_pane(pane_id)
        self.tabs.pop(pane_id, None)
        try:
            session = await self.api.session(tab.session_id)
        except ApiError as e:
            self.notify(e.message, severity="error")
            return
        await self.open_session(session, replay=True)

    def action_new_session(self) -> None:
        self.run_worker(self.new_tab(), exclusive=False)

    async def new_tab(self) -> None:
        """An empty tab: the next line typed into it starts a session here."""
        tabs = self.query_one("#tabs", TabbedContent)
        if "new" not in self.tabs:
            self.tabs["new"] = Tab(session_id=0, agent_id=self.agent_id or 0, key="")
            log = RichLog(wrap=True, markup=True, highlight=False, id="log-new")
            await tabs.add_pane(TabPane("new", log, id="new"))
            log.write(f"[dim]a new session in {self.root.name}; type to start it[/dim]")
        tabs.active = "new"
        self.query_one("#prompt", Input).focus()

    def action_refresh(self) -> None:
        self.refresh_sessions()

    # -- output ------------------------------------------------------------

    def log_lines(self, tab: Tab | None, lines: list[str]) -> None:
        for line in lines:
            self.log_line(tab, line)

    def log_line(self, tab: Tab | None, line: str) -> None:
        target = f"#log-{tab.session_id}" if tab and tab.session_id else "#log-new"
        try:
            self.query_one(target, RichLog).write(line)
        except Exception:
            if tab is None:
                self.set_status(line)

    def set_status(self, text: str) -> None:
        try:
            self.query_one("#status", Static).update(text)
        except Exception:
            pass
