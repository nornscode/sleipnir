"""Text for the session list and the chat pane. Content is rendered here,
in the client, never by Norns."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from rich.markup import escape
from rich.style import Style
from rich.text import Text

@dataclass(frozen=True)
class Md:
    """Assistant prose: rendered as Markdown by the pane, not as markup."""

    text: str


STATUS_GLYPH = {
    "idle": ("○", "dim"),
    "running": ("◐", "cyan"),
    "awaiting_llm": ("◐", "cyan"),
    "awaiting_tools": ("◑", "cyan"),
    "waiting": ("●", "yellow"),
    "waiting_timer": ("◔", "dim"),
    "stopped": ("○", "dim"),
    "unknown": ("?", "dim"),
}

STATUS_WORD = {
    "idle": "idle",
    "running": "thinking",
    "awaiting_llm": "thinking",
    "awaiting_tools": "running tools",
    "waiting": "needs you",
    "waiting_timer": "sleeping",
    "stopped": "idle",
    "unknown": "?",
}


def text_of(content: Any) -> str:
    """Content as text. An opaque block shows as [encrypted] until E3.

    A message can be a list of blocks — that is how an image reaches the
    model — and its text is the text blocks. An image is named, not
    printed: nobody wants a megabyte of base64 in their transcript.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict) and "$enc" in content:
        return "[encrypted]"
    if isinstance(content, list):
        parts = [block_text(b) for b in content]
        return "\n".join(p for p in parts if p)
    try:
        return json.dumps(content)
    except (TypeError, ValueError):
        return str(content)


def block_text(block: Any) -> str:
    """One content block as a line of transcript."""
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return text_of(block)
    if block.get("type") == "text":
        return text_of(block.get("text"))
    if block.get("type") == "image_url":
        return f"🖼 {block.get('name') or 'image'}"
    return text_of(block)


def title_of(session: dict) -> str:
    """The name the user gave it; else the first user turn; after a
    compaction has folded that away, the summary's first line; failing all
    three, the key."""
    named = text_of(session.get("title")).strip()
    if named:
        return named if len(named) <= 48 else named[:47] + "…"
    first = text_of(session.get("first_message")).strip().splitlines()
    if not first:
        first = text_of(session.get("summary")).strip().splitlines()
    if not first:
        # A run still in flight has not been written to the conversation yet.
        first = text_of(((session.get("run") or {}).get("input") or {}).get("user_message")).strip().splitlines()
    title = first[0] if first else session.get("key") or f"session {session.get('id')}"
    return title if len(title) <= 48 else title[:47] + "…"


NO_WORKER = ("pending", "disconnected")


# A space is a place on disk; a session is a conversation in it. Outlined
# geometry could not tell them apart — ▢ beside ○ is one small hollow shape
# beside another in a mono font — so the kind is an emoji, which differs in
# weight and colour and not just in outline. State is carried by the colour
# of the text beside it, so the icon never has to mean two things.
SPACE_ICON = "📁"
SESSION_ICON = "💬"


def space_row(name: str, sessions: list[dict], status: str | None = None, *, here: bool = False) -> str:
    """A space as one line of a tree: what it is, and what it is doing."""
    if status in NO_WORKER:
        # Two situations, not one: the remedy exists only when the checkout
        # is on this machine, and saying so is what stops a fruitless /start.
        remedy = "— /start" if here else "· elsewhere"
        return f"{SPACE_ICON} [b red]{escape(name)}[/] [red]no worker {remedy}[/]"
    waiting = sum(1 for s in sessions if (s.get("run") or {}).get("status") == "waiting")
    working = sum(1 for s in sessions if s.get("status") in ("running", "awaiting_llm", "awaiting_tools"))
    if waiting:
        return f"{SPACE_ICON} [b]{escape(name)}[/b] [yellow]{waiting} need you[/]"
    if working:
        return f"{SPACE_ICON} [b]{escape(name)}[/b] [cyan]{working} working[/]"
    return f"{SPACE_ICON} [b]{escape(name)}[/b] [dim]{len(sessions)}[/dim]"


# What a session's own state colours its line: nothing for the quiet ones,
# so the two that want the eye are the only two that get it.
SESSION_COLOUR = {
    "running": "cyan", "awaiting_llm": "cyan", "awaiting_tools": "cyan",
    "waiting": "yellow",
}


