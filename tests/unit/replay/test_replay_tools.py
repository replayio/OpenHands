import pytest

from openhands.core.schema.replay import ReplayPhase
from openhands.replay.replay_phases import get_next_agent_replay_phase
from openhands.replay.replay_tools import (
    get_replay_tools,
    get_replay_transition_tool_for_current_phase,
    replay_analysis_tools,
)


def test_get_replay_transition_tools_analysis():
    assert get_next_agent_replay_phase(ReplayPhase.Analysis) is not None
    tool = get_replay_transition_tool_for_current_phase(ReplayPhase.Analysis, 'submit')
    assert tool
    assert tool['function']['name'] == 'submit'
    assert tool['new_phase'] is not None
    assert tool['new_phase'] == get_next_agent_replay_phase(ReplayPhase.Analysis)


def test_get_replay_transition_tools_edit():
    assert get_next_agent_replay_phase(ReplayPhase.Edit) is None
    tool = get_replay_transition_tool_for_current_phase(ReplayPhase.Edit, 'submit')
    assert not tool


def test_get_tools():
    default_tools = []

    # Test Normal phase
    tools = get_replay_tools(ReplayPhase.Normal, default_tools)
    assert len(tools) == len(default_tools)
    assert all(t in tools for t in default_tools)

    # Test Analysis phase
    tools = get_replay_tools(ReplayPhase.Analysis, default_tools)
    assert len(tools) == len(replay_analysis_tools) + 1  # +1 for transition tool
    assert all(t in tools for t in replay_analysis_tools)
    assert tools[-1]['function']['name'] == 'submit'

    # Test Edit phase
    tools = get_replay_tools(ReplayPhase.Edit, default_tools)
    assert len(tools) == len(default_tools) + len(replay_analysis_tools)
    assert all(t in tools for t in default_tools)
    assert all(t in tools for t in replay_analysis_tools)

    # Test invalid phase
    with pytest.raises(ValueError):
        get_replay_tools('invalid_phase', default_tools)
