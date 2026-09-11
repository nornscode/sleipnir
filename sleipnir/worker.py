"""The Sleipnir worker: six tools plus the LLM task, on one connection."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from norns import Agent, Norns

from sleipnir import runtime
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


def build_agent(name: str, model: str, max_steps: int, compact_at: int, keep: int, max_tokens: int) -> Agent:
    return Agent(
        name=name,
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=all_tools,
        mode="conversation",
        checkpoint_policy="on_tool_call",
        # A coding session is one long tool loop. No sliding window: Norns
        # compacts the history into a summary once a response reports
        # compact_at input tokens, and this worker writes the summary.
        context_strategy="none",
        context_policy={"compact_at": compact_at, "keep": keep},
        max_steps=max_steps,
        # A turn that writes a file is long; the default ceiling cuts it off.
        max_tokens=max_tokens,
    )


def build_harness(root: Path, settings: dict[str, str]) -> tuple[Harness, Agent]:
    runtime.configure(root)
    perms = runtime.permissions()
    logger.info(f"workspace {root}; {len(perms.rules)} allow rules from {perms.allow_file}")
    logger.info(
        f"agent {settings['agent']}, model {settings['model']}, max_steps {settings['max_steps']}, "
        f"compact at {settings['compact_at']} tokens keeping {settings['keep']} messages, "
        f"max_tokens {settings['max_tokens']}"
    )
    url = os.environ.get("NORNS_URL", "http://localhost:4000")
    harness = Harness(url, api_key=os.environ.get("NORNS_API_KEY"))
    agent = build_agent(
        settings["agent"], settings["model"], int(settings["max_steps"]),
        int(settings["compact_at"]), int(settings["keep"]), int(settings["max_tokens"]),
    )
    return harness, agent


def run_worker(root: Path, settings: dict[str, str], gard: dict | None = None) -> None:
    """Serve until told to stop, in this thread."""
    harness, agent = build_harness(root, settings)
    harness.run(agent, **gard_kwargs(gard))


def worker_thread(
    harness: Harness, agent: Agent, gard: dict | None, on_stop=None
) -> threading.Thread:
    """The same worker, in a background thread beside the session client.

    on_stop is called with the exception that ended it, if any: a gard
    closed from another machine kicks this worker, and the client is the
    only thing that can say so.
    """

    def serve() -> None:
        error = None
        try:
            harness.run(agent, **gard_kwargs(gard))
        except BaseException as e:  # noqa: BLE001 — reported, not swallowed
            error = e
            logger.error(f"worker stopped: {e}")
        if on_stop is not None:
            on_stop(error)

    return threading.Thread(target=serve, name="sleipnir-worker", daemon=True)


def gard_kwargs(gard: dict | None) -> dict:
    # Worker identity and gard binding otherwise come from the environment
    # (NORNS_WORKER_ID, NORNS_GARD, NORNS_GARD_CLAIM_TOKEN).
    if gard and gard.get("id") and gard.get("claim_token"):
        return {"gard": gard["id"], "claim_token": gard["claim_token"]}
    return {}
