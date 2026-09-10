"""Text for the session list and the chat pane. Content is rendered here,
in the client, never by Norns."""

from __future__ import annotations

import json
from typing import Any

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
    first = text_of(session.get("first_message")).strip().splitlines()
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


def first_line(text: str, width: int = 100) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[: width - 1] + "…"


def message_lines(msg: dict) -> list[str]:
    """A stored message as chat lines, Rich markup."""
    role = msg.get("role")
    content = text_of(msg.get("content"))
    kind = msg.get("kind")
    if role == "user":
        if kind == "inherited_context":
            return ["", "[dim]· inherited context[/dim]"]
        return ["", f"[b green]›[/] {escape(content)}"]
    if role == "assistant":
        lines = ["", escape(content)] if content.strip() else []
        for tc in msg.get("tool_calls") or []:
            lines.append(f"[cyan]⚙ {escape(tc.get('name', '?'))}[/] {escape(tool_summary(tc.get('name', ''), tc.get('arguments')))}")
        return lines
    if role == "tool":
        if msg.get("name") == "ask_human":
            return [f"[yellow]?[/] answered: {escape(first_line(content))}"]
        if kind:
            return [f"  [dim]↳ {escape(kind)}[/dim]"]
        marker = "[red]↳[/]" if msg.get("is_error") else "[dim]↳[/dim]"
        return [f"  {marker} [dim]{escape(first_line(content))}[/dim]"]
    return [escape(content)] if content else []


def event_lines(event: str, payload: dict) -> list[str]:
    """A live channel event as chat lines, Rich markup."""
    if event == "agent_started":
        return [f"[dim]— run {payload.get('run_id')} started —[/dim]"]
    if event == "llm_response":
        lines = []
        content = text_of(payload.get("content"))
        if content.strip():
            lines += ["", escape(content)]
        for tc in payload.get("tool_calls") or []:
            lines.append(f"[cyan]⚙ {escape(tc.get('name', '?'))}[/] {escape(tool_summary(tc.get('name', ''), tc.get('arguments')))}")
        return lines
    if event == "tool_result":
        content = text_of(payload.get("content"))
        if payload.get("name") == "ask_human":
            return [f"[yellow]?[/] answered: {escape(first_line(content))}"]
        marker = "[red]↳[/]" if payload.get("is_error") else "[dim]↳[/dim]"
        return [f"  {marker} [dim]{escape(payload.get('name', ''))}: {escape(first_line(content))}[/dim]"]
    if event == "waiting_for_user":
        return ["", f"[yellow b]? {escape(text_of(payload.get('question')))}[/]", "[yellow]  type your answer below[/yellow]"]
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
