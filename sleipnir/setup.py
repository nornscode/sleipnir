"""First-run setup: the keys sleip needs, asked for once and kept for
every space.

Secrets live in ~/.sleipnir/env, beside gards.json and outside any
repository, because a key in a checkout is a key one `git add` away from
being published. A repository's own .envrc or .env still wins over it,
so a checkout can point at a different Norns without being reconfigured.
"""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

from sleipnir.env import USER_ENV, parse_env_file

DEFAULT_URL = "http://localhost:4000"
LLM_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def configured() -> bool:
    """Enough to start: somewhere to talk to, and something to talk with."""
    return bool(os.environ.get("NORNS_API_KEY", "").strip()) and any(
        os.environ.get(k, "").strip() for k in LLM_KEYS
    )


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def mask(value: str) -> str:
    return f"{value[:6]}…{value[-4:]}" if len(value) > 14 else "set"


def read_user_env() -> dict[str, str]:
    try:
        return parse_env_file(USER_ENV.read_text())
    except OSError:
        return {}


def write_user_env(values: dict[str, str]) -> None:
    """Merge into ~/.sleipnir/env, owner-readable only."""
    merged = {**read_user_env(), **values}
    USER_ENV.parent.mkdir(parents=True, exist_ok=True)
    USER_ENV.write_text(
        "# Written by `sleip setup`. Keys for every space on this machine.\n"
        "# A repository's own .envrc or .env overrides anything here.\n"
        + "".join(f"{k}={v}\n" for k, v in merged.items() if v)
    )
    try:
        USER_ENV.chmod(0o600)
    except OSError:
        pass


def check(url: str, api_key: str) -> tuple[bool, str]:
    """Ask Norns whether the key works, so a typo is caught here."""
    import httpx

    try:
        r = httpx.get(
            f"{url.rstrip('/')}/api/v1/agents",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8,
        )
    except Exception as e:
        return False, f"cannot reach {url}: {e}"
    if r.status_code == 200:
        return True, f"connected to {url}"
    if r.status_code in (401, 403):
        return False, f"{url} rejected that key ({r.status_code})"
    return False, f"{url} answered {r.status_code}"


def ask(prompt: str, *, default: str = "", secret: bool = False) -> str:
    shown = f"{prompt} [{default}]: " if default else f"{prompt}: "
    try:
        answer = (getpass(shown) if secret else input(shown)).strip()
    except EOFError:
        raise KeyboardInterrupt from None
    return answer or default


def run(*, force: bool = False) -> int:
    """Ask for what is missing and store it. Returns an exit code."""
    if not interactive():
        print(
            "error: sleip is not configured and this is not a terminal, so it\n"
            "cannot ask. Run `sleip setup` from a terminal, or set NORNS_URL,\n"
            "NORNS_API_KEY and ANTHROPIC_API_KEY in the environment.",
            file=sys.stderr,
        )
        return 1

    stored = read_user_env()
    print("Setting up sleip. Answers are kept in ~/.sleipnir/env for every space.\n")

    url = os.environ.get("NORNS_URL", "").strip() or stored.get("NORNS_URL", "") or DEFAULT_URL
    api_key = os.environ.get("NORNS_API_KEY", "").strip() or stored.get("NORNS_API_KEY", "")

    while True:
        url = ask("Norns URL", default=url)
        if api_key and not force:
            print(f"  NORNS_API_KEY: {mask(api_key)}")
            if ask("Keep that key? (y/n)", default="y").lower().startswith("n"):
                api_key = ""
        if not api_key:
            api_key = ask("Norns API key (nrn_…)", secret=True)
        if not api_key:
            print("  a key is required; it is what authenticates you to Norns.")
            continue
        good, message = check(url, api_key)
        print(f"  {'ok' if good else 'FAIL'} {message}")
        if good:
            break
        if ask("Try again? (y/n)", default="y").lower().startswith("n"):
            print("  storing it anyway; `sleip doctor` will re-check.")
            break
        api_key = ""

    have = [k for k in LLM_KEYS if (os.environ.get(k, "").strip() or stored.get(k))]
    llm_key = llm_name = ""
    if have and not force:
        llm_name = have[0]
        print(f"  {llm_name}: {mask(os.environ.get(llm_name, '') or stored.get(llm_name, ''))}")
        if ask("Keep that key? (y/n)", default="y").lower().startswith("n"):
            llm_name = ""
    if not llm_name:
        print("\nsleip makes the model calls itself — the key stays on this machine")
        print("and never reaches Norns.")
        which = ask("Provider: anthropic or openai", default="anthropic").lower()
        llm_name = "OPENAI_API_KEY" if which.startswith("o") else "ANTHROPIC_API_KEY"
        llm_key = ask(f"{llm_name}", secret=True)
        if not llm_key:
            print(f"  no {llm_name}; sessions will fail on the first model call.")

    values = {"NORNS_URL": url, "NORNS_API_KEY": api_key}
    if llm_key:
        values[llm_name] = llm_key
    write_user_env(values)
    for k, v in values.items():
        os.environ[k] = v

    print(f"\nSaved to {USER_ENV} (owner-readable only).")
    print("`sleip doctor` checks it; `sleip setup` changes it.")
    return 0
