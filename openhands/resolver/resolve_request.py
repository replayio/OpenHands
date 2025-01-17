# flake8: noqa: E501

import asyncio
import dataclasses
import os
import pathlib
import re
import shutil
import traceback
from typing import Any
from uuid import uuid4

import jinja2
from litellm import BaseModel

# from git import Repo
from openhands.controller.state.state import State
from openhands.core.config import (
    AgentConfig,
    AppConfig,
    LLMConfig,
    SandboxConfig,
)
from openhands.core.config.replay_config import ReplayConfig
from openhands.core.logger import openhands_logger as logger
from openhands.core.main import create_runtime, run_controller
from openhands.events.action import CmdRunAction, MessageAction
from openhands.events.observation import (
    CmdOutputObservation,
    Observation,
)
from openhands.events.stream import EventStreamSubscriber
from openhands.resolver.utils import (
    codeact_user_response,
    reset_logger_for_multiprocessing,
)
from openhands.runtime.base import Runtime

# Don't make this confgurable for now, unless we have other competitive agents
AGENT_CLASS = 'CodeActAgent'


# Duplicate ResolverOutput here and make changes we need (ResolverOutput is github specific)
class ResolverOutput(BaseModel):
    # NOTE: User-specified
    instruction: str
    history: list[dict[str, Any]]
    metrics: dict[str, Any] | None
    success: bool
    comment_success: list[bool] | None
    success_explanation: str
    error: str | None


def initialize_runtime(
    runtime: Runtime,
):
    """Initialize the runtime for the agent.

    This function is called before the runtime is used to run the agent.
    Currently it does nothing.
    """
    logger.info('-' * 30)
    logger.info('BEGIN Runtime Completion Fn')
    logger.info('-' * 30)
    obs: Observation

    action = CmdRunAction(command='cd /workspace')
    logger.info(action, extra={'msg_type': 'ACTION'})
    obs = runtime.run_action(action)
    logger.info(obs, extra={'msg_type': 'OBSERVATION'})
    if not isinstance(obs, CmdOutputObservation) or obs.exit_code != 0:
        raise RuntimeError(f'Failed to change directory to /workspace.\n{obs}')


REPLAY_COMMENT_PATTERN = r'^\+.*(?:\s+//|\{/\*.*?\*/\})'


def strip_replay_comments(base_path: str, patch: str) -> None:
    """Strip replay comments from files referenced in a patch.

    Args:
        base_path: Root path for the working directory
        patch: Patch content containing file changes
    """
    current_file = ''
    file_changes: dict[str, list[str]] = {}

    # First pass: collect all changes per file
    for line in patch.splitlines():
        modified_prefix = '+++ modified/'
        if line.startswith(modified_prefix):
            current_file = os.path.join(
                base_path, line.split('\t')[0][len(modified_prefix) :]
            )
            continue

        if re.match(REPLAY_COMMENT_PATTERN, line.lstrip()):
            if current_file not in file_changes:
                file_changes[current_file] = []
            file_changes[current_file].append(line[1:])

    # Second pass: apply changes to each file once
    for file_name, comments in file_changes.items():
        if not os.path.exists(file_name):
            logger.warning(f'File {file_name} does not exist')
            continue

        with open(file_name, 'r') as f:
            lines = f.readlines()

        # Remove all comments from this file
        for comment in comments:
            if comment + '\n' in lines:
                lines.remove(comment + '\n')

        with open(file_name, 'w') as f:
            f.writelines(lines)
            logger.info(f'Stripped {len(comments)} comments from {file_name}')

    logger.info(f'[REPLAY] Stripped {len(file_changes)} files: {file_changes.keys()}')


