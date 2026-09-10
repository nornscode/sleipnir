"""Text for the session list and the chat pane. Content is rendered here,
in the client, never by Norns."""

from __future__ import annotations

import json
from typing import Any

import re

from rich.markup import escape

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
    """Content as text. An opaque block shows as [encrypted] until E3."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict) and "$enc" in content:
        return "[encrypted]"
    try:
        return json.dumps(content)
    except (TypeError, ValueError):
        return str(content)


def title_of(session: dict) -> str:
    """The first user turn; after a compaction has folded it away, the
    summary's first line; failing both, the key."""
    first = text_of(session.get("first_message")).strip().splitlines()
    if not first:
        first = text_of(session.get("summary")).strip().splitlines()
    if not first:
        # A run still in flight has not been written to the conversation yet.
        first = text_of(((session.get("run") or {}).get("input") or {}).get("user_message")).strip().splitlines()
    title = first[0] if first else session.get("key") or f"session {session.get('id')}"
    return title if len(title) <= 48 else title[:47] + "…"


def session_label(session: dict, gard_names: dict[int, str] | None = None) -> str:
    """One sidebar row, Rich markup."""
    status = session.get("status") or "stopped"
    run = session.get("run") or {}
    if status in ("stopped", "idle") and run.get("status") == "waiting":
        status = "waiting"
    glyph, colour = STATUS_GLYPH.get(status, STATUS_GLYPH["unknown"])
    where = session.get("agent_name") or f"agent {session.get('agent_id')}"
    gard_id = session.get("gard_id")
    if gard_id and gard_names and gard_id in gard_names:
        where = f"{where} @ {gard_names[gard_id]}"
    return f"[{colour}]{glyph}[/] [b]{escape(title_of(session))}[/b]\n  [dim]{escape(where)} · {STATUS_WORD.get(status, status)}[/dim]"


def space_label(name: str, sessions: list[dict]) -> str:
    """One sidebar row for a space: its name and what its sessions are doing."""
    working = sum(1 for s in sessions if s.get("status") in ("running", "awaiting_llm", "awaiting_tools"))
    waiting = sum(1 for s in sessions if (s.get("run") or {}).get("status") == "waiting")
    if waiting:
        glyph, colour = "●", "yellow"
    elif working:
        glyph, colour = "◐", "cyan"
    else:
        glyph, colour = "○", "dim"
    parts = [f"{len(sessions)} session{'s' if len(sessions) != 1 else ''}"]
    if working:
        parts.append(f"{working} working")
    if waiting:
        parts.append(f"{waiting} need you")
    return f"[{colour}]{glyph}[/] [b]{escape(name)}[/b]\n  [dim]{' · '.join(parts)}[/dim]"


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
    lines.append("[dim]  y allow once · a always allow · n deny · or type a reply[/dim]")
    return lines


def expand_answer(text: str) -> str:
    return ANSWER_SHORTCUTS.get(text.strip().lower(), text)


def first_line(text: str, width: int = 100) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[: width - 1] + "…"


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
        lines = ["", escape(content)] if content.strip() else []
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
    return [f"  {marker} [dim]{label}{escape(first_line(content))}[/dim]"]


RUN_EVENT_NAMES = {"run_completed": "completed", "run_failed": "error"}
RUN_EVENTS_SHOWN = {"llm_response", "tool_result", "waiting_for_user", "context_compacted", "run_completed", "run_failed"}


def run_event_lines(events: list[dict], known: dict[str, tuple[str, str]] | None = None) -> list[str]:
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
        lines += event_lines(RUN_EVENT_NAMES.get(kind, kind), payload, known)
    return lines


def event_lines(event: str, payload: dict, known: dict[str, tuple[str, str]] | None = None) -> list[str]:
    """A live channel event as chat lines, Rich markup."""
    if event == "agent_started":
        return [f"[dim]— run {payload.get('run_id')} started —[/dim]"]
    if event == "llm_response":
        lines = []
        content = text_of(payload.get("content"))
        if content.strip():
            lines += ["", escape(content)]
        # The question itself arrives as waiting_for_user right after.
        lines += tool_call_lines([tc for tc in payload.get("tool_calls") or [] if tc.get("name") != "ask_human"])
        return lines
    if event == "tool_result":
        return tool_result_lines(payload.get("name", ""), text_of(payload.get("content")), None, bool(payload.get("is_error")))
    if event == "waiting_for_user":
        return question_lines(text_of(payload.get("question")), known)
    if event == "waiting_timer":
        return [f"[dim]◔ waiting {payload.get('seconds')}s[/dim]"]
    if event == "completed":
        out = text_of(payload.get("output")).strip()
        return ([""] if out else []) + ([escape(out)] if out else []) + ["", "[green]✓ done[/green]"]
    if event == "error":
        return [f"[red]✗ {escape(text_of(payload.get('error')))}[/red]"]
    if event == "context_compacted":
        return [f"[dim]… compacted {payload.get('dropped')} messages into the summary[/dim]"]
    if event == "agent_resumed":
        return [f"[dim]— resumed —[/dim]"]
    return []
