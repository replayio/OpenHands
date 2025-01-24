import pytest

from openhands.core.schema.replay import ReplayPhase
from openhands.replay.replay_phases import (
    get_next_agent_replay_phase,
    replay_agent_state_machine,
)
from openhands.replay.replay_tools import (
    get_replay_tools,
    get_replay_transition_tool,
    get_replay_transition_tools,
    replay_analysis_tools,
    replay_phase_transition_tools,
    replay_phase_transition_tools_by_from_phase,
)
from tests.unit.replay.replay_test_util import assert_edges_partition


def test_transition_tool_edges():
    # Get tool edges.
    tools = replay_phase_transition_tools
    tool_edges: list[tuple[ReplayPhase, ReplayPhase]] = [
        edge for t in tools for edge in t['edges']
    ]

    # All tool edges must form a partition of the set of all agent edges.
    assert_edges_partition(tool_edges)


def test_replay_phase_transition_tools_by_from_phase():
    # Get ground truth
    all_agent_edges = replay_agent_state_machine.edges
    all_agent_from_phases = {edge[0] for edge in all_agent_edges}

    # all_agent_from_phases should exactly match the set of all from_phases of all tools.
    assert (
        set(replay_phase_transition_tools_by_from_phase.keys()) == all_agent_from_phases
    )

    # All tool edges should form a partition of the set of all agent edges
    all_tool_edges = [
        edge
        for _, tools in replay_phase_transition_tools_by_from_phase.items()
        for tool in tools
        for edge in tool['edges']
    ]
    assert_edges_partition(all_tool_edges)


def test_get_replay_transition_tools_analysis():
    tool = get_replay_transition_tool(ReplayPhase.Analysis, 'submit')
    assert tool
    assert tool['function']['name'] == 'submit'
    assert (ReplayPhase.Analysis, ReplayPhase.ConfirmAnalysis) in tool['edges']

    tools = get_replay_transition_tools(ReplayPhase.Analysis)
    assert len([t['function']['name'] for t in tools]) == 1

    assert tool in tools


def test_get_replay_transition_tools_edit():
    assert get_next_agent_replay_phase(ReplayPhase.Edit) is None
    tool = get_replay_transition_tool(ReplayPhase.Edit, 'submit')
    assert not tool


def test_get_tools():
    default_tools = []

    # Make sure that all ReplayPhases are handled and no error is raised.
    for phase in ReplayPhase:
        get_replay_tools(phase, default_tools)

    # Test individual phases.
    tools = get_replay_tools(ReplayPhase.Normal, default_tools)
    assert len(tools) == len(default_tools)
    assert all(t in tools for t in default_tools)

    tools = get_replay_tools(ReplayPhase.Analysis, default_tools)
    assert len(tools) == len(replay_analysis_tools) + 1  # +1 for transition tool
    assert all(t in tools for t in replay_analysis_tools)
    assert tools[-1]['function']['name'] == 'submit'

    tools = get_replay_tools(ReplayPhase.ConfirmAnalysis, default_tools)
    assert len(tools) == len(replay_analysis_tools) + 1  # +1 for transition tool
    assert all(t in tools for t in replay_analysis_tools)
    assert tools[-1]['function']['name'] == 'confirm'

    tools = get_replay_tools(ReplayPhase.Edit, default_tools)
    assert len(tools) == len(default_tools) + len(replay_analysis_tools)
    assert all(t in tools for t in default_tools)
    assert all(t in tools for t in replay_analysis_tools)

    # Test invalid phase
    with pytest.raises(ValueError):
        get_replay_tools('invalid_phase', default_tools)
