"""The Sleipnir worker: six tools plus the LLM task, on one connection."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from norns import Agent, Norns

from sleipnir import __version__, runtime
from sleipnir.prompt import SYSTEM_PROMPT
from sleipnir.tools import all_tools

logger = logging.getLogger("sleipnir")


class Harness(Norns):
    """A Norns worker that reads the run's messages on every LLM task so
    the permission set can see the user's ask_human answers."""

    async def _handle_llm_task(self, task: dict) -> dict:
        try:
            runtime.permissions().observe(task.get("messages", []))
        except Exception as e:  # never let bookkeeping break the LLM call
            logger.warning(f"permission observe failed: {e}")
        return await super()._handle_llm_task(task)


def build_agent(name: str, model: str, max_steps: int) -> Agent:
    return Agent(
        name=name,
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=all_tools,
        mode="conversation",
        checkpoint_policy="on_tool_call",
        # A coding session is one long tool loop; the window must outlast
        # max_steps (up to three messages per step) or the task itself is
        # evicted partway through. Compaction (H2) replaces this.
        context_window=max_steps * 3,
        max_steps=max_steps,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sleipnir", description="Coding harness worker for Norns")
    parser.add_argument("--root", default=".", help="repository root (default: current directory)")
    parser.add_argument("--agent", default=os.environ.get("SLEIPNIR_AGENT", "sleipnir"), help="agent name")
    parser.add_argument("--model", default=os.environ.get("SLEIPNIR_MODEL", "claude-sonnet-5"))
    parser.add_argument("--max-steps", type=int, default=int(os.environ.get("SLEIPNIR_MAX_STEPS", "200")))
    parser.add_argument("--version", action="version", version=f"sleipnir {__version__}")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"{root} is not a directory")
    runtime.configure(root)
    perms = runtime.permissions()
    logger.info(f"workspace {root}; {len(perms.rules)} allow rules from {perms.allow_file}")

    url = os.environ.get("NORNS_URL", "http://localhost:4000")
    harness = Harness(url, api_key=os.environ.get("NORNS_API_KEY"))
    # Worker identity and gard binding come from the environment
    # (NORNS_WORKER_ID, NORNS_GARD, NORNS_GARD_CLAIM_TOKEN).
    harness.run(build_agent(args.agent, args.model, args.max_steps))


if __name__ == "__main__":
    main()
