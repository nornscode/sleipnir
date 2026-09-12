"""The session client: spaces down the side, the sessions of the selected
space as tabs, your worker in the same process.

A space is a gard: a checkout on a machine with a worker in it. Sessions
that no gard serves share a "no gard" space.
"""

from __future__ import annotations

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
from rich.markdown import Markdown
from rich.markup import escape
from textual.widgets import Input, Label, ListItem, ListView, OptionList, RichLog, Static, TabbedContent, TabPane

from sleipnir.api import ApiError, NornsApi
from sleipnir.render import (
    Md,
    archived_lines,
    ended_lines,
    event_lines,
    expand_answer,
    message_lines,
    permission_details,
    permission_in_question,
    run_event_lines,
    set_web_base,
    space_label,
    spaces_lines,
    text_of,
    title_of,
)
from sleipnir.stream import AgentStream
from sleipnir.widgets import ConfirmClose, PermissionPrompt

logger = logging.getLogger("sleipnir.app")

NO_GARD = 0

HELP = """[b]sleipnir[/b] — spaces on the left (one per checkout with a worker), the sessions of the selected space as tabs.
Type to talk to the session you are in; when the agent asks a question, your next line answers it.
The worker runs beside this window, not inside it, so leaving does not stop the work.

  /new              start a new session in this space (ctrl+n)
  /fork N [message] fork the current session from step N into a new one
  /spaces           every space, with whether a worker is in it
  /resume           reload the current session and re-attach to its run
  /close            close the current tab (ctrl+w); the session comes back
  /archive          put this session away: the tab goes and stays gone,
                    but nothing is deleted
  /archived         the sessions you have put away
  /restore N        take one back out of the archive and open it
  /delete           delete the current session from Norns (asks once)
  /start            start a worker for this space, if its checkout is here
  /close-space      close this space everywhere (ctrl+g): destroys its
                    gard and stops its worker on every machine
  /help             this text
  /quit             stop looking (ctrl+q). The worker keeps this space
                    open; `sleip stop` closes it in this checkout

Keys: ctrl+n new session · ctrl+w close tab · ctrl+g close space · ctrl+r refresh · ctrl+q quit"""


@dataclass
class Tab:
    """An open session and what we know about it."""

    session_id: int
    agent_id: int
    key: str
    run_id: int | None = None
    # The run whose opening user message this tab has already shown, so a
    # message is not printed twice by the instance that sent it, and is
    # printed once by every instance that did not.
    shown_user_run: int | None = None
    question: str | None = None
    last_assistant: str = ""
    title: str = ""
    loaded: bool = False
    # Permission requests seen in this session: token -> (tool, subject).
    permissions: dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass
class Space:
    gard_id: int
    name: str
    sessions: list[dict] = field(default_factory=list)


class SpaceItem(ListItem):
    def __init__(self, space: Space):
        self.space = space
        self.markup = space_label(space.name, space.sessions)
        super().__init__(Label(self.markup, markup=True))

    def refresh_space(self, space: Space) -> None:
        self.space = space
        markup = space_label(space.name, space.sessions)
        if markup != self.markup:
            self.markup = markup
            self.query_one(Label).update(markup)


def tab_title(session: dict, width: int = 22) -> str:
    title = title_of(session)
    return title if len(title) <= width else title[: width - 1] + "…"