async def complete_runtime(
    runtime: Runtime,
) -> dict[str, Any]:
    """Complete the runtime for the agent.

    This function is called before the runtime is used to run the agent.
    If you need to do something in the sandbox to get the correctness metric after
    the agent has run, modify this function.
    """
    logger.info('-' * 30)
    logger.info('BEGIN Runtime Completion Fn')
    logger.info('-' * 30)

    logger.info('Downloading /workspace from runtime')
    zip_path = runtime.copy_from('/workspace')
    logger.info(f' -> {zip_path}')

    # notyet(toshok)
    #
    # Strip comments.
    # base_git_patch = await get_git_patch(runtime, base_commit)
    # assert runtime.config.workspace_base is not None
    # strip_replay_comments(runtime.config.workspace_base, base_git_patch)
    #
    # Get final patch.
    # git_patch = await get_git_patch(runtime, base_commit)

    logger.info('-' * 30)
    logger.info('END Runtime Completion Fn')
    logger.info('-' * 30)
    return {
        # 'git_patch': git_patch,
        'zip_path': zip_path,
    }


async def process_request(
    request_id: str,
    user_id: int,
    max_iterations: int,
    llm_config: LLMConfig,
    output_dir: str,
    runtime_container_image: str,
    prompt_template: str,
    conversation: str,
    additional_instruction: str | None = None,
    reset_logger: bool = False,
) -> ResolverOutput:
    # Setup the logger properly, so you can run multi-processing to parallelize processing
    if reset_logger:
        log_dir = os.path.join(output_dir, 'infer_logs')
        reset_logger_for_multiprocessing(logger, request_id, log_dir)
    else:
        logger.info('Starting fixing request.')

    workspace_base = os.path.join(
        output_dir,
        'workspace',
        request_id,
    )
    # Get the absolute path of the workspace base
    workspace_base = os.path.abspath(workspace_base)

    config = AppConfig(
        debug=True,
        default_agent='CodeActAgent',
        runtime='eventstream',
        max_budget_per_task=4,
        max_iterations=max_iterations,
        sandbox=SandboxConfig(
            runtime_container_image=runtime_container_image,
            enable_auto_lint=False,
            use_host_network=False,
            # large enough timeout, since some testcases take very long to run
            timeout=300,
            user_id=user_id,
        ),
        replay=ReplayConfig(
            # dir=os.environ.get(
            #     'REPLAY_DIR', os.path.abspath(os.path.join(output_dir, 'replay'))
            # ),
            dir=os.environ.get('REPLAY_DIR', None),
            api_key=os.environ.get('REPLAY_API_KEY', None),
        ),
        # do not mount workspace
        workspace_base=workspace_base,
        workspace_mount_path=workspace_base,
        agents={
            'CodeActAgent': AgentConfig(
                is_workspace_repo=True, disabled_microagents=['github']
            )
        },
    )
    config.set_llm_config(llm_config)

    logger.info('creating and connecting to our runtime')

    runtime = create_runtime(config)
    await runtime.connect()

    logger.info('connected to runtime!')

    async def on_event(evt):
        logger.info(evt)

    runtime.event_stream.subscribe(EventStreamSubscriber.MAIN, on_event, str(uuid4()))

    initialize_runtime(runtime)

    instruction = get_instruction(prompt_template, conversation, additional_instruction)
    # Here's how you can run the agent (similar to the `main` function) and get the final task state
    action = MessageAction(content=instruction)
    try:
        state: State | None = await run_controller(
            config=config,
            initial_user_action=action,
            runtime=runtime,
            fake_user_response_fn=codeact_user_response,
        )
        if state is None:
            raise RuntimeError('Failed to run the agent.')
    except (ValueError, RuntimeError) as e:
        error_msg = f'Agent failed with error: {str(e)}'
        logger.error(error_msg)
        state = None
        last_error: str | None = error_msg

    return_val = await complete_runtime(runtime)

    # move the new contents of the workspace to the output directory
    zip_path = return_val['zip_path']

    if os.path.exists(workspace_base):
        shutil.rmtree(workspace_base)

    os.makedirs(workspace_base, exist_ok=True)

    shutil.unpack_archive(zip_path, workspace_base, format='zip')
    if user_id != os.getuid():
        shutil.chown(workspace_base, user=user_id)

    # Serialize histories and set defaults for failed state
    if state is None:
        histories = []
        metrics = None
        success = False
        comment_success = None
        success_explanation = 'Agent failed to run'
        last_error = 'Agent failed to run or crashed'
    else:
        histories = [dataclasses.asdict(event) for event in state.history]
        metrics = state.metrics.get() if state.metrics else None

        # XXX(toshok) we definitely need to stop lying to ourselves
        success = True
        comment_success = None
        success_explanation = 'Agent succeeded brilliantly.  10/10 no notes'

        # # determine success based on the history and the issue description
        # success, comment_success, success_explanation = issue_handler.guess_success(
        #     issue, state.history, llm_config
        # )

        # if issue_handler.issue_type == 'pr' and comment_success:
        #     success_log = 'I have updated the PR and resolved some of the issues that were cited in the pull request review. Specifically, I identified the following revision requests, and all the ones that I think I successfully resolved are checked off. All the unchecked ones I was not able to resolve, so manual intervention may be required:\n'
        #     try:
        #         explanations = json.loads(success_explanation)
        #     except json.JSONDecodeError:
        #         logger.error(
        #             f'Failed to parse success_explanation as JSON: {success_explanation}'
        #         )
        #         explanations = [str(success_explanation)]  # Use raw string as fallback

        #     for success_indicator, explanation in zip(comment_success, explanations):
        #         status = (
        #             colored('[X]', 'red')
        #             if success_indicator
        #             else colored('[ ]', 'red')
        #         )
        #         bullet_point = colored('-', 'yellow')
        #         success_log += f'\n{bullet_point} {status}: {explanation}'
        #     logger.info(success_log)
        last_error = state.last_error if state.last_error else None

    # Save the output
    output = ResolverOutput(
        instruction=instruction,
        history=histories,
        metrics=metrics,
        success=success,
        comment_success=comment_success,
        success_explanation=success_explanation,
        error=last_error,
    )
    return output


