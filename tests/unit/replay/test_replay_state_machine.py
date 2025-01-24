from openhands.core.schema.replay import ReplayPhase
from openhands.replay.replay_phases import get_next_agent_replay_phase


def test_get_next_agent_replay_phase():
    assert get_next_agent_replay_phase(ReplayPhase.Analysis) == ReplayPhase.Edit
