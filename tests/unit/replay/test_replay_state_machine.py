from openhands.core.schema.replay import ReplayPhase
from openhands.replay.replay_phases import (
    get_next_agent_replay_phase,
    replay_agent_state_machine,
)


def test_edges():
    all_agent_edges = replay_agent_state_machine.edges

    # All agent edges should be unique.
    assert len(all_agent_edges) == len(set(all_agent_edges))


def test_get_next_agent_replay_phase():
    assert (
        get_next_agent_replay_phase(ReplayPhase.Analysis) == ReplayPhase.ConfirmAnalysis
    )
    assert get_next_agent_replay_phase(ReplayPhase.ConfirmAnalysis) == ReplayPhase.Edit
