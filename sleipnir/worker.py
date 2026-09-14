"""The Sleipnir worker: the tools, the LLM task, and the agents that use
them, on one connection."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from norns import Agent, Norns

from sleipnir import runtime
from sleipnir.prompt import CODE_PROMPT, EXPLORE_PROMPT, SYSTEM_PROMPT, TEAM_PROMPT
from sleipnir.tools import all_tools, read_tools

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


def team_names(agent: str) -> tuple[str, str]:
    """The explorer's and the coder's names in Norns, from the agent's."""
    return f"{agent}-explore", f"{agent}-code"


def build_agents(settings: dict[str, str]) -> list[Agent]:
    """The agent, and with the team on, its explorers and its coder.

    What each may do is fixed here rather than left to the agent's
    judgment: Norns offers each only the tools it names and refuses a call
    to any other, and only the agent may launch the other two. The agent
    decides who does a piece of work, never what they are allowed to do,
    and every change still goes through the allow list and the user.
    """
    name, model = settings["agent"], settings["model"]

    def agent(agent_name: str, agent_model: str, prompt: str, tools: list, **extra) -> Agent:
        return Agent(
            name=agent_name,
            model=agent_model,
            system_prompt=prompt,
            tools=tools,
            allowed_tools=[t.name for t in tools],
            mode="conversation",
            checkpoint_policy="on_tool_call",
            # A coding session is one long tool loop. No sliding window: Norns
            # compacts the history into a summary once a response reports
            # compact_at input tokens, and this worker writes the summary.
            context_strategy="none",
            context_policy={"compact_at": int(settings["compact_at"]), "keep": int(settings["keep"])},
            max_steps=int(settings["max_steps"]),
            # A turn that writes a file is long; the default ceiling cuts it off.
            max_tokens=int(settings["max_tokens"]),
            **extra,
        )

    alone = {"mode": "disabled"}
    if settings.get("team", "on") != "on":
        return [agent(name, model, SYSTEM_PROMPT, all_tools, subagents=alone)]
    explore, code = team_names(name)
    return [
        agent(
            name, model, SYSTEM_PROMPT + TEAM_PROMPT.format(explore=explore, code=code), all_tools,
            subagents={"mode": "allowlist", "allowed_agents": [explore, code], "allow_list_agents": False, "max_depth": 1},
        ),
        agent(explore, settings.get("explore_model") or model, EXPLORE_PROMPT, read_tools, subagents=alone),
        # One conversation per session: a second assignment while the first
        # is still going is refused, so there is never more than one writer,
        # and the coder remembers what it was asked before.
        agent(
            code, settings.get("code_model") or model, CODE_PROMPT, all_tools,
            subagents=alone, subagent_conversation="per_parent",
        ),
    ]


def build_harness(root: Path, settings: dict[str, str]) -> tuple[Harness, list[Agent]]:
    runtime.configure(root)
    perms = runtime.permissions()
    logger.info(f"workspace {root}; {len(perms.rules)} allow rules from {perms.allow_file}")
    agents = build_agents(settings)
    logger.info(
        f"agents {', '.join(f'{a.name} ({a.model})' for a in agents)}, max_steps {settings['max_steps']}, "
        f"compact at {settings['compact_at']} tokens keeping {settings['keep']} messages, "
        f"max_tokens {settings['max_tokens']}"
    )
    url = os.environ.get("NORNS_URL", "http://localhost:4000")
    harness = Harness(url, api_key=os.environ.get("NORNS_API_KEY"))
    return harness, agents


def run_worker(root: Path, settings: dict[str, str], gard: dict | None = None) -> None:
    """Serve until told to stop, in this thread."""
    harness, agents = build_harness(root, settings)
    harness.run(agents, **gard_kwargs(gard))


def worker_thread(
    harness: Harness, agents: list[Agent], gard: dict | None, on_stop=None
) -> threading.Thread:
    """The same worker, in a background thread beside the session client.

    on_stop is called with the exception that ended it, if any: a gard
    closed from another machine kicks this worker, and the client is the
    only thing that can say so.
    """

    def serve() -> None:
        error = None
        try:
            harness.run(agents, **gard_kwargs(gard))
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