def get_instruction(
    prompt_template: str,
    conversation: str,
    additional_instruction: str | None,
) -> str:
    template = jinja2.Template(prompt_template)
    return template.render(
        body=conversation,
        additional_instruction=additional_instruction,
    )


async def resolve_request(
    max_iterations: int,
    output_dir: str,
    request_id: str,
    user_id: int,
    llm_config: LLMConfig,
    runtime_container_image: str,
    prompt_template: str,
    conversation: str,
    additional_instruction: str | None,
    reset_logger: bool = False,
) -> None:
    """Resolve a single request.

    Args:
        max_iterations: Maximum number of iterations to run.
        output_dir: Output directory to write the results.
        request_id: Identifier (assumed to be unique) for this request.
        user_id: The user ID to use for writing files both in the sandbox and in this process.
        llm_config: Configuration for the language model.
        runtime_container_image: Container image to use.
        prompt_template: Prompt template to use.
        additional_instruction: request-level additional instructions.
        reset_logger: Whether to reset the logger for multiprocessing.
    """

    def exception_handler(_loop, context):
        exception = context.get('exception')
        if exception is not None:
            # We have an actual exception
            print(f'ERROR: {exception}')
            traceback.print_exception(
                type(exception), exception, exception.__traceback__
            )
        else:
            # No exception object; print the message and current stack
            message = context.get('message', 'Unknown error')
            print(f'ERROR: {message}')
            traceback.print_stack()

    loop = asyncio.get_running_loop()
    loop.set_exception_handler(exception_handler)

    # TEST METADATA
    model_name = llm_config.model.split('/')[-1]

    pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)
    pathlib.Path(os.path.join(output_dir, 'infer_logs')).mkdir(
        parents=True, exist_ok=True
    )
    logger.info(f'Using output directory: {output_dir}')

    workspace_base = os.path.join(
        output_dir,
        'workspace',
        request_id,
    )
    # Get the absolute path of the workspace base
    workspace_base = os.path.abspath(workspace_base)
    # copy the source over to the workspace
    if os.path.exists(workspace_base):
        shutil.rmtree(workspace_base)
    shutil.copytree(os.path.join(output_dir, 'source'), workspace_base)

    # change the owner of the workspace_base subtree to be user_id
    if user_id != os.getuid():
        shutil.chown(workspace_base, user=user_id)

    # OUTPUT FILE
    output_file = os.path.join(output_dir, 'output.jsonl')
    logger.info(f'Writing output to {output_file}')

    output_fp = open(output_file, 'a')

    logger.info(
        f'Resolving request with Agent {AGENT_CLASS}, model {model_name}, max iterations {max_iterations}.'
    )

    try:
        output = await process_request(
            request_id,
            user_id,
            max_iterations,
            llm_config,
            output_dir,
            runtime_container_image,
            prompt_template,
            conversation,
            additional_instruction,
            reset_logger,
        )
        output_fp.write(output.model_dump_json() + '\n')
        output_fp.flush()

    finally:
        output_fp.close()
        logger.info('Finished.')


