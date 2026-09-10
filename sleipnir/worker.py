"""The Sleipnir worker: six tools plus the LLM task, on one connection."""

from __future__ import annotations

import logging
import os
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


def run_worker(root: Path, settings: dict[str, str]) -> None:
    runtime.configure(root)
    perms = runtime.permissions()
    logger.info(f"workspace {root}; {len(perms.rules)} allow rules from {perms.allow_file}")
    logger.info(f"agent {settings['agent']}, model {settings['model']}, max_steps {settings['max_steps']}")

    url = os.environ.get("NORNS_URL", "http://localhost:4000")
    harness = Harness(url, api_key=os.environ.get("NORNS_API_KEY"))
    # Worker identity and gard binding come from the environment
    # (NORNS_WORKER_ID, NORNS_GARD, NORNS_GARD_CLAIM_TOKEN).
    harness.run(build_agent(settings["agent"], settings["model"], int(settings["max_steps"])))
