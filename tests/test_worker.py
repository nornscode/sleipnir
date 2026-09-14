from sleipnir import config
from sleipnir.worker import build_agents


def settings(**overrides):
    return {**config.DEFAULTS, **overrides}


def by_name(agents):
    return {a.name: a for a in agents}


def test_the_team_is_three_agents_with_fixed_powers():
    agents = by_name(build_agents(settings()))
    assert set(agents) == {"sleipnir", "sleipnir-explore", "sleipnir-code"}

    lead, explore, code = agents["sleipnir"], agents["sleipnir-explore"], agents["sleipnir-code"]
    # The lead can do everything itself, and launch only its own two helpers.
    assert {"edit_file", "bash"} <= set(lead.allowed_tools)
    assert lead.subagents == {"mode": "allowlist", "allowed_agents": ["sleipnir-explore", "sleipnir-code"],
                              "allow_list_agents": False, "max_depth": 1}
    assert "sleipnir-explore" in lead.system_prompt and "sleipnir-code" in lead.system_prompt

    # Explorers cannot change anything; nothing they are offered writes.
    assert sorted(explore.allowed_tools) == ["git", "glob", "grep", "read_file"]
    assert explore.subagents == {"mode": "disabled"}

    # One coder per session, and it launches nobody.
    assert {"edit_file", "write_file", "bash"} <= set(code.allowed_tools)
    assert code.subagent_conversation == "per_parent"
    assert code.subagents == {"mode": "disabled"}


def test_helpers_use_the_agents_model_unless_told_otherwise():
    agents = by_name(build_agents(settings(model="claude-opus-5")))
    assert {a.model for a in agents.values()} == {"claude-opus-5"}

    agents = by_name(build_agents(settings(model="claude-opus-5", explore_model="claude-haiku-4-5", code_model="claude-sonnet-5")))
    assert agents["sleipnir"].model == "claude-opus-5"
    assert agents["sleipnir-explore"].model == "claude-haiku-4-5"
    assert agents["sleipnir-code"].model == "claude-sonnet-5"


def test_team_off_is_one_agent_that_launches_nobody():
    [agent] = build_agents(settings(team="off", agent="mine"))
    assert agent.name == "mine"
    assert agent.subagents == {"mode": "disabled"}
    assert "launch_agent" not in agent.system_prompt
