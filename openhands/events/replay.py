import json
import re
from typing import Any, TypedDict, cast

from openhands.controller.state.state import State
from openhands.core.logger import openhands_logger as logger
from openhands.events.action.action import Action
from openhands.events.action.message import MessageAction
from openhands.events.action.replay import ReplayInternalCmdRunAction
from openhands.events.observation.replay import ReplayInternalCmdOutputObservation


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
def command_annotate_execution_points(
    thought: str, is_workspace_repo: bool
) -> ReplayInternalCmdRunAction:
    command_input: dict[str, Any] = dict()
    if is_workspace_repo:
        # NOTE: In the resolver workflow, the workdir path is equal to the repo path:
        #    1. We should not append the repo name to the path.
        #    2. The resolver also already hard-reset the repo, so forceDelete is not necessary.
        command_input['isWorkspaceRepoPath'] = True
        command_input['forceDelete'] = False
    else:
        command_input['isWorkspaceRepoPath'] = False
        command_input['forceDelete'] = True
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
                return command_annotate_execution_points(
                    latest_user_message.content, is_workspace_repo
                )
    return None


class AnnotatedLocation(TypedDict, total=False):
    filePath: str
    line: int


class AnalysisToolMetadata(TypedDict, total=False):
    recordingId: str


class AnnotateResult(TypedDict, total=False):
    point: str
    commentText: str | None
    annotatedRepo: str | None
    annotatedLocations: list[AnnotatedLocation] | None
    pointLocation: str | None
    metadata: AnalysisToolMetadata | None


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


def enhance_prompt(user_message: MessageAction, prefix: str, suffix: str | None = None):
    if prefix != '':
        user_message.content = f'{prefix}\n\n{user_message.content}'
    if suffix is not None:
        user_message.content = f'{user_message.content}\n\n{suffix}'
    logger.info(f'[REPLAY] Enhanced user prompt:\n{user_message.content}')


def handle_replay_internal_observation(
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

        result: AnnotateResult = cast(
            AnnotateResult, safe_parse_json(observation.content)
        )

        if result and 'metadata' in result:
            metadata, data = split_metadata(result)
            intro = 'This bug had a timetravel debugger recording which has been analyzed. Use the analysis results and the timetravel debugger `inspect-*` tools to find the bug. Once found `submit-hypothesis`, so your results can be used to implement the solution.\n'
            enhance_prompt(
                user_message,
                intro,
                f'## Initial Analysis\n{json.dumps(data, indent=2)}',
            )
            return metadata
        elif result and result.get('annotatedRepo'):
            annotated_repo_path = result.get('annotatedRepo', '')
            comment_text = result.get('commentText', '')
            react_component_name = result.get('reactComponentName', '')
            console_error = result.get('consoleError', '')
            # start_location = result.get('startLocation', '')
            start_name = result.get('startName', '')

            # TODO: Move this to a prompt template file.
            if comment_text:
                if react_component_name:
                    intro = f'There is a change needed to the {react_component_name} component.\n'
                else:
                    intro = f'There is a change needed in {annotated_repo_path}:\n'
                intro += f'{comment_text}\n\n'
            elif console_error:
                intro = f'There is a change needed in {annotated_repo_path} to fix a console error that has appeared unexpectedly:\n'
                intro += f'{console_error}\n\n'

            intro += '<IMPORTANT>\n'
            intro += 'Information about a reproduction of the problem is available in source comments.\n'
            intro += 'You must search for these comments and use them to get a better understanding of the problem.\n'
            intro += f'The first reproduction comment to search for is named {start_name}. Start your investigation there.\n'
            intro += '</IMPORTANT>\n'

            enhance_prompt(user_message, intro)
            return None
        else:
            logger.warning(
                f'[REPLAY] Replay observation cannot be interpreted. Observed content: {str(observation.content)}'
            )

    return None
