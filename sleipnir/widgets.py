"""The permission selector: what appears when the agent wants to run
something the allow list does not cover."""

from __future__ import annotations

from rich.markup import escape
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

CHOICES = [("yes", "Allow once"), ("always", "Always allow  (adds a rule to .sleipnir/allow)"), ("no", "Deny")]


class PermissionPrompt(Vertical):
    DEFAULT_CSS = """
    PermissionPrompt { height: auto; margin: 0 1; padding: 0 1; border: round $warning; }
    PermissionPrompt #perm-title { height: auto; }
    PermissionPrompt OptionList { height: auto; border: none; padding: 0; margin: 0; background: transparent; }
    PermissionPrompt #perm-hint { height: 1; color: $text-muted; }
    """

    BINDINGS = [
        Binding("y", "answer('yes')", "Allow once", show=False),
        Binding("a", "answer('always')", "Always", show=False),
        Binding("n", "answer('no')", "Deny", show=False),
        Binding("escape", "type_reply", "Type a reply", show=False),
    ]

    class Answered(Message):
        def __init__(self, answer: str) -> None:
            super().__init__()
            self.answer = answer

    class TypeReply(Message):
        pass

    def __init__(self) -> None:
        super().__init__(id="permission")
        self.display = False
        self.tool = ""
        self.subject = ""

    def compose(self):
        yield Static("", id="perm-title", markup=True)
        yield OptionList(*[Option(label, id=answer) for answer, label in CHOICES], id="perm-options")
        yield Static("[dim]↑↓ enter · y / a / n · esc to type a reply[/dim]", id="perm-hint", markup=True)

    def show(self, tool: str, subject: str) -> None:
        self.tool, self.subject = tool, subject
        lines = subject.splitlines() or [""]
        shown = "\n".join(escape(line) for line in lines[:6]) + ("\n…" if len(lines) > 6 else "")
        self.query_one("#perm-title", Static).update(f"[b yellow]{escape(tool)}[/] wants to run\n{shown}")
        self.display = True
        options = self.query_one(OptionList)
        options.highlighted = 0
        options.focus()

    def hide(self) -> None:
        self.display = False

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.post_message(self.Answered(str(event.option.id)))

    def action_answer(self, answer: str) -> None:
        self.post_message(self.Answered(answer))

    def action_type_reply(self) -> None:
        self.post_message(self.TypeReply())
