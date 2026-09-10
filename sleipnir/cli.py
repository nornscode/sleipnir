"""`sleipnir`: run the worker, or configure it.

    sleipnir [run] [--root DIR] [--agent NAME] [--model M] [--max-steps N]
    sleipnir allow list | add <tool> <pattern> | remove <tool> <pattern>
    sleipnir config show | set <key> <value> | unset <key>
    sleipnir doctor
    sleipnir docs
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from sleipnir import __version__, config
from sleipnir.docs import DOCS
from sleipnir.permissions import MUTATING, Permissions, Rule
from sleipnir.runtime import ALLOW_FILE

SUBCOMMANDS = {"run", "allow", "config", "doctor", "docs"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sleipnir", description="Coding harness worker for Norns")
    parser.add_argument("--version", action="version", version=f"sleipnir {__version__}")
    parser.add_argument("--root", default=".", help="repository root (default: current directory)")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="connect to Norns and serve the harness (the default)")
    run.add_argument("--agent", help="agent name in Norns")
    run.add_argument("--model")
    run.add_argument("--max-steps", type=int)

    allow = sub.add_parser("allow", help="manage the allow list (.sleipnir/allow)")
    allow_sub = allow.add_subparsers(dest="action", required=True)
    allow_sub.add_parser("list")
    for name in ("add", "remove"):
        a = allow_sub.add_parser(name)
        a.add_argument("tool", choices=sorted(MUTATING))
        a.add_argument("pattern", help="fnmatch pattern over the command (bash) or path (file tools)")

    cfg = sub.add_parser("config", help="show or change settings (.sleipnir/config)")
    cfg_sub = cfg.add_subparsers(dest="action", required=True)
    cfg_sub.add_parser("show")
    s = cfg_sub.add_parser("set")
    s.add_argument("key", choices=config.KEYS)
    s.add_argument("value")
    u = cfg_sub.add_parser("unset")
    u.add_argument("key", choices=config.KEYS)

    sub.add_parser("doctor", help="check the environment and configuration")
    sub.add_parser("docs", help="print the reference the agent reads")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `sleipnir` and `sleipnir --agent x` mean `run`; --root may come anywhere.
    if not any(a in SUBCOMMANDS for a in argv) and not any(a in ("-h", "--help", "--version") for a in argv):
        root_args: list[str] = []
        if "--root" in argv:
            i = argv.index("--root")
            root_args, argv = argv[i : i + 2], argv[:i] + argv[i + 2 :]
        argv = root_args + ["run"] + argv
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"{root} is not a directory")

    if args.command == "run":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
        settings = config.resolve(
            root,
            {"agent": args.agent, "model": args.model, "max_steps": str(args.max_steps) if args.max_steps else None},
        )
        from sleipnir.worker import run_worker

        run_worker(root, settings)
        return 0
    if args.command == "allow":
        return cmd_allow(root, args)
    if args.command == "config":
        return cmd_config(root, args)
    if args.command == "doctor":
        return cmd_doctor(root)
    if args.command == "docs":
        print(DOCS, end="")
        return 0
    return 0


def cmd_allow(root: Path, args) -> int:
    perms = Permissions(root / ALLOW_FILE)
    if args.action == "list":
        if not perms.rules:
            print(f"(no rules in {perms.allow_file})")
        for r in perms.rules:
            print(r)
        return 0
    rule = Rule(args.tool, args.pattern)
    if args.action == "add":
        if rule in perms.rules:
            print(f"already present: {rule}")
        else:
            perms.add_rules([rule])
            print(f"added: {rule}")
        return 0
    removed = perms.remove_rules([rule])
    print(f"removed: {rule}" if removed else f"not found: {rule}")
    return 0 if removed else 1


def cmd_config(root: Path, args) -> int:
    if args.action == "show":
        values = config.resolve(root)
        for k in config.KEYS:
            print(f"{k} = {values[k]}  ({config.source(root, k)})")
        print(f"allow list: {root / ALLOW_FILE}")
        return 0
    if args.action == "set":
        try:
            config.set_value(root, args.key, args.value)
        except (KeyError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"{args.key} = {args.value}  (takes effect when the worker restarts)")
        return 0
    config.unset_value(root, args.key)
    print(f"{args.key} unset")
    return 0


def cmd_doctor(root: Path) -> int:
    ok = True

    def report(good: bool | None, text: str) -> None:
        nonlocal ok
        mark = "ok  " if good else ("warn" if good is None else "FAIL")
        if good is False:
            ok = False
        print(f"{mark} {text}")

    report(True, f"root {root}")
    report(None if not (root / ".git").exists() else True, "git repository" if (root / ".git").exists() else "not a git repository")

    perms = Permissions(root / ALLOW_FILE)
    report(True, f"{len(perms.rules)} allow rules in {perms.allow_file}")
    values = config.resolve(root)
    report(True, f"agent {values['agent']}, model {values['model']}, max_steps {values['max_steps']}")

    url = os.environ.get("NORNS_URL")
    key = os.environ.get("NORNS_API_KEY")
    report(bool(url), f"NORNS_URL {url}" if url else "NORNS_URL is not set")
    report(bool(key), "NORNS_API_KEY is set" if key else "NORNS_API_KEY is not set")
    if url and key:
        try:
            import httpx

            r = httpx.get(f"{url.rstrip('/')}/api/v1/agents", headers={"Authorization": f"Bearer {key}"}, timeout=5)
            report(r.status_code == 200, f"GET {url}/api/v1/agents -> {r.status_code}")
        except Exception as e:
            report(False, f"cannot reach {url}: {e}")

    llm_keys = [k for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY") if os.environ.get(k)]
    report(bool(llm_keys), f"LLM key: {', '.join(llm_keys)}" if llm_keys else "no ANTHROPIC_API_KEY or OPENAI_API_KEY")

    gard, claim = os.environ.get("NORNS_GARD"), os.environ.get("NORNS_GARD_CLAIM_TOKEN")
    if gard or claim:
        report(bool(gard and claim), f"gard {gard}" if gard and claim else "NORNS_GARD and NORNS_GARD_CLAIM_TOKEN must both be set")
    else:
        report(None, "no gard: serves runs that have no gard")

    print("all good" if ok else "problems found")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
