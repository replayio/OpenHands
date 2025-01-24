from openhands.replay.replay_phases import (
    replay_agent_state_machine,
)
from openhands.replay.replay_prompts import phase_prompts
from tests.unit.replay.replay_test_util import format_enums


def test_transition_prompts():
    # Get ground truth
    all_agent_edges = replay_agent_state_machine.edges
    to_edges = {edge[1] for edge in all_agent_edges}

    # All destination phases should have prompts.
    assert format_enums(phase_prompts.keys()) == format_enums(to_edges)
