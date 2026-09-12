"""`sleip` (also `sleipnir`): the session client with your worker, or the pieces alone.

    sleip [run] [--root DIR] [--agent NAME] [--model M] [--max-steps N]   client + worker
    sleip serve ...                                                        worker only, headless
    sleip chat ...                                                         client only
    sleip allow list | add <tool> <pattern> | remove <tool> <pattern>
    sleip config show | set <key> <value> | unset <key>
    sleip doctor
    sleip docs
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from sleipnir import __version__, config, environment
from sleipnir.docs import DOCS
from sleipnir.permissions import MUTATING, Permissions, Rule
from sleipnir.runtime import ALLOW_FILE

SUBCOMMANDS = {"run", "serve", "chat", "stop", "allow", "config", "doctor", "docs", "help", "setup"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sleip", description="Sleipnir: the coding harness for Norns")
    parser.add_argument("--version", action="version", version=f"sleipnir {__version__}")
    parser.add_argument("--root", default=".", help="repository root (default: current directory)")
    parser.add_argument("--env-file", help="extra KEY=VALUE file to load before .envrc/.env")
    sub = parser.add_subparsers(dest="command")

    for name, help_text in (
        ("run", "the session client with this repository's worker (the default)"),
        ("serve", "the worker alone, headless"),
        ("chat", "the session client alone, without a worker"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--agent", help="agent name in Norns")
        p.add_argument("--model")
        p.add_argument("--max-steps", type=int)
        p.add_argument("--compact-at", type=int, help="input tokens at which Norns compacts the history")
        p.add_argument("--keep", type=int, help="messages kept verbatim after a compaction")
        p.add_argument("--max-tokens", type=int, help="ceiling on one response; a turn that reaches it is cut off")
        p.add_argument("--no-gard", action="store_true", help="do not pin this worker to a per-repository gard")
        if name == "serve":
            p.add_argument(
                "--foreground", "-f", action="store_true",
                help="hold this terminal instead of detaching (what a container's supervisor wants)",
            )

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

    sub.add_parser("stop", help="stop this checkout's worker")
    setup = sub.add_parser("setup", help="set the keys sleip needs, kept for every space")
    setup.add_argument("--force", action="store_true", help="ask again for keys that are already set")
    sub.add_parser("doctor", help="check the environment and configuration")
    sub.add_parser("docs", help="print the reference the agent reads")
    sub.add_parser("help", help="the commands, in brief")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `sleip` and `sleip --agent x` mean `run`; --root may come anywhere.
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

    # NORNS_URL, NORNS_API_KEY, ANTHROPIC_API_KEY and friends may live in the
    # repository: --env-file, then .envrc through direnv, then .env.
    from sleipnir.env import load_env

    env_file = Path(args.env_file).resolve() if args.env_file else None
    if env_file is not None and not env_file.is_file():
        parser.error(f"{env_file} is not a file")
    loaded_env = load_env(root, env_file)

    if args.command in ("run", "serve", "chat", "doctor") or (
        args.command == "config" and args.action == "show"
    ):
        try:
            environment.load(root)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    if args.command in ("run", "serve", "chat"):
        settings = config.resolve(
            root,
            {
                "agent": args.agent,
                "model": args.model,
                "max_steps": str(args.max_steps) if args.max_steps else None,
                "compact_at": str(args.compact_at) if args.compact_at else None,
                "keep": str(args.keep) if args.keep else None,
                "max_tokens": str(args.max_tokens) if args.max_tokens else None,
            },
        )
        return cmd_start(
            root, settings, mode=args.command, use_gard=not args.no_gard,
            foreground=getattr(args, "foreground", False),
        )
    if args.command == "stop":
        from sleipnir import daemon

        print(daemon.stop(root))
        return 0
    if args.command == "setup":
        from sleipnir import setup

        try:
            return setup.run(force=args.force)
        except KeyboardInterrupt:
            print("\nnothing saved.", file=sys.stderr)
            return 1
    if args.command == "doctor":
        return cmd_doctor(root, loaded_env)
    if args.command == "allow":
        return cmd_allow(root, args)
    if args.command == "config":
        return cmd_config(root, args)
    if args.command == "docs":
        print(DOCS, end="")
        return 0
    if args.command == "help":
        parser.print_help()
        return 0
    return 0


def cmd_start(
    root: Path, settings: dict[str, str], *, mode: str, use_gard: bool, foreground: bool = False
) -> int:
    import asyncio

    from sleipnir.api import NornsApi
    from sleipnir.gard import ensure_gard

    from sleipnir import setup

    # Nothing configured yet: ask, rather than failing on a blank header.
    if not setup.configured():
        try:
            if setup.run() != 0:
                return 1
        except KeyboardInterrupt:
            print("\nnothing saved.", file=sys.stderr)
            return 1

    url = os.environ.get("NORNS_URL", "").strip() or "http://localhost:4000"
    api_key = os.environ.get("NORNS_API_KEY", "").strip()
    if not api_key:
        print(
            "error: NORNS_API_KEY is not set, so there is nothing to authenticate with.\n"
            "Run `sleip setup`, or set it in this repository's .envrc or .env.",
            file=sys.stderr,
        )
        return 1

    async def bootstrap():
        api = NornsApi(url, api_key)
        try:
            return await ensure_gard(api, root) if use_gard else None
        finally:
            await api.close()

    if mode == "serve" and not foreground:
        # A checkout being open should not cost a terminal. The child is
        # this same command with --foreground.
        from sleipnir import daemon

        pid, message = daemon.start(root, [] if use_gard else ["--no-gard"])
        print(message)
        return 0 if pid else 1

    if mode == "serve":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
        from sleipnir.worker import run_worker

        gard = asyncio.run(bootstrap())
        if gard:
            logging.getLogger("sleipnir").info(f"gard {gard['id']} ({gard['source']})")
        run_worker(root, settings, gard)
        return 0

    # The client owns the terminal; the worker's logs go to a file.
    log_path = root / ".sleipnir" / "sleipnir.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", filename=str(log_path))

    from sleipnir.app import SleipnirApp

    gard = asyncio.run(bootstrap()) if mode == "run" else None
    if mode == "run":
        # Start it if it is not already up, and leave it up afterwards: the
        # worker is this checkout being open, not this window being open.
        from sleipnir import daemon

        pid, message = daemon.start(root, [] if use_gard else ["--no-gard"])
        if pid is None:
            print(f"error: {message}", file=sys.stderr)
            return 1

    app = SleipnirApp(
        NornsApi(url, api_key),
        agent_name=settings["agent"],
        gard_id=gard["id"] if gard else None,
        root=root,
    )
    app.run()
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


def cmd_doctor(root: Path, loaded_env: dict[str, str] | None = None) -> int:
    from sleipnir.env import env_hint

    ok = True
    loaded_env = loaded_env or {}

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

    if loaded_env:
        by_source: dict[str, list[str]] = {}
        for k, src in loaded_env.items():
            by_source.setdefault(src, []).append(k)
        for src, keys in by_source.items():
            report(True, f"{src}: {', '.join(sorted(keys))}")
    hint = env_hint(root)
    if hint:
        report(None, hint)

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
