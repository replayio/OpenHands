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
from openhands.replay.replay_prompts import replay_prompt_phase_edit

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


def on_agent_replay_observation(
    obs: ReplayObservation, max_message_chars: int
) -> Message:
    """Create a message to explain the observation."""
    text: str
    if isinstance(obs, ReplayToolCmdOutputObservation):
        # Internal command result from an automatic or user-triggered replay command.
        if obs.tool_call_metadata is None:
            # If it doesn't have tool call metadata, it was triggered by a user action.
            text = truncate_content(
                f'\nObserved result of replay command executed by user:\n{obs.content}',
                max_message_chars,
            )
        else:
            text = obs.content
    elif isinstance(obs, ReplayPhaseUpdateObservation):
        # Agent requested a phase update.
        text = get_new_phase_prompt(obs)
    else:
        raise NotImplementedError(
            f"Unhandled observation type: {obs.__class__.__name__} ({getattr(obs, 'observation', None)})"
        )
    return Message(role='user', content=[TextContent(text=text)])


# ###########################################################################
# Prompts.
# ###########################################################################


def get_new_phase_prompt(obs: ReplayPhaseUpdateObservation) -> str:
    """Get the prompt for the new phase."""
    new_phase = obs.new_phase
    if new_phase == ReplayPhase.Edit:
        new_phase_prompt = replay_prompt_phase_edit(obs)
    else:
        raise NotImplementedError(f'Unhandled ReplayPhaseUpdateAction: {new_phase}')
    return new_phase_prompt


# ###########################################################################
# State machine transitions.
# ###########################################################################


def update_phase(new_phase: ReplayPhase, state: State, agent: Agent):
    """Apply phase update side effects."""
    state.replay_phase = new_phase
    agent.update_tools(new_phase)
    logger.info(f'[REPLAY] update_phase (replay_phase): {new_phase}')
