"""Replay state machine logic."""

from openhands.controller.agent import Agent
from openhands.controller.state.state import State
from openhands.core.logger import openhands_logger as logger
from openhands.core.message import Message, TextContent
from openhands.core.schema.replay import ReplayPhase
from openhands.events.observation.replay import (
    ReplayInternalCmdOutputObservation,
    ReplayObservation,
    ReplayPhaseUpdateObservation,
    ReplayToolCmdOutputObservation,
)
from openhands.events.serialization.event import truncate_content
from openhands.replay.replay_initial_analysis import (
    on_replay_internal_command_observation,
)
from openhands.replay.replay_prompts import (
    get_phase_enter_prompt,
)

# ###########################################################################
# Phase events.
# ###########################################################################


def on_controller_replay_observation(
    obs: ReplayObservation, state: State, agent: Agent
) -> None:
    """Handle the observation."""
    new_phase: ReplayPhase | None = None
    if isinstance(obs, ReplayInternalCmdOutputObservation):
        # NOTE: Currently, the only internal command is the initial-analysis command.
        analysis_tool_metadata = on_replay_internal_command_observation(state, obs)
        if analysis_tool_metadata:
            # Start analysis phase
            state.replay_recording_id = analysis_tool_metadata['recordingId']
            new_phase = ReplayPhase.Analysis
    elif isinstance(obs, ReplayPhaseUpdateObservation):
        # Agent action triggered a phase change.
        new_phase = obs.new_phase

    if new_phase:
        if state.replay_phase == new_phase:
            logger.warning(
                f'Unexpected ReplayPhaseUpdateAction. Already in phase. Observation:\n {repr(obs)}',
            )
        else:
            update_phase(new_phase, state, agent)


def get_replay_observation_prompt(
    obs: ReplayObservation, max_message_chars: int
) -> Message:
    """Create a message to explain the Replay observation to the agent."""
    text: str
    if isinstance(obs, ReplayToolCmdOutputObservation):
        # Internal command result from an automatic or user-triggered replay command.
        if obs.tool_call_metadata is None:
            # If it doesn't have tool call metadata, it was triggered by a user action.
            # TODO: Improve truncation. It currently can cut things off very aggressively.
            text = truncate_content(
                f'\nObserved result of replay command executed by user:\n{obs.content}',
                max_message_chars,
            )
        else:
            text = obs.content
    elif isinstance(obs, ReplayPhaseUpdateObservation):
        # A phase transition was requested.
        text = get_phase_prompt(obs)
    else:
        raise NotImplementedError(
            f"Unhandled observation type: {obs.__class__.__name__} ({getattr(obs, 'observation', None)})"
        )
    return Message(role='user', content=[TextContent(text=text)])


# ###########################################################################
# State machine transition.
# ###########################################################################


def get_phase_prompt(obs) -> str:
    """Prompt for agent when entering new phase."""
    # NOTE: We might add more edge types later, but for now we only have 'enter'.
    return get_phase_enter_prompt(obs)


def update_phase(new_phase: ReplayPhase, state: State, agent: Agent):
    """Apply phase update side effects."""
    state.replay_phase = new_phase
    agent.update_tools(new_phase)
    logger.info(f'[REPLAY] update_phase (replay_phase): {new_phase}')


# ###########################################################################
# ReplayStateMachine.
# ###########################################################################

replay_state_transitions: dict[ReplayPhase, list[ReplayPhase] | None] = {
    ReplayPhase.Normal: None,
    ReplayPhase.Analysis: [ReplayPhase.Edit],
    ReplayPhase.Edit: None,
}


class ReplayStateMachine:
    def __init__(self):
        self.forward_edges = replay_state_transitions

        self.reverse_edges: dict[ReplayPhase, list[ReplayPhase] | None] = {}

        for source, targets in self.forward_edges.items():
            if targets:
                for target in targets:
                    reverse_list = self.reverse_edges.get(target, None)
                    if not reverse_list:
                        reverse_list = self.reverse_edges[target] = []
                    assert reverse_list is not None
                    if source in reverse_list:
                        raise ValueError(
                            f'Cycle detected in ReplayStateMachine: {source} -> {target}'
                        )
                    reverse_list.append(source)

    def get_unique_parent_phase(self, phase: ReplayPhase) -> ReplayPhase | None:
        phases = self.get_parent_phases(phase)
        if not phases:
            return None
        if len(phases) == 1:
            return phases.pop()
        assert len(phases) > 1
        raise ValueError(f'Phase {phase} has multiple parent phases: {phases}')

    def get_parent_phases(self, phase: ReplayPhase) -> list[ReplayPhase] | None:
        return self.reverse_edges.get(phase, list())

    def get_unique_child_phase(self, phase: ReplayPhase) -> ReplayPhase | None:
        phases = self.get_child_phases(phase)
        if not phases:
            return None
        if len(phases) == 1:
            return phases.pop()
        assert len(phases) > 1
        raise ValueError(f'Phase {phase} has multiple child phases: {phases}')

    def get_child_phases(self, phase: ReplayPhase) -> list[ReplayPhase] | None:
        return self.forward_edges.get(phase, list())


replay_state_machine = ReplayStateMachine()


def get_replay_child_phase(phase: ReplayPhase) -> ReplayPhase | None:
    return replay_state_machine.get_unique_child_phase(phase)
