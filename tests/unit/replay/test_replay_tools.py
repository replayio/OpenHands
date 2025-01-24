from openhands.core.schema.replay import ReplayPhase
from openhands.replay.replay_phases import get_next_agent_replay_phase
from openhands.replay.replay_tools import (
    get_replay_transition_tool_for_current_phase,
)


def test_get_replay_transition_tool_for_analysis_phase():
    tool = get_replay_transition_tool_for_current_phase(ReplayPhase.Analysis, 'submit')
    assert tool is not None
    assert tool['function']['name'] == 'submit'
    assert tool['new_phase'] is not None
    assert get_next_agent_replay_phase(ReplayPhase.Analysis) is not None
    assert tool['new_phase'] == get_next_agent_replay_phase(ReplayPhase.Analysis)
