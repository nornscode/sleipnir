"""The allow list and the ask_human approval loop.

Read-only tools (read_file, grep, glob) never ask; they are confined to
the workspace root. A mutating tool (bash, write_file, edit_file) checks
its subject, the command or the path, against the allow list. Outside
the list it raises PermissionRequired carrying a one-time token. The
model then asks the user with ask_human, quoting the token, the user
answers "yes", "always", or "no", and the model retries the same call
with approval=<token>.

The answer is the user's, not the model's: the worker also serves the
LLM task for the run, so it sees the ask_human result in the messages
before the retry arrives, and records the decision from there. A retry
whose token has no recorded answer is refused. "always" appends a rule to
the allow file so the next matching action does not ask.
"""

from __future__ import annotations

import fnmatch
import re
import secrets
import shlex
from dataclasses import dataclass
from pathlib import Path

READ_ONLY = {"read_file", "grep", "glob"}
MUTATING = {"bash", "write_file", "edit_file"}

TOKEN_RE = re.compile(r"\bp-[0-9a-f]{6}\b")
REQUEST_RE = re.compile(
    r"\Apermission required \(token (p-[0-9a-f]{6})\)\n(\w+): (.*?)\n\n", re.DOTALL
)
SHELL_SEPARATORS = {"&&", "||", ";", ";;", "|", "|&", "&", "(", ")"}
YES_RE = re.compile(r"^(y|yes|yep|yeah|ok|okay|sure|approve|approved|allow|allowed|go ahead|do it)\b")


class PermissionRequired(Exception):
    """Raised by a mutating tool when the action needs the user's answer."""


class PermissionDenied(Exception):
    """Raised when an approval token is unusable or the user said no."""


@dataclass(frozen=True)
class Rule:
    tool: str
    pattern: str

    @classmethod
    def parse(cls, line: str) -> Rule | None:
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        tool, _, pattern = line.partition(" ")
        return cls(tool, pattern.strip() or "*")

    def matches(self, tool: str, subject: str) -> bool:
        return tool == self.tool and fnmatch.fnmatchcase(subject, self.pattern)

    def __str__(self) -> str:
        return f"{self.tool} {self.pattern}"


def shell_segments(command: str) -> list[str]:
    """Split a shell command into the simple commands it runs.

    `git status && rm -rf build` is two segments and each must be
    allowed. Subshells split too, so `echo $(rm -rf /)` exposes the
    inner command. Backticks are not parsed; a command containing one
    always asks.
    """
    if "`" in command:
        return []
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return [command]
    segments: list[str] = []
    current: list[str] = []
    for tok in tokens:
        if tok in SHELL_SEPARATORS or (tok and set(tok) <= set("&|;()")):
            if current:
                segments.append(" ".join(current))
                current = []
        else:
            current.append(tok)
    if current:
        segments.append(" ".join(current))
    return segments or [command]


def subjects(tool: str, subject: str) -> list[str]:
    return shell_segments(subject) if tool == "bash" else [subject]


def rule_for(tool: str, subject: str) -> list[Rule]:
    """The rules an "always" answer adds: the command word for each
    shell segment, or every path for a file tool."""
    if tool != "bash":
        return [Rule(tool, "*")]
    rules = []
    for seg in shell_segments(subject):
        word = seg.split(" ", 1)[0]
        if word:
            rules.append(Rule(tool, f"{word} *"))
            rules.append(Rule(tool, word))
    return rules


def classify(answer) -> str:
    if not isinstance(answer, str):
        return "deny"
    a = answer.strip().lower()
    if a.startswith("always"):
        return "always"
    if YES_RE.match(a):
        return "once"
    return "deny"


def request_message(token: str, tool: str, subject: str) -> str:
    example = f"Allow {tool} `{subject}`? (yes / always / no) [{token}]"
    return (
        f"permission required (token {token})\n"
        f"{tool}: {subject}\n\n"
        "This action is not in the allow list. Do not retry it yet and do not "
        "attempt it another way. Ask the user with ask_human, quoting the "
        "token and the exact action, for example:\n"
        f'  "{example}"\n'
        f'Then call {tool} again with the same arguments and approval="{token}". '
        "If the user says no, do not attempt it another way."
    )


