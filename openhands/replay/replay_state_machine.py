from openhands.controller.agent import Agent
from openhands.controller.state.state import State
from openhands.core.logger import openhands_logger as logger
from openhands.core.message import Message, TextContent
from openhands.core.schema.replay import ReplayDebuggingPhase
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


def on_replay_observation(obs: ReplayObservation, state: State, agent: Agent) -> None:
    """Handle the observation."""
    if isinstance(obs, ReplayInternalCmdOutputObservation):
        # NOTE: Currently, the only internal command is the initial-analysis command.
        analysis_tool_metadata = on_replay_internal_command_observation(state, obs)
        if analysis_tool_metadata:
            # Start analysis phase
            state.replay_recording_id = analysis_tool_metadata['recordingId']
            state.replay_phase = ReplayDebuggingPhase.Analysis
            agent.replay_phase_changed(ReplayDebuggingPhase.Analysis)
    elif isinstance(obs, ReplayPhaseUpdateObservation):
        new_phase = obs.new_phase
        if state.replay_phase == new_phase:
            logger.warning(
                f'Unexpected ReplayPhaseUpdateAction. Already in phase. Observation:\n {repr(obs)}',
            )
        else:
            state.replay_phase = new_phase
            agent.replay_phase_changed(new_phase)


def get_replay_observation_message(
    obs: ReplayObservation, max_message_chars: int
) -> Message:
    """Create a message to explain the observation."""
    if isinstance(obs, ReplayToolCmdOutputObservation):
        # if it doesn't have tool call metadata, it was triggered by a user action
        if obs.tool_call_metadata is None:
            text = truncate_content(
                f'\nObserved result of replay command executed by user:\n{obs.content}',
                max_message_chars,
            )
        else:
            text = obs.content
        message = Message(role='user', content=[TextContent(text=text)])
    elif isinstance(obs, ReplayPhaseUpdateObservation):
        new_phase = obs.new_phase
        if new_phase == ReplayDebuggingPhase.Edit:
            text = replay_prompt_phase_edit(obs)
        else:
            raise NotImplementedError(f'Unhandled ReplayPhaseUpdateAction: {new_phase}')
        message = Message(role='user', content=[TextContent(text=text)])
    else:
        raise NotImplementedError(
            f"Unhandled observation type: {obs.__class__.__name__} ({getattr(obs, 'observation', None)})"
        )
    return message