def main():
    import argparse

    def int_or_none(value):
        if value.lower() == 'none':
            return None
        else:
            return int(value)

    parser = argparse.ArgumentParser(
        description='Resolve a request using a chat history and zip of source.'
    )
    parser.add_argument(
        '--runtime-container-image',
        type=str,
        default=None,
        help='Container image to use.',
    )
    parser.add_argument(
        '--max-iterations',
        type=int,
        default=50,
        help='Maximum number of iterations to run.',
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='output',
        help='Output directory to write the results.',
    )
    parser.add_argument(
        '--request-id',
        type=str,
        default=None,
        help='Identifier (assumed to be unique) for this request',
    )
    parser.add_argument(
        '--user-id',
        type=int,
        default=0,
        help='The user ID to use for writing files both in the sandbox and in this process',
    )
    parser.add_argument(
        '--llm-model',
        type=str,
        default=None,
        help='LLM model to use.',
    )
    parser.add_argument(
        '--llm-api-key',
        type=str,
        default=None,
        help='LLM API key to use.',
    )
    parser.add_argument(
        '--llm-base-url',
        type=str,
        default=None,
        help='LLM base URL to use.',
    )
    parser.add_argument(
        '--prompt-file',
        type=str,
        default=None,
        help='Path to the prompt template file in Jinja format.',
    )
    parser.add_argument(
        '--additional-instruction-file',
        type=str,
        default=None,
        help='Path to file of additional model instructions in text format.',
    )

    my_args = parser.parse_args()

    if my_args.request_id is None:
        raise ValueError('Request ID must be specified.')

    # NOTE: The correct image name is passed in as argument to the script by the GH action.
    #       If we don't pass it in, it will auto-build it on the fly. Useful for local dev loop.
    runtime_container_image = my_args.runtime_container_image

    llm_config = LLMConfig(
        model=my_args.llm_model or os.environ['LLM_MODEL'],
        api_key=my_args.llm_api_key or os.environ['LLM_API_KEY'],
        base_url=my_args.llm_base_url or os.environ.get('LLM_BASE_URL', None),
    )

    conversation = None
    conversation_file = os.path.join(my_args.output_dir, 'conversation.md')
    with open(conversation_file, 'r') as f:
        conversation = f.read()

    additional_instruction = None
    if my_args.additional_instruction_file:
        with open(my_args.additional_instruction_file, 'r') as f:
            additional_instruction = f.read()

    # Read the prompt template
    prompt_file = my_args.prompt_file
    if prompt_file is None:
        prompt_file = os.path.join(
            os.path.dirname(__file__), 'prompts/resolve_request/basic.jinja'
        )
    with open(prompt_file, 'r') as f:
        prompt_template = f.read()

    asyncio.run(
        resolve_request(
            runtime_container_image=runtime_container_image,
            max_iterations=my_args.max_iterations,
            output_dir=my_args.output_dir,
            request_id=my_args.request_id,
            user_id=my_args.user_id,
            llm_config=llm_config,
            prompt_template=prompt_template,
            conversation=conversation,
            additional_instruction=additional_instruction,
        )
    )


if __name__ == '__main__':
    main()
