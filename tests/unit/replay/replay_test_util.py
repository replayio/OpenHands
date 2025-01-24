import enum
from typing import Collection, TypeVar

from openhands.core.schema.replay import ReplayPhase
from openhands.replay.replay_phases import (
    replay_agent_state_machine,
)

T = TypeVar('T', bound=enum.Enum)


def format_enums(enums: Collection[T]) -> set[str]:
    """Convert any collection of enums to readable set of names."""
    return {e.name for e in enums}


def format_edge(edge: tuple[ReplayPhase, ReplayPhase]) -> str:
    """Format state transition edge as 'from → to'."""
    from_state, to_state = edge
    return f'{from_state.name} → {to_state.name}'


# The given edges should form a partition of the set of all agent edges.
def assert_edges_partition(
    edges: list[tuple[ReplayPhase, ReplayPhase]],
) -> None:
    """Verify tool edges form a partition of agent edges."""
    # Get ground truth
    all_agent_edges = replay_agent_state_machine.edges

    # Convert to sorted lists of formatted strings for comparison
    tool_edge_strs = sorted(f'{f.name} → {t.name}' for [f, t] in edges)
    agent_edge_strs = sorted(f'{f.name} → {t.name}' for [f, t] in all_agent_edges)

    # Check for duplicates in tool edges
    if len(set(tool_edge_strs)) != len(tool_edge_strs):
        raise AssertionError('Tool edges contain duplicates')

    # Check lists match exactly
    assert tool_edge_strs == agent_edge_strs