class SleipnirApp(App):
    CSS = """
    #sidebar { width: 28; border-right: solid $primary-background; }
    #sidebar ListItem { padding: 0 1; }
    #main { width: 1fr; }
    #tabs { height: 1fr; }
    RichLog { height: 1fr; padding: 0 2; }

    /* No boxes, and a blank row on either side of the prompt: what made
       the old chrome feel tight was five rows of it, not the spacing. The
       caret lines up with the transcript's own left edge. */
    #promptline { height: 1; margin: 1 2 0 2; }
    #caret { width: 2; color: $success; }
    #prompt { border: none; height: 1; padding: 0; background: transparent; }
    #prompt:focus { border: none; background: transparent; }
    #statusline { height: 1; margin: 1 0 0 0; padding: 0 2; }
    #keys, #state { color: $text-muted; height: 1; }
    #state { width: 1fr; text-align: right; }
    """

    BINDINGS = [
        Binding("ctrl+n", "new_session", "New"),
        Binding("ctrl+w", "close_tab", "Close"),
        Binding("ctrl+r", "refresh", "Refresh"),
        # Not ctrl+x / ctrl+k / ctrl+w: the prompt edits with those.
        Binding("ctrl+g", "close_space", "Close space"),
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
        self.spaces: dict[int, Space] = {}
        self.current_space: int | None = gard_id
        self.gard_names: dict[int, str] = {}
        # Gards destroyed since we last looked: no worker can ever
        # claim one again, so neither it nor its sessions are reachable.
        self.closed_gards: set[int] = set()
        # Sessions whose tab was closed locally (ctrl+w / /close): the
        # session lives on in Norns, so the next poll would otherwise
        # bring the tab straight back. Cleared when the space holding it
        # is re-selected.
        self.closed_sessions: set[int] = set()
        self.agent_id: int | None = None
        self._pending_key: str | None = None
        self._pending_text: str | None = None
        self._delete_armed: tuple[str, float] | None = None

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield ListView(id="sidebar")
            with Vertical(id="main"):
                yield TabbedContent(id="tabs")
                yield PermissionPrompt()
                with Horizontal(id="promptline"):
                    yield Static("›", id="caret", markup=False)
                    yield Input(placeholder="message the agent, or /help", id="prompt")
                with Horizontal(id="statusline"):
                    yield Static("", id="keys", markup=True)
                    yield Static("", id="state", markup=True)

    async def on_mount(self) -> None:
        self.title = f"sleipnir · {self.root.name}"
        set_web_base(self.api.url)
        self.query_one("#keys", Static).update(self.KEYS)
        if self.worker_thread is not None:
            self.worker_thread.start()
        if self.stream is None:
            self.stream = AgentStream(self.api.url, self.api.api_key, self.on_agent_event)
        self.stream.start()
        self.set_interval(self.poll_seconds, self.refresh_sessions)
        await self.refresh_sessions().wait()
        self._focus_default()

    async def on_unmount(self) -> None:
        if self.stream:
            await self.stream.stop()
        await self.api.close()
        if self.on_exit:
            self.on_exit()

    # -- spaces and sessions -----------------------------------------------

    @work(exclusive=True, group="sessions")
    async def refresh_sessions(self) -> None:
        try:
            sessions = await self.api.sessions()
            # Every poll, because spaces open and close on machines we are
            # not looking at: one closed elsewhere has to leave this sidebar
            # too, and one created elsewhere arrives with its name.
            await self._learn_gards()
            if self.agent_id is None:
                await self._learn_agents()
        except Exception as e:
            self.set_status(f"cannot reach Norns: {e}")
            return

        self.sessions = {s["id"]: s for s in sessions}
        self.spaces = self._group_spaces(sessions)
        await self._render_sidebar()

        if self.current_space is None or self.current_space not in self.spaces:
            self.current_space = next(iter(self.spaces), None)
        await self._sync_tabs()

        # A session we just started shows up: replace the "new" tab with it.
        if self._pending_key:
            for s in sessions:
                if s["key"] == self._pending_key:
                    self._pending_key = None
                    await self.close_new_tab()
                    await self.open_session(s, replay=False)
                    if self._pending_text:
                        started = self.tabs[f"s{s['id']}"]
                        started.shown_user_run = (s.get("run") or {}).get("id")
                        self.log_lines(started, ["", f"[b green]›[/] {self._pending_text}"])
                        self._pending_text = None
                    break

        waiting = sum(1 for s in sessions if (s.get("run") or {}).get("status") == "waiting")
        thinking = sum(1 for s in sessions if s.get("status") in ("running", "awaiting_llm", "awaiting_tools"))
        here = self.gard_names.get(self.gard_id, self.gard_id) if self.gard_id else "no gard"
        # The sidebar already counts spaces and their sessions; this says
        # what it cannot — where you are, and whether anything wants you.
        state = [f"{here} · {self.agent_name}"]
        if thinking:
            state.insert(0, f"{thinking} working")
        if waiting:
            state.insert(0, f"[yellow]{waiting} need you[/]")
        self.set_status("  ".join(state))

    def _group_spaces(self, sessions: list[dict]) -> dict[int, Space]:
        spaces: dict[int, Space] = {}
        if self.gard_id and self.gard_id not in self.closed_gards:
            spaces[self.gard_id] = Space(self.gard_id, self.gard_names.get(self.gard_id, f"gard {self.gard_id}"))
        for s in sessions:
            gid = s.get("gard_id") or NO_GARD
            if gid in self.closed_gards or s["id"] in self.closed_sessions:
                continue
            if gid not in spaces:
                name = "no gard" if gid == NO_GARD else self.gard_names.get(gid, f"gard {gid}")
                spaces[gid] = Space(gid, name)
            spaces[gid].sessions.append(s)
        # This checkout first, then the rest by most recent activity, no-gard last.
        def order(item):
            gid, space = item
            latest = max((s.get("updated_at") or "" for s in space.sessions), default="")
            return (gid != self.gard_id, gid == NO_GARD, latest and "~" or "", "")
        return dict(sorted(spaces.items(), key=lambda item: (item[0] != self.gard_id, item[0] == NO_GARD, -len(item[1].sessions))))

    async def _render_sidebar(self) -> None:
        listview = self.query_one("#sidebar", ListView)
        items = list(listview.query(SpaceItem))
        spaces = list(self.spaces.values())
        if [i.space.gard_id for i in items] == [sp.gard_id for sp in spaces]:
            for item, space in zip(items, spaces):
                item.refresh_space(space)
            return
        await listview.clear()
        for sp in spaces:
            await listview.append(SpaceItem(sp))
        for i, sp in enumerate(spaces):
            if sp.gard_id == self.current_space:
                listview.index = i
                break

    async def _learn_agents(self) -> None:
        for a in await self.api.agents():
            if a.get("name") == self.agent_name:
                self.agent_id = a["id"]

    async def _learn_gards(self) -> None:
        try:
            gards = await self.api.gards()
        except ApiError:
            return  # keep what we know rather than blanking the sidebar
        self.gard_names = {g["id"]: g.get("name") or str(g["id"]) for g in gards}
        # Destroy is a soft delete: the row stays with status "destroyed",
        # so a closed space would otherwise sit in every other client.
        self.closed_gards = {g["id"] for g in gards if g.get("status") == "destroyed"}

    async def _learn_agent_and_gards(self) -> None:
        await self._learn_agents()
        await self._learn_gards()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, SpaceItem):
            await self.select_space(event.item.space.gard_id)

    async def select_space(self, gard_id: int) -> None:
        if gard_id == self.current_space:
            return
        self.current_space = gard_id
        self.closed_sessions -= {
            sid for sid, s in self.sessions.items() if (s.get("gard_id") or NO_GARD) == gard_id
        }
        self.spaces = self._group_spaces(list(self.sessions.values()))
        await self._sync_tabs(reset=True)
        self._focus_default()

    async def _sync_tabs(self, reset: bool = False) -> None:
        """The tabs are the sessions of the current space, oldest on the left."""
        tabs = self.query_one("#tabs", TabbedContent)
        space = self.spaces.get(self.current_space) if self.current_space is not None else None
        wanted = list(reversed(space.sessions)) if space else []
        wanted_ids = [f"s{s['id']}" for s in wanted]

        if reset:
            for pane_id in list(self.tabs):
                if pane_id != "new":
                    self.tabs.pop(pane_id, None)
                    try:
                        await tabs.remove_pane(pane_id)
                    except Exception:
                        pass

        for pane_id in list(self.tabs):
            if pane_id != "new" and pane_id not in wanted_ids:
                self.tabs.pop(pane_id, None)
                try:
                    await tabs.remove_pane(pane_id)
                except Exception:
                    pass

        first_fill = not any(pid != "new" for pid in self.tabs)

        for s in wanted:
            pane_id = f"s{s['id']}"
            run = s.get("run") or {}
            if pane_id not in self.tabs:
                # A session we just started echoes its own first line below;
                # adding the pane posts TabActivated, whose handler would
                # otherwise load the same message from the run in flight.
                tab = Tab(
                    session_id=s["id"], agent_id=s["agent_id"], key=s["key"], run_id=run.get("id"),
                    title=tab_title(s), loaded=s["key"] == self._pending_key,
                )
                self.tabs[pane_id] = tab
                log = RichLog(wrap=True, markup=True, highlight=False, id=f"log-{s['id']}")
                await tabs.add_pane(TabPane(tab.title, log, id=pane_id))
                await self.stream.join(s["agent_id"])
                continue
            tab = self.tabs[pane_id]
            title = tab_title(s)
            if title != tab.title:
                tab.title = title
                self.set_tab_title(pane_id, title)
            if run.get("id") and run["id"] != tab.run_id:
                tab.run_id = run["id"]
                # Nothing on the wire carries the user's turn — agent_started
                # is only a run id — so this is where an instance that did
                # not send it learns what was said.
                opening = text_of((run.get("input") or {}).get("user_message")).strip()
                if tab.loaded and opening and tab.shown_user_run != run["id"] and run.get("trigger_type") != "fork":
                    self.log_lines(tab, ["", f"[b green]›[/] {escape(opening)}"])
                tab.shown_user_run = run["id"]
            if run.get("status") == "waiting" and (run.get("waiting_for") or {}).get("question"):
                if tab.question != run["waiting_for"]["question"]:
                    tab.question = run["waiting_for"]["question"]
                    if tab.loaded:
                        self.log_lines(tab, event_lines("waiting_for_user", {"question": tab.question}, tab.permissions))
            elif run.get("status") != "waiting":
                tab.question = None

        if (reset or first_fill or not tabs.active or tabs.active not in self.tabs) and wanted_ids:
            tabs.active = wanted_ids[-1]
        await self._ensure_loaded(tabs.active)

    async def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        await self._ensure_loaded(event.pane.id)
        self._update_prompt()

    async def _ensure_loaded(self, pane_id: str | None) -> None:
        """A tab's history is fetched the first time it is shown."""
        tab = self.tabs.get(pane_id or "")
        if tab is None or tab.loaded or tab.session_id == 0:
            return
        tab.loaded = True
        try:
            full = await self.api.session(tab.session_id)
        except Exception as e:
            self.log_line(tab, f"[red]could not load session: {e}[/red]")
            return
        run = full.get("run") or {}
        # Turns carry the run that produced them and the session says how
        # each ended, which is what lets a transcript we did not watch being
        # made show the same run boundaries as one we did.
        outcomes = {r["id"]: r.get("status") for r in (full.get("runs") or []) if r.get("id")}
        current, stamped = None, False
        for msg in full.get("messages") or []:
            rid = msg.get("run_id")
            if rid is not None:
                stamped = True
                if current is not None and rid != current:
                    self.log_lines(tab, self._ending(current, outcomes, run))
                current = rid
            self._learn_permission(tab, msg.get("name"), msg.get("content"))
            self.log_lines(tab, message_lines(msg, tab.permissions))
        if stamped and current is not None:
            self.log_lines(tab, self._ending(current, outcomes, run))

        if run.get("status") in ("pending", "running", "waiting") and run.get("id"):
            # The run in flight is not on the conversation row yet: its own
            # log is the rest of the history.
            await self._replay_run(tab, run)
        elif not stamped and run.get("status") in ("completed", "failed"):
            # Turns written before runs were stamped: the last ending is
            # still recoverable from the session's own run.
            self.log_lines(tab, ended_lines(run))
        if run.get("status") == "waiting" and (run.get("waiting_for") or {}).get("question"):
            tab.question = run["waiting_for"]["question"]
        self._update_prompt()

    def _ending(self, run_id: int, outcomes: dict, row_run: dict) -> list:
        """How that run finished. The session's own run says why it failed;
        for older ones all we have is that it did."""
        if row_run.get("id") == run_id:
            return ended_lines(row_run)
        return ended_lines({"status": outcomes.get(run_id)})

    async def _replay_run(self, tab: Tab, run: dict) -> None:
        try:
            events = await self.api.run_events(run["id"])
        except Exception as e:
            self.log_line(tab, f"[red]could not load the run in progress: {e}[/red]")
            return
        message = text_of((run.get("input") or {}).get("user_message")).strip()
        tab.shown_user_run = run.get("id")
        if message and run.get("trigger_type") != "fork":
            self.log_lines(tab, ["", f"[b green]›[/] {message}"])
        for e in events:
            if e.get("event_type") == "tool_result":
                payload = e.get("payload") or {}
                self._learn_permission(tab, payload.get("name"), payload.get("content"))
        self.log_lines(tab, run_event_lines(events, tab.permissions, run_id=run.get("id")))

    def _learn_permission(self, tab: Tab, name, content) -> None:
        if name in ("bash", "write_file", "edit_file") and isinstance(content, str):
            details = permission_details(content)
            if details:
                token, tool, subject = details
                tab.permissions[token] = (tool, subject)

    async def open_session(self, session: dict, *, replay: bool = True) -> None:
        """Show a session: switch to its space if needed, activate its tab."""
        gid = session.get("gard_id") or NO_GARD
        if gid != self.current_space:
            self.current_space = gid
            self.spaces = self._group_spaces(list(self.sessions.values()))
            await self._render_sidebar()
            await self._sync_tabs(reset=True)
        pane_id = f"s{session['id']}"
        if pane_id not in self.tabs:
            if session["id"] not in self.sessions:
                self.sessions[session["id"]] = session
                self.spaces = self._group_spaces(list(self.sessions.values()))
            await self._sync_tabs()
        tabs = self.query_one("#tabs", TabbedContent)
        if pane_id in self.tabs:
            tabs.active = pane_id
            if not replay:
                self.tabs[pane_id].loaded = True
            await self._ensure_loaded(pane_id)
        self._focus_default()

    def active_tab(self) -> Tab | None:
        return self.tabs.get(self.query_one("#tabs", TabbedContent).active or "")

    def _update_prompt(self) -> None:
        """The permission selector shows for a pending permission on the
        active tab; the input's placeholder says what a line will do."""
        tab = self.active_tab()
        prompt = self.query_one("#prompt", Input)
        selector = self.query_one(PermissionPrompt)
        action = permission_in_question(tab.question, tab.permissions) if tab and tab.question else None
        if action:
            if not selector.display or (selector.tool, selector.subject) != action:
                selector.show(*action)
            prompt.placeholder = "or type a reply to the agent"
            return
        selector.hide()
        if tab and tab.question:
            prompt.placeholder = "answer the question"
        elif tab is None or tab.session_id == 0:
            prompt.placeholder = "type to start a new session, or /help"
        else:
            prompt.placeholder = "message the agent, or /help"

    def _focus_default(self) -> None:
        selector = self.query_one(PermissionPrompt)
        if selector.display:
            selector.query_one(OptionList).focus()
        else:
            self.query_one("#prompt", Input).focus()

    async def on_permission_prompt_answered(self, event: PermissionPrompt.Answered) -> None:
        tab = self.active_tab()
        if tab is None or not tab.question or not tab.run_id:
            return
        try:
            await self.api.reply(tab.run_id, event.answer)
        except ApiError as e:
            self.notify(e.message, severity="error")
            return
        tab.question = None
        self._update_prompt()
        self.query_one("#prompt", Input).focus()

    def on_permission_prompt_type_reply(self, event: PermissionPrompt.TypeReply) -> None:
        self._focus_default()

    # -- live events -------------------------------------------------------

    async def on_agent_event(self, agent_id: int, event: str, payload: dict) -> None:
        run_id = payload.get("run_id")
        tab = next((t for t in self.tabs.values() if t.run_id == run_id and t.agent_id == agent_id), None)
        if tab is None:
            self.refresh_sessions()
            return
        if event == "tool_result":
            self._learn_permission(tab, payload.get("name"), text_of(payload.get("content")))
        if event == "waiting_for_user":
            tab.question = payload.get("question")
        elif event in ("completed", "error") or (event == "tool_result" and payload.get("name") == "ask_human"):
            tab.question = None
        if event == "llm_response":
            tab.last_assistant = text_of(payload.get("content")).strip()
        if event == "completed":
            output = text_of(payload.get("output")).strip()
            if output and output == tab.last_assistant:
                payload = {**payload, "output": ""}
        if tab.loaded:
            self.log_lines(tab, event_lines(event, payload, tab.permissions))
        self._update_prompt()
        if event in ("completed", "error", "waiting_for_user", "agent_started"):
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
                await self.api.reply(tab.run_id, expand_answer(text))
                tab.question = None
                self._update_prompt()
            except ApiError as e:
                self.log_line(tab, f"[red]{e.message}[/red]")
            return
        await self.send(tab, text)

    def _gard_for(self, agent_id: int | None) -> int | None:
        space = self.current_space
        return space if space and space != NO_GARD else None

    async def send(self, tab: Tab, text: str) -> None:
        session = self.sessions.get(tab.session_id) or {}
        gard = session.get("gard_id") or None
        try:
            run_id = await self.api.send_message(tab.agent_id, text, conversation_key=tab.key, gard_id=gard)
        except ApiError as e:
            self.log_line(tab, f"[red]{e.message}[/red]")
            return
        tab.run_id = run_id
        tab.shown_user_run = run_id
        self.log_lines(tab, ["", f"[b green]›[/] {text}"])

    def _agent_for_space(self) -> int | None:
        """The agent a new session in the current space talks to: this
        worker's agent in this checkout, else the space's most recent agent."""
        if self.current_space == self.gard_id and self.agent_id is not None:
            return self.agent_id
        space = self.spaces.get(self.current_space) if self.current_space is not None else None
        if space and space.sessions:
            return space.sessions[0]["agent_id"]
        return self.agent_id

    async def start_session(self, text: str) -> None:
        if self.agent_id is None:
            await self._learn_agent_and_gards()
        agent_id = self._agent_for_space()
        if agent_id is None:
            self.notify(f"agent {self.agent_name} is not registered yet; is the worker running?", severity="error")
            return
        key = f"sleipnir-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            await self.api.send_message(agent_id, text, conversation_key=key, gard_id=self._gard_for(agent_id))
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
        elif cmd == "/spaces":
            try:
                gards = await self.api.gards()
            except ApiError as e:
                self.notify(e.message, severity="error")
                return
            self.log_lines(tab, spaces_lines(gards, list(self.sessions.values()), self.gard_id))
        elif cmd == "/resume":
            if tab is None:
                self.notify("no session open")
                return
            await self.resume(tab)
        elif cmd == "/close":
            await self.close_active_tab()
        elif cmd == "/archive":
            await self.archive_active_session(force="force" in args)
        elif cmd == "/archived":
            await self.show_archive()
        elif cmd == "/restore":
            if not args or not args[0].isdigit():
                self.notify("which one? /archived lists them with their ids", severity="warning")
                return
            await self.restore_archived(int(args[0]))
        elif cmd == "/delete":
            await self.delete_active_session()
        elif cmd == "/start":
            self.start_worker_here()
        elif cmd in ("/close-space", "/close_space"):
            self.ask_close_space(force="force" in args)
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
                    self.sessions[s["id"]] = s
                    await self.open_session(s, replay=True)
                    break
            self.refresh_sessions()
        else:
            self.notify(f"unknown command {cmd}; try /help", severity="warning")

    async def archive_active_session(self, *, force: bool = False) -> None:
        """Put the current session away. The tab goes, and unlike /close it
        does not come back on restart — but nothing is deleted, and
        /archived brings it back."""
        tabs = self.query_one("#tabs", TabbedContent)
        pane_id = tabs.active
        tab = self.tabs.get(pane_id or "")
        if tab is None or tab.session_id == 0:
            self.notify("no session to archive", severity="warning")
            return
        try:
            await self.api.archive_session(tab.session_id, force=force)
        except ApiError as e:
            if e.status == 409:
                self.notify(f"{e.message} — /archive force", severity="warning")
            else:
                self.notify(e.message, severity="error")
            return
        self.sessions.pop(tab.session_id, None)
        self.tabs.pop(pane_id, None)
        await tabs.remove_pane(pane_id)
        self.spaces = self._group_spaces(list(self.sessions.values()))
        await self._render_sidebar()
        self.notify(f"archived “{tab.title}” — /archived to see it")
        self._focus_default()
        self.refresh_sessions()

    async def show_archive(self) -> None:
        """`/archived`: the sessions put away, newest first, each with the
        command that brings it back."""
        tab = self.tabs.get(self.query_one("#tabs", TabbedContent).active or "")
        try:
            archived = await self.api.sessions(archived=True)
        except ApiError as e:
            self.notify(e.message, severity="error")
            return
        self.log_lines(tab, archived_lines(archived))

    async def restore_archived(self, session_id: int) -> None:
        """`/restore N`: take a session back out of the archive and open it."""
        try:
            session = await self.api.restore_session(session_id)
        except ApiError as e:
            self.notify(e.message, severity="error")
            return
        self.sessions[session["id"]] = session
        self.closed_sessions.discard(session["id"])
        self.spaces = self._group_spaces(list(self.sessions.values()))
        await self._render_sidebar()
        await self.open_session(session, replay=True)
        self.notify(f"restored “{session.get('first_message') or session['id']}”"[:60])
        self.refresh_sessions()

    async def delete_active_session(self) -> None:
        """Two /delete within ten seconds remove the session from Norns."""
        tabs = self.query_one("#tabs", TabbedContent)
        pane_id = tabs.active
        tab = self.tabs.get(pane_id or "")
        if tab is None or tab.session_id == 0:
            self.notify("no session to delete", severity="warning")
            return
        armed = self._delete_armed
        if not armed or armed[0] != pane_id or time.monotonic() - armed[1] > 10:
            self._delete_armed = (pane_id, time.monotonic())
            self.notify(f"delete “{tab.title}” from Norns? type /delete again to confirm", severity="warning")
            return
        self._delete_armed = None
        try:
            await self.api.delete_session(tab.agent_id, tab.key)
        except ApiError as e:
            self.notify(e.message, severity="error")
            return
        self.sessions.pop(tab.session_id, None)
        self.tabs.pop(pane_id, None)
        await tabs.remove_pane(pane_id)
        self.spaces = self._group_spaces(list(self.sessions.values()))
        await self._render_sidebar()
        self.notify(f"deleted “{tab.title}”")
        self.refresh_sessions()

    def start_worker_here(self) -> None:
        """Start a worker for the selected space, if its checkout is on this
        machine. A space whose worker has stopped looks exactly like one
        that is working — it just never answers."""
        gid = self.current_space
        if gid is None or gid == NO_GARD:
            self.notify("that is not a space with a checkout", severity="warning")
            return

        from sleipnir import daemon
        from sleipnir import gard as gard_store

        name = self.gard_names.get(gid, f"gard {gid}")
        root = gard_store.root_of(self.api.url, gid)
        if root is None:
            self.notify(
                f"“{name}” is not a checkout on this machine; start `sleip` there instead",
                severity="warning",
            )
            return
        pid, message = daemon.start(root)
        self.notify(f"{name}: {message}", severity="information" if pid else "error")
        self.refresh_sessions()

    def action_close_space(self) -> None:
        self.ask_close_space()

    def ask_close_space(self, *, force: bool = False) -> None:
        """Closing a space reaches machines the user cannot see, so it asks
        in a screen of its own rather than in a line of the log."""
        gid = self.current_space
        if gid is None or gid == NO_GARD:
            self.notify("that is not a space you can close", severity="warning")
            return
        name = self.gard_names.get(gid, f"gard {gid}")
        count = len(self.spaces[gid].sessions) if gid in self.spaces else 0
        self.push_screen(
            ConfirmClose(name, count, gid == self.gard_id),
            lambda confirmed: self.close_space(gid, name, force=force) if confirmed else None,
        )

    @work(group="close-space")
    async def close_space(self, gid: int, name: str, *, force: bool = False) -> None:
        """Destroy the space's gard. Norns kicks every worker claiming it,
        on this machine and any other, so it closes everywhere."""
        try:
            await self.api.destroy_gard(gid, force=force)
        except ApiError as e:
            if e.status == 409:
                self.notify(f"{e.message} — /close-space force", severity="error")
            else:
                self.notify(e.message, severity="error")
            return

        from sleipnir import gard as gard_store

        gard_store.forget(gid)
        self.closed_gards.add(gid)
        self.sessions = {i: x for i, x in self.sessions.items() if (x.get("gard_id") or NO_GARD) != gid}
        self.spaces = self._group_spaces(list(self.sessions.values()))
        self.current_space = next(iter(self.spaces), None)
        await self._render_sidebar()
        await self._sync_tabs(reset=True)
        if gid == self.gard_id:
            self.notify(f"closed “{name}”. this checkout has no space now; restart sleip for a new one")
        else:
            self.notify(f"closed “{name}”")
        self.refresh_sessions()

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
        self.sessions[session["id"]] = session
        await self.open_session(session, replay=True)

    def action_close_tab(self) -> None:
        self.run_worker(self.close_active_tab(), exclusive=False)

    async def close_active_tab(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        pane_id = tabs.active
        if not pane_id or pane_id not in self.tabs:
            return
        self.tabs.pop(pane_id, None)
        await tabs.remove_pane(pane_id)
        if pane_id != "new" and pane_id.startswith("s"):
            # Closed tabs stay closed until the space is re-selected: the
            # session is still on the server, so the next poll would
            # otherwise bring it straight back.
            sid = int(pane_id[1:])
            self.closed_sessions.add(sid)
            space = self.spaces.get(self.current_space)
            if space:
                space.sessions = [s for s in space.sessions if s["id"] != sid]
        self._focus_default()

    def set_tab_title(self, pane_id: str, title: str) -> None:
        try:
            self.query_one("#tabs", TabbedContent).get_tab(pane_id).label = title
        except Exception:
            pass

    def action_new_session(self) -> None:
        self.run_worker(self.new_tab(), exclusive=False)

    async def new_tab(self) -> None:
        """An empty tab in this space: the next line typed into it starts a session."""
        tabs = self.query_one("#tabs", TabbedContent)
        if "new" not in self.tabs:
            self.tabs["new"] = Tab(session_id=0, agent_id=self.agent_id or 0, key="", loaded=True)
            log = RichLog(wrap=True, markup=True, highlight=False, id="log-new")
            await tabs.add_pane(TabPane("new", log, id="new"))
            space = self.spaces.get(self.current_space)
            where = space.name if space else self.root.name
            log.write(f"[dim]a new session in {where}; type to start it[/dim]")
        tabs.active = "new"
        self._focus_default()

    def action_open_url(self, url: str) -> None:
        """A run in the transcript, opened in the dashboard.

        Textual resolves the action `app.open_url(...)` to this; App has a
        plain open_url method, which an action string never reaches.
        """
        self.open_url(url)

    def action_refresh(self) -> None:
        self.refresh_sessions()

    # -- output ------------------------------------------------------------

    def log_lines(self, tab: Tab | None, lines: list[str]) -> None:
        for line in lines:
            self.log_line(tab, line)

    def log_line(self, tab: Tab | None, line) -> None:
        target = f"#log-{tab.session_id}" if tab and tab.session_id else "#log-new"
        if isinstance(line, Md):
            line = Markdown(line.text, code_theme="monokai")
        try:
            self.query_one(target, RichLog).write(line)
        except Exception:
            if tab is None:
                self.set_status(line)

    KEYS = "[dim]^n[/] new  [dim]^w[/] close  [dim]^g[/] close space  [dim]^r[/] refresh  [dim]^q[/] quit"

    def set_status(self, text: str) -> None:
        try:
            self.query_one("#state", Static).update(text)
        except Exception:
            pass