def session_row(session: dict, width: int = 24) -> str:
    """A session as one line under its space: what it is about, and what it
    is doing right now."""
    status = session.get("status") or "stopped"
    run = session.get("run") or {}
    if status in ("stopped", "idle") and run.get("status") == "waiting":
        status = "waiting"
    title = title_of(session)
    if len(title) > width:
        title = title[: width - 1] + "…"
    colour = SESSION_COLOUR.get(status)
    body = f"[{colour}]{escape(title)}[/]" if colour else escape(title)
    return f"{SESSION_ICON} {body}"


GARD_STATE = {
    "ready": ("●", "green", "worker connected"),
    "pending": ("○", "dim", "no worker yet"),
    "disconnected": ("○", "red", "worker gone"),
    "destroyed": ("✗", "red", "destroyed"),
}


def spaces_lines(gards: list[dict], sessions: list[dict], here: int | None) -> list[str]:
    """`/spaces`: every gard with whether a worker is in it, and its sessions."""
    by_gard: dict[int, list[dict]] = {}
    for s in sessions:
        by_gard.setdefault(s.get("gard_id") or 0, []).append(s)
    lines = ["", "[b]spaces[/b]  (a space is a checkout with `sleip` running in it)"]
    for g in sorted(gards, key=lambda g: (g["id"] != here, g.get("status") != "ready", g.get("name") or "")):
        glyph, colour, word = GARD_STATE.get(g.get("status"), ("?", "dim", g.get("status") or "?"))
        own = by_gard.get(g["id"], [])
        working = sum(1 for s in own if s.get("status") in ("running", "awaiting_llm", "awaiting_tools"))
        waiting = sum(1 for s in own if (s.get("run") or {}).get("status") == "waiting")
        counts = f"{len(own)} session{'s' if len(own) != 1 else ''}"
        if working:
            counts += f", {working} working"
        if waiting:
            counts += f", {waiting} need you"
        mark = "  [dim]← this checkout[/dim]" if g["id"] == here else ""
        lines.append(f"  [{colour}]{glyph}[/] [b]{escape(g.get('name') or str(g['id']))}[/b]  [dim]{word} · {counts}[/dim]{mark}")
    loose = by_gard.get(0, [])
    if loose:
        lines.append(f"  [dim]○[/] [b]no gard[/b]  [dim]{len(loose)} session{'s' if len(loose) != 1 else ''} served by any worker without a gard[/dim]")
    lines.append("[dim]  start a space: run `sleip` in another repository (or `sleip serve` on another machine)[/dim]")
    return lines


def archived_lines(sessions: list[dict]) -> list[str]:
    """`/archived`: what you have put away, and how to get it back."""
    if not sessions:
        return ["", "[dim]nothing archived. /archive puts the session you are in away.[/dim]"]
    lines = ["", f"[b]archived[/b]  [dim]{len(sessions)} session{'s' if len(sessions) != 1 else ''}, newest first[/dim]"]
    for s in sessions:
        when = text_of(s.get("archived_at"))[:10]
        agent = escape(text_of(s.get("agent_name")))
        lines.append(f"  [dim]{s['id']:>5}[/dim]  {escape(title_of(s))}  [dim]{agent} · {when}[/dim]")
    lines.append("[dim]  /restore <id> opens one again · nothing here is deleted[/dim]")
    return lines


def tool_summary(name: str, arguments: Any) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    if name == "bash":
        return text_of(args.get("command"))
    if name in ("read_file", "write_file", "edit_file"):
        return text_of(args.get("path"))
    if name == "grep":
        return f"/{text_of(args.get('pattern'))}/ in {text_of(args.get('path') or '.')}"
    if name == "glob":
        return text_of(args.get("pattern"))
    if name == "ask_human":
        return text_of(args.get("question"))
    if name == "launch_agent":
        return text_of(args.get("agent_name") or args.get("agent"))
    return text_of(args) if args else ""


PERMISSION_RE = re.compile(r"\Apermission required \(token (p-[0-9a-f]{6})\)\n(\w+): (.*?)(?:\n\n|\Z)", re.DOTALL)
TOKEN_RE = re.compile(r"\bp-[0-9a-f]{6}\b")
QUESTION_RE = re.compile(r"[Aa]llow (\w+) `(.+?)`\?")
ANSWER_SHORTCUTS = {"y": "yes", "a": "always", "n": "no"}


