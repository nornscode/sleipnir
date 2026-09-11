"""The permission selector: what appears when the agent wants to run
something the allow list does not cover."""

from __future__ import annotations

from rich.markup import escape
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
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


class ConfirmClose(ModalScreen[bool]):
    """Closing a space stops its worker on machines you are not looking at,
    so it asks in front of everything, and the safe answer is the one under
    the cursor."""

    DEFAULT_CSS = """
    ConfirmClose { align: center middle; background: $background 60%; }
    ConfirmClose > Vertical {
        width: 64; height: auto; padding: 1 2; background: $surface; border: round $error;
    }
    ConfirmClose #confirm-title { height: auto; }
    ConfirmClose OptionList { height: auto; border: none; padding: 0; margin: 1 0 0 0; background: transparent; }
    ConfirmClose #confirm-hint { height: 1; color: $text-muted; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, name: str, sessions: int, here: bool) -> None:
        super().__init__()
        self.space_name = name
        self.sessions = sessions
        self.here = here

    def compose(self):
        with Vertical():
            what = [f"Close [b]{escape(self.space_name)}[/b]?"]
            what.append("Its worker stops wherever it is running, and the space")
            what.append("leaves every client — not just this one.")
            if self.sessions:
                s = "" if self.sessions == 1 else "s"
                what.append(
                    f"Its {self.sessions} session{s} stay in Norns, but nothing can serve"
                )
                what.append("them again.")
            if self.here:
                what.append("This is this checkout's own space; sleip needs a restart")
                what.append("afterwards for a new one.")
            yield Static("\n".join(what), id="confirm-title", markup=True)
            yield OptionList(
                Option("Keep it", id="cancel"),
                Option("Close the space", id="close"),
                id="confirm-options",
            )
            yield Static("[dim]↑↓ enter · esc to keep it[/dim]", id="confirm-hint", markup=True)

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        options.highlighted = 0  # "Keep it": enter alone never closes a space
        options.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(str(event.option.id) == "close")

    def action_cancel(self) -> None:
        self.dismiss(False)
