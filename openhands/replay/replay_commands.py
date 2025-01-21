import json
import re
from typing import Any, cast

from openhands.controller.state.state import State
from openhands.core.logger import openhands_logger as logger
from openhands.events.action.action import Action
from openhands.events.action.message import MessageAction
from openhands.events.action.replay import ReplayInternalCmdRunAction
from openhands.events.observation.replay import ReplayInternalCmdOutputObservation
from openhands.replay.replay_prompts import replay_prompt_phase_analysis
from openhands.replay.replay_types import AnalysisToolMetadata, AnnotateResult


def scan_recording_id(issue: str) -> str | None:
    match = re.search(r'\.replay\.io\/recording\/([a-zA-Z0-9-]+)', issue)
    if not match:
        return None

    id_maybe_with_title = match.group(1)
    match2 = re.search(r'^.*?--([a-zA-Z0-9-]+)$', id_maybe_with_title)

    if match2:
        return match2.group(1)
    return id_maybe_with_title


# Produce the command string for the `annotate-execution-points` command.
def start_initial_analysis(
    thought: str, is_workspace_repo: bool
) -> ReplayInternalCmdRunAction:
    command_input: dict[str, Any] = dict()
    command_input['prompt'] = thought

    action = ReplayInternalCmdRunAction(
        command_name='initial-analysis',
        command_args=command_input,
        in_workspace_dir=is_workspace_repo,
        thought=thought,
        keep_prompt=False,
        # hidden=True, # The hidden implementation causes problems, so we added replay stuff to `filter_out` instead.
    )
    return action


def replay_enhance_action(state: State, is_workspace_repo: bool) -> Action | None:
    enhance_action_id = state.extra_data.get('replay_enhance_prompt_id')
    if enhance_action_id is None:
        # 1. Get current user prompt.
        latest_user_message = state.get_last_user_message()
        if latest_user_message:
            logger.debug(f'[REPLAY] latest_user_message id is {latest_user_message.id}')
            # 2. Check if it has a recordingId.
            recording_id = scan_recording_id(latest_user_message.content)
            if recording_id:
                # 3. Analyze recording and start the enhancement action.
                logger.debug(
                    f'[REPLAY] Enhancing prompt for Replay recording "{recording_id}"...'
                )
                state.extra_data['replay_enhance_prompt_id'] = latest_user_message.id
                logger.info('[REPLAY] stored latest_user_message id in state')
                return start_initial_analysis(
                    latest_user_message.content, is_workspace_repo
                )
    return None


def safe_parse_json(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def split_metadata(result):
    if 'metadata' not in result:
        return {}, result
    metadata = result['metadata']
    data = dict(result)
    del data['metadata']
    return metadata, data


def handle_replay_internal_command_observation(
    state: State, observation: ReplayInternalCmdOutputObservation
) -> AnalysisToolMetadata | None:
    """
    Enhance the user prompt with the results of the replay analysis.
    Returns the metadata needed for the agent to switch to analysis tools.
    """
    enhance_action_id = state.extra_data.get('replay_enhance_prompt_id')
    enhance_observed = state.extra_data.get('replay_enhance_observed', False)
    if enhance_action_id is not None and not enhance_observed:
        user_message: MessageAction | None = next(
            (
                m
                for m in state.history
                if m.id == enhance_action_id and isinstance(m, MessageAction)
            ),
            None,
        )
        assert user_message
        state.extra_data['replay_enhance_observed'] = True

        # Deserialize stringified result.
        result: AnnotateResult = cast(
            AnnotateResult, safe_parse_json(observation.content)
        )

        # Get metadata and enhance prompt.
        if result and 'metadata' in result:
            # initial-analysis provides metadata needed for tool use.
            metadata, command_result = split_metadata(result)
            replay_prompt_phase_analysis(command_result, user_message)
            return metadata
        else:
            logger.warning(
                f'[REPLAY] Replay command result cannot be interpreted. Observed content: {str(observation.content)}'
            )

    return None