def permission_request(content: str) -> bool:
    return content.startswith("permission required (token ")


def permission_details(content: str) -> tuple[str, str, str] | None:
    """(token, tool, subject) from the worker's own permission request."""
    m = PERMISSION_RE.match(content)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def permission_in_question(question: str, known: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    """The action a question is about: from the worker's request whose
    token the question quotes, else from the question's own wording."""
    for token in TOKEN_RE.findall(question):
        if token in known:
            return known[token]
    m = QUESTION_RE.search(question)
    return (m.group(1), m.group(2)) if m else None


def question_lines(question: str, known: dict[str, tuple[str, str]] | None = None) -> list[str]:
    """A question to you. A permission request renders as one, without
    the token the worker and the model pass between themselves."""
    action = permission_in_question(question, known or {})
    if action is None:
        return ["", f"[yellow b]? {escape(question)}[/]"]
    tool, subject = action
    lines = ["", f"[yellow b]⚠ {escape(tool)} wants to run[/]"]
    lines += [f"[yellow]    {escape(line)}[/]" for line in subject.splitlines()[:8]]
    if len(subject.splitlines()) > 8:
        lines.append("[yellow]    …[/]")
    return lines


def expand_answer(text: str) -> str:
    return ANSWER_SHORTCUTS.get(text.strip().lower(), text)


def first_line(text: str, width: int = 100) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[: width - 1] + "…"


def result_summary(content: str, width: int = 100) -> str:
    """One line describing a result of any size.

    Showing the first line alone made a search over hundreds of files
    render one arbitrary path as though it were the answer. A count is
    both shorter and true; a single-line result still reads as itself.
    """
    lines = [line for line in content.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) == 1:
        return first_line(lines[0], width)
    head = first_line(lines[0], max(20, width - 18))
    return f"{head}  (+{len(lines) - 1} more)"


def message_lines(msg: dict, known: dict[str, tuple[str, str]] | None = None) -> list[str]:
    """A stored message as chat lines, Rich markup. `known` maps permission
    tokens to (tool, subject), learned from earlier tool results."""
    role = msg.get("role")
    content = text_of(msg.get("content"))
    kind = msg.get("kind")
    if role == "user":
        if kind == "inherited_context":
            return ["", "[dim]· inherited context[/dim]"]
        return ["", f"[b green]›[/] {escape(content)}"]
    if role == "assistant":
        lines = ["", Md(content)] if content.strip() else []
        lines += tool_call_lines(msg.get("tool_calls") or [], known)
        return lines
    if role == "tool":
        return tool_result_lines(msg.get("name", ""), content, kind, bool(msg.get("is_error")))
    return [escape(content)] if content else []


def tool_call_lines(tool_calls: list[dict], known: dict[str, tuple[str, str]] | None = None) -> list[str]:
    """One line per tool call. A question to you is not a tool call as far
    as the chat is concerned: it shows when it is asked (waiting_for_user)."""
    lines = []
    for tc in tool_calls:
        name = tc.get("name", "?")
        if name == "ask_human":
            lines += question_lines(tool_summary(name, tc.get("arguments")), known)
        else:
            lines.append(f"[cyan]⚙ {escape(name)}[/] {escape(tool_summary(name, tc.get('arguments')))}")
    return lines


def tool_result_lines(name: str, content: str, kind: str | None = None, is_error: bool = False) -> list[str]:
    """One line per result. Your answer to a question shows as your turn;
    a permission request shows as the question that follows it."""
    if name == "ask_human":
        return ["", f"[b green]›[/] {escape(first_line(content))}"]
    if permission_request(content):
        return []
    if kind:
        return [f"  [dim]↳ {escape(kind)}[/dim]"]
    marker = "[red]↳[/]" if is_error else "[dim]↳[/dim]"
    label = f"{escape(name)}: " if name else ""
    return [f"  {marker} [dim]{label}{escape(result_summary(content))}[/dim]"]


RUN_EVENT_NAMES = {"run_completed": "completed", "run_failed": "error"}
RUN_EVENTS_SHOWN = {"llm_response", "tool_result", "waiting_for_user", "context_compacted", "run_completed", "run_failed"}


def run_event_lines(
    events: list[dict], known: dict[str, tuple[str, str]] | None = None, run_id=None
) -> list[str]:
    """The chat lines of a run's event log: what the conversation row will
    hold once the run finishes. After a compaction only the events since
    it count, because the compacted history is already on the row."""
    last_compaction = max((i for i, e in enumerate(events) if e.get("event_type") == "context_compacted"), default=-1)
    lines: list[str] = []
    for e in events[last_compaction + 1 :]:
        kind = e.get("event_type", "")
        if kind not in RUN_EVENTS_SHOWN:
            continue
        payload = e.get("payload") or {}
        if kind == "run_failed":
            payload = {"error": payload.get("error")}
        if run_id and kind in ("run_completed", "run_failed"):
            payload = {**payload, "run_id": run_id}
        lines += event_lines(RUN_EVENT_NAMES.get(kind, kind), payload, known)
    return lines


# Where this client's Norns serves its dashboard. The transcript is the
# envelope; the run page is the whole log, and it is one click away.
WEB_BASE = ""


def set_web_base(url: str) -> None:
    global WEB_BASE
    WEB_BASE = (url or "").rstrip("/")


def run_link(run_id, label: str | None = None) -> Text:
    """A run, as something you can click through to.

    Rich's own [link=] sets a terminal hyperlink, which Textual does not
    act on — so the click is an action in the app, and the OSC 8 link is
    set too for terminals that handle those themselves.
    """
    label = label or f"run {run_id}"
    if not WEB_BASE or not run_id:
        return Text(label, style="dim")
    url = f"{WEB_BASE}/runs/{run_id}"
    return Text(label, style=Style(meta={"@click": f"app.open_url({url!r})"}, link=url, dim=True, underline=True))


def with_link(markup: str, run_id) -> Text:
    """A rendered line with the run it belongs to on the end of it."""
    line = Text.from_markup(markup)
    if run_id:
        line.append("  ")
        line.append_text(run_link(run_id))
    return line


def ended_lines(run: dict) -> list[str]:
    """How a finished run reads when its history came from the conversation
    row rather than from its own events — the ending, which the row does
    not record. The output is left out: it is already the last assistant
    message on the row."""
    status = run.get("status")
    if status == "failed":
        return event_lines("error", {
            "error": (run.get("failure_metadata") or {}).get("error") or "run failed",
            "run_id": run.get("id"),
        })
    if status == "completed":
        return event_lines("completed", {"output": "", "run_id": run.get("id")})
    return []


def event_lines(event: str, payload: dict, known: dict[str, tuple[str, str]] | None = None) -> list[str]:
    """A live channel event as chat lines, Rich markup."""
    if event == "agent_started":
        started = Text.from_markup("[dim]— [/dim]")
        started.append_text(run_link(payload.get("run_id")))
        started.append_text(Text.from_markup("[dim] started —[/dim]"))
        return [started]
    if event == "llm_response":
        lines = []
        content = text_of(payload.get("content"))
        if content.strip():
            lines += ["", Md(content)]
        # The question itself arrives as waiting_for_user right after.
        lines += tool_call_lines([tc for tc in payload.get("tool_calls") or [] if tc.get("name") != "ask_human"])
        if payload.get("finish_reason") == "length":
            # The turn hit the response ceiling: it is not wrong, it stops
            # mid-thought, and nothing else would say so.
            lines += ["", "[yellow]⚠ cut off at the response limit — ask it to carry on, "
                          "or raise max_tokens with `sleip config set max_tokens`[/yellow]"]
        return lines
    if event == "tool_result":
        return tool_result_lines(payload.get("name", ""), text_of(payload.get("content")), None, bool(payload.get("is_error")))
    if event == "waiting_for_user":
        return question_lines(text_of(payload.get("question")), known)
    if event == "waiting_timer":
        return [f"[dim]◔ waiting {payload.get('seconds')}s[/dim]"]
    if event == "completed":
        out = text_of(payload.get("output")).strip()
        done = with_link("[green]✓ done[/green]", payload.get("run_id"))
        return (["", Md(out)] if out else []) + ["", done]
    if event == "error":
        failed = with_link(f"[red]✗ {escape(text_of(payload.get('error')))}[/red]", payload.get("run_id"))
        return [failed]
    if event == "context_compacted":
        return [f"[dim]… compacted {payload.get('dropped')} messages into the summary[/dim]"]
    if event == "agent_resumed":
        return [f"[dim]— resumed —[/dim]"]
    return []