class Permissions:
    def __init__(self, allow_file: Path | None):
        self.allow_file = allow_file
        self.rules: list[Rule] = []
        self.pending: dict[str, tuple[str, str]] = {}
        self.decisions: dict[str, str] = {}
        self.consumed: set[str] = set()
        self.reload()

    # -- allow list --------------------------------------------------------

    def reload(self) -> None:
        self.rules = []
        if self.allow_file and self.allow_file.is_file():
            for line in self.allow_file.read_text().splitlines():
                rule = Rule.parse(line)
                if rule:
                    self.rules.append(rule)

    def add_rules(self, rules: list[Rule]) -> None:
        new = [r for r in rules if r not in self.rules]
        if not new:
            return
        self.rules.extend(new)
        if self.allow_file:
            self.allow_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.allow_file, "a") as f:
                for r in new:
                    f.write(f"{r}\n")

    def allowed(self, tool: str, subject: str) -> bool:
        if tool in READ_ONLY:
            return True
        parts = subjects(tool, subject)
        if not parts:
            return False
        return all(any(r.matches(tool, part) for r in self.rules) for part in parts)

    # -- the approval loop -------------------------------------------------

    def check(self, tool: str, subject: str, approval: str = "") -> None:
        """Return if the action may proceed; raise otherwise."""
        if self.allowed(tool, subject):
            return
        if approval:
            self._apply(tool, subject, approval.strip())
            return
        token = self.request(tool, subject)
        raise PermissionRequired(request_message(token, tool, subject))

    def request(self, tool: str, subject: str) -> str:
        token = "p-" + secrets.token_hex(3)
        self.pending[token] = (tool, subject)
        return token

    def _apply(self, tool: str, subject: str, token: str) -> None:
        issued = self.pending.get(token)
        if issued is None:
            raise PermissionDenied(f"unknown approval token {token}; request permission again")
        if issued != (tool, subject):
            raise PermissionDenied(
                f"approval token {token} was issued for a different action; request permission again"
            )
        if token in self.consumed:
            raise PermissionDenied(f"approval {token} was already used; request permission again")
        decision = self.decisions.get(token)
        if decision is None:
            raise PermissionDenied(
                f"no answer from the user for {token}; ask with ask_human, quoting the token, "
                "and wait for the reply"
            )
        self.consumed.add(token)
        if decision == "deny":
            raise PermissionDenied(f"the user declined {tool}: {subject}")
        if decision == "always":
            self.add_rules(rule_for(tool, subject))

    def observe(self, messages: list[dict]) -> None:
        """Learn pending requests and the user's answers from a run's messages.

        Called with the messages of every LLM task the worker serves.
        Requests are rebuilt from the harness's own tool results, so a
        worker restart between the question and the retry is fine.
        """
        results: dict[str, dict] = {}
        for m in messages:
            if m.get("role") == "tool" and m.get("tool_call_id"):
                results[m["tool_call_id"]] = m

        for m in results.values():
            if m.get("name") in MUTATING and isinstance(m.get("content"), str):
                match = REQUEST_RE.match(m["content"])
                if match:
                    token, tool, subject = match.groups()
                    self.pending.setdefault(token, (tool, subject))

        for m in messages:
            if m.get("role") != "assistant":
                continue
            for tc in m.get("tool_calls") or []:
                if tc.get("name") != "ask_human":
                    continue
                args = tc.get("arguments") or {}
                question = args.get("question", "") if isinstance(args, dict) else ""
                tokens = TOKEN_RE.findall(question) if isinstance(question, str) else []
                if not tokens:
                    tokens = self._by_subject(question)
                if not tokens:
                    continue
                answer = results.get(tc.get("id"))
                if answer is None or answer.get("name") != "ask_human":
                    continue
                decision = classify(answer.get("content"))
                for token in tokens:
                    self.decisions.setdefault(token, decision)

    def _by_subject(self, question) -> list[str]:
        """A question with no token still binds if it quotes the subject
        of exactly one open request; the model often drops the token."""
        if not isinstance(question, str):
            return []
        open_tokens = [
            t for t, (_, subject) in self.pending.items()
            if t not in self.decisions and t not in self.consumed and subject and subject in question
        ]
        return open_tokens if len(open_tokens) == 1 else []
