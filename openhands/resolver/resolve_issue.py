# flake8: noqa: E501

import asyncio
import dataclasses
import json
import os
import pathlib
import re
import shutil
import subprocess
import traceback
from typing import Any
from uuid import uuid4

# from git import Repo
from termcolor import colored

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
    ErrorObservation,
    Observation,
)
from openhands.events.stream import EventStreamSubscriber
from openhands.resolver.github_issue import GithubIssue
from openhands.resolver.issue_definitions import (
    IssueHandler,
    IssueHandlerInterface,
    PRHandler,
)
from openhands.resolver.resolver_output import ResolverOutput
from openhands.resolver.utils import (
    codeact_user_response,
    reset_logger_for_multiprocessing,
)
from openhands.runtime.base import Runtime

# Don't make this confgurable for now, unless we have other competitive agents
AGENT_CLASS = 'CodeActAgent'


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

    action = CmdRunAction(command='git config --global core.pager ""')
    logger.info(action, extra={'msg_type': 'ACTION'})
    obs = runtime.run_action(action)
    logger.info(obs, extra={'msg_type': 'OBSERVATION'})
    if not isinstance(obs, CmdOutputObservation) or obs.exit_code != 0:
        raise RuntimeError(f'Failed to set git config.\n{obs}')


async def get_git_patch(runtime: Runtime, base_commit: str) -> str:
    """Get the git diff for the current commit.

    Args:
        base_commit: The base commit to compare against
    """
    n_retries = 0
    git_patch = None
    while n_retries < 5:
        action = CmdRunAction(
            command=f'git diff --no-color --cached {base_commit}',
            keep_prompt=False,
        )
        action.timeout = 600 + 100 * n_retries
        logger.info(action, extra={'msg_type': 'ACTION'})
        obs = runtime.run_action(action)
        logger.info(obs, extra={'msg_type': 'OBSERVATION'})
        n_retries += 1
        if isinstance(obs, CmdOutputObservation):
            if obs.exit_code == 0:
                git_patch = obs.content.strip()
                break
            else:
                logger.info('Failed to get git diff, retrying...')
                await asyncio.sleep(10)
        elif isinstance(obs, ErrorObservation):
            logger.error(f'Error occurred: {obs.content}. Retrying...')
            await asyncio.sleep(10)
        else:
            raise ValueError(f'Unexpected observation type: {type(obs)}')
    if git_patch is None:
        raise RuntimeError('Failed to get git diff')
    return git_patch


def strip_replay_comment(file_name: str, line: str):
    """Remove a replay comment with the specified text from a file.

    Args:
        file_name: Path to the file containing the comment
        line: The line containing the comment to remove
    """
    logger.info(f'Stripping Replay comment from {file_name}: "{line}"')
    if not os.path.exists(file_name):
        raise ValueError(f'File {file_name} does not exist')
    with open(file_name, 'r') as f:
        lines = f.readlines()

    # Find and remove the line
    if line + '\n' in lines:
        lines.remove(line + '\n')

    # Write back the file without the comment
    with open(file_name, 'w') as f:
        f.writelines(lines)


def strip_replay_comments(git_patch: str) -> None:
    """Strip all replay comments from the git patch."""
    logger.info('Stripping Replay comments...')

    logger.info('Dumping contents of /workspace...')
    for root, dirs, files in os.walk('/workspace'):
        logger.info(f'Root: {root}, Dirs: {dirs}, Files: {files}')
    logger.info('Done dumping contents of /workspace.')

    lines = git_patch.splitlines()
    current_file = ''
    for line in lines:
        logger.info(f'Processing line: {line}')
        if re.match(r'^\+\+\+ b/', line):
            current_file = f'/workspace/{line[6:]}'
        if re.match(r'^\+.*\s+//', line.lstrip()):
            strip_replay_comment(current_file, line[1:])


async def complete_runtime(
    runtime: Runtime,
    base_commit: str,
) -> dict[str, Any]:
    """Complete the runtime for the agent.

    This function is called before the runtime is used to run the agent.
    If you need to do something in the sandbox to get the correctness metric after
    the agent has run, modify this function.
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
        raise RuntimeError(
            f'Failed to change directory to /workspace. Observation: {obs}'
        )

    action = CmdRunAction(command='git config --global core.pager ""')
    logger.info(action, extra={'msg_type': 'ACTION'})
    obs = runtime.run_action(action)
    logger.info(obs, extra={'msg_type': 'OBSERVATION'})
    if not isinstance(obs, CmdOutputObservation) or obs.exit_code != 0:
        raise RuntimeError(f'Failed to set git config. Observation: {obs}')

    action = CmdRunAction(command='git config --global --add safe.directory /workspace')
    logger.info(action, extra={'msg_type': 'ACTION'})
    obs = runtime.run_action(action)
    logger.info(obs, extra={'msg_type': 'OBSERVATION'})
    if not isinstance(obs, CmdOutputObservation) or obs.exit_code != 0:
        raise RuntimeError(f'Failed to set git config. Observation: {obs}')

    action = CmdRunAction(command='git add -A')
    logger.info(action, extra={'msg_type': 'ACTION'})
    obs = runtime.run_action(action)
    logger.info(obs, extra={'msg_type': 'OBSERVATION'})
    if not isinstance(obs, CmdOutputObservation) or obs.exit_code != 0:
        raise RuntimeError(f'Failed to git add. Observation: {obs}')

    base_git_patch = await get_git_patch(runtime, base_commit)
    strip_replay_comments(base_git_patch)

    git_patch = await get_git_patch(runtime, base_commit)

    logger.info('-' * 30)
    logger.info('END Runtime Completion Fn')
    logger.info('-' * 30)
    return {'git_patch': git_patch}


# def init_replay(replay_dir: str | Path) -> None:
#     replay_dir = Path(replay_dir)

#     if not replay_dir.exists():
#         replay_dir.mkdir(parents=True)

#     repo_urls = [
#         'https://github.com/replayio-public/replayapi',
#         'https://github.com/replayio/devtools',
#     ]
#     for repo_url in repo_urls:
#         repo_name = repo_url.split('/')[-1]
#         repo_path = replay_dir / repo_name
#         logger.info(f'[REPLAY] Preparing {repo_name} in {repo_path}')
#         if not repo_path.exists():
#             logger.info(
#                 f'[REPLAY] Repository {repo_name} not found in {replay_dir}, cloning...'
#             )
#             Repo.clone_from(repo_url, str(repo_path))

#         # Now mypy should see Repo as a proper class.
#         repo = Repo(str(repo_path))

#         if repo.active_branch.name != 'main':
#             raise ValueError(f'Repository {repo_name} not on main branch')

#         origin = repo.remote('origin')
#         origin.pull()

#     # Execute the dependencies installation script
#     install_script = replay_dir / 'replayapi' / 'scripts' / 'install-deps.sh'
#     subprocess.run([str(install_script)], check=True)


async def process_issue(
    issue: GithubIssue,
    base_commit: str,
    max_iterations: int,
    llm_config: LLMConfig,
    output_dir: str,
    runtime_container_image: str,
    prompt_template: str,
    issue_handler: IssueHandlerInterface,
    repo_instruction: str | None = None,
    reset_logger: bool = False,
) -> ResolverOutput:
    # Setup the logger properly, so you can run multi-processing to parallelize processing
    if reset_logger:
        log_dir = os.path.join(output_dir, 'infer_logs')
        reset_logger_for_multiprocessing(logger, str(issue.number), log_dir)
    else:
        logger.info(f'Starting fixing issue {issue.number}.')

    workspace_base = os.path.join(
        output_dir, 'workspace', f'{issue_handler.issue_type}_{issue.number}'
    )
    # Get the absolute path of the workspace base
    workspace_base = os.path.abspath(workspace_base)
    # write the repo to the workspace
    if os.path.exists(workspace_base):
        shutil.rmtree(workspace_base)
    shutil.copytree(os.path.join(output_dir, 'repo'), workspace_base)

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

    runtime = create_runtime(config)
    await runtime.connect()

    # # Force-update the Replay repos, if necessary:
    # if config.replay.dir is None:
    #     raise ValueError('config.replay.dir is not set.')
    # init_replay(config.replay.dir)

    async def on_event(evt):
        logger.info(evt)

    runtime.event_stream.subscribe(EventStreamSubscriber.MAIN, on_event, str(uuid4()))

    initialize_runtime(runtime)

    instruction, images_urls = issue_handler.get_instruction(
        issue, prompt_template, repo_instruction
    )
    # Here's how you can run the agent (similar to the `main` function) and get the final task state
    action = MessageAction(content=instruction, image_urls=images_urls)
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

    # Get git patch
    return_val = await complete_runtime(runtime, base_commit)
    git_patch = return_val['git_patch']
    logger.info(
        f'Got git diff for instance {issue.number}:\n--------\n{git_patch}\n--------'
    )

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
        # determine success based on the history and the issue description
        success, comment_success, success_explanation = issue_handler.guess_success(
            issue, state.history, llm_config
        )

        if issue_handler.issue_type == 'pr' and comment_success:
            success_log = 'I have updated the PR and resolved some of the issues that were cited in the pull request review. Specifically, I identified the following revision requests, and all the ones that I think I successfully resolved are checked off. All the unchecked ones I was not able to resolve, so manual intervention may be required:\n'
            try:
                explanations = json.loads(success_explanation)
            except json.JSONDecodeError:
                logger.error(
                    f'Failed to parse success_explanation as JSON: {success_explanation}'
                )
                explanations = [str(success_explanation)]  # Use raw string as fallback

            for success_indicator, explanation in zip(comment_success, explanations):
                status = (
                    colored('[X]', 'red')
                    if success_indicator
                    else colored('[ ]', 'red')
                )
                bullet_point = colored('-', 'yellow')
                success_log += f'\n{bullet_point} {status}: {explanation}'
            logger.info(success_log)
        last_error = state.last_error if state.last_error else None

    # Save the output
    output = ResolverOutput(
        issue=issue,
        issue_type=issue_handler.issue_type,
        instruction=instruction,
        base_commit=base_commit,
        git_patch=git_patch,
        history=histories,
        metrics=metrics,
        success=success,
        comment_success=comment_success,
        success_explanation=success_explanation,
        error=last_error,
    )
    return output


def issue_handler_factory(
    issue_type: str, owner: str, repo: str, token: str
) -> IssueHandlerInterface:
    if issue_type == 'issue':
        return IssueHandler(owner, repo, token)
    elif issue_type == 'pr':
        return PRHandler(owner, repo, token)
    else:
        raise ValueError(f'Invalid issue type: {issue_type}')


async def resolve_issue(
    owner: str,
    repo: str,
    token: str,
    username: str,
    max_iterations: int,
    output_dir: str,
    llm_config: LLMConfig,
    runtime_container_image: str,
    prompt_template: str,
    issue_type: str,
    repo_instruction: str | None,
    issue_number: int,
    comment_id: int | None,
    target_branch: str | None = None,
    reset_logger: bool = False,
) -> None:
    """Resolve a single github issue.

    Args:
        owner: Github owner of the repo.
        repo: Github repository to resolve issues in form of `owner/repo`.
        token: Github token to access the repository.
        username: Github username to access the repository.
        max_iterations: Maximum number of iterations to run.
        output_dir: Output directory to write the results.
        llm_config: Configuration for the language model.
        runtime_container_image: Container image to use.
        prompt_template: Prompt template to use.
        issue_type: Type of issue to resolve (issue or pr).
        repo_instruction: Repository instruction to use.
        issue_number: Issue number to resolve.
        comment_id: Optional ID of a specific comment to focus on.
        target_branch: Optional target branch to create PR against (for PRs).
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

    issue_handler = issue_handler_factory(issue_type, owner, repo, token)

    # Load dataset
    issues: list[GithubIssue] = issue_handler.get_converted_issues(
        issue_numbers=[issue_number], comment_id=comment_id
    )

    issue = issues[0]

    if comment_id is not None:
        if (
            issue_type == 'pr'
            and not issue.review_comments
            and not issue.review_threads
            and not issue.thread_comments
        ):
            raise ValueError(
                f'Comment ID {comment_id} did not have a match for issue {issue.number}'
            )

        if issue_type == 'issue' and not issue.thread_comments:
            raise ValueError(
                f'Comment ID {comment_id} did not have a match for issue {issue.number}'
            )

    # TEST METADATA
    model_name = llm_config.model.split('/')[-1]

    pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)
    pathlib.Path(os.path.join(output_dir, 'infer_logs')).mkdir(
        parents=True, exist_ok=True
    )
    logger.info(f'Using output directory: {output_dir}')

    # checkout the repo
    repo_dir = os.path.join(output_dir, 'repo')
    if not os.path.exists(repo_dir):
        checkout_output = subprocess.check_output(
            [
                'git',
                'clone',
                f'https://{username}:{token}@github.com/{owner}/{repo}',
                f'{output_dir}/repo',
            ]
        ).decode('utf-8')
        if 'fatal' in checkout_output:
            raise RuntimeError(f'Failed to clone repository: {checkout_output}')

    # get the commit id of current repo for reproducibility
    base_commit = (
        subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir)
        .decode('utf-8')
        .strip()
    )
    logger.info(f'Base commit: {base_commit}')

    if repo_instruction is None:
        # Check for .openhands_instructions file in the workspace directory
        openhands_instructions_path = os.path.join(repo_dir, '.openhands_instructions')
        if os.path.exists(openhands_instructions_path):
            with open(openhands_instructions_path, 'r') as f:
                repo_instruction = f.read()

    # OUTPUT FILE
    output_file = os.path.join(output_dir, 'output.jsonl')
    logger.info(f'Writing output to {output_file}')

    # Check if this issue was already processed
    if os.path.exists(output_file):
        with open(output_file, 'r') as f:
            for line in f:
                data = ResolverOutput.model_validate_json(line)
                if data.issue.number == issue_number:
                    logger.warning(
                        f'Issue {issue_number} was already processed. Skipping.'
                    )
                    return

    output_fp = open(output_file, 'a')

    logger.info(
        f'Resolving issue {issue_number} with Agent {AGENT_CLASS}, model {model_name}, max iterations {max_iterations}.'
    )

    try:
        # checkout to pr branch if needed
        if issue_type == 'pr':
            branch_to_use = target_branch if target_branch else issue.head_branch
            logger.info(
                f'Checking out to PR branch {target_branch} for issue {issue.number}'
            )

            if not branch_to_use:
                raise ValueError('Branch name cannot be None')

            # Fetch the branch first to ensure it exists locally
            fetch_cmd = ['git', 'fetch', 'origin', branch_to_use]
            subprocess.check_output(
                fetch_cmd,
                cwd=repo_dir,
            )

            # Checkout the branch
            checkout_cmd = ['git', 'checkout', branch_to_use]
            subprocess.check_output(
                checkout_cmd,
                cwd=repo_dir,
            )

            # Update issue's base_branch if using custom target branch
            if target_branch:
                issue.base_branch = target_branch

            base_commit = (
                subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_dir)
                .decode('utf-8')
                .strip()
            )

        output = await process_issue(
            issue,
            base_commit,
            max_iterations,
            llm_config,
            output_dir,
            runtime_container_image,
            prompt_template,
            issue_handler,
            repo_instruction,
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

    parser = argparse.ArgumentParser(description='Resolve a single issue from Github.')
    parser.add_argument(
        '--repo',
        type=str,
        required=True,
        help='Github repository to resolve issues in form of `owner/repo`.',
    )
    parser.add_argument(
        '--token',
        type=str,
        default=None,
        help='Github token to access the repository.',
    )
    parser.add_argument(
        '--username',
        type=str,
        default=None,
        help='Github username to access the repository.',
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
        '--issue-number',
        type=int,
        required=True,
        help='Issue number to resolve.',
    )
    parser.add_argument(
        '--comment-id',
        type=int_or_none,
        required=False,
        default=None,
        help='Resolve a specific comment',
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='output',
        help='Output directory to write the results.',
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
        '--repo-instruction-file',
        type=str,
        default=None,
        help='Path to the repository instruction file in text format.',
    )
    parser.add_argument(
        '--issue-type',
        type=str,
        default='issue',
        choices=['issue', 'pr'],
        help='Type of issue to resolve, either open issue or pr comments.',
    )
    parser.add_argument(
        '--target-branch',
        type=str,
        default=None,
        help="Target branch to pull and create PR against (for PRs). If not specified, uses the PR's base branch.",
    )

    my_args = parser.parse_args()

    # NOTE: The correct image name is passed in as argument to the script by the GH action.
    #       If we don't pass it in, it will auto-build it on the fly. Useful for local dev loop.
    runtime_container_image = my_args.runtime_container_image
    owner, repo = my_args.repo.split('/')
    token = my_args.token if my_args.token else os.getenv('GITHUB_TOKEN')
    username = my_args.username if my_args.username else os.getenv('GITHUB_USERNAME')
    if not username:
        raise ValueError('Github username is required.')

    if not token:
        raise ValueError('Github token is required.')

    llm_config = LLMConfig(
        model=my_args.llm_model or os.environ['LLM_MODEL'],
        api_key=my_args.llm_api_key or os.environ['LLM_API_KEY'],
        base_url=my_args.llm_base_url or os.environ.get('LLM_BASE_URL', None),
    )

    repo_instruction = None
    if my_args.repo_instruction_file:
        with open(my_args.repo_instruction_file, 'r') as f:
            repo_instruction = f.read()

    issue_type = my_args.issue_type

    # Read the prompt template
    prompt_file = my_args.prompt_file
    if prompt_file is None:
        if issue_type == 'issue':
            prompt_file = os.path.join(
                os.path.dirname(__file__), 'prompts/resolve/basic.jinja'
            )
        else:
            prompt_file = os.path.join(
                os.path.dirname(__file__), 'prompts/resolve/basic-followup.jinja'
            )
    with open(prompt_file, 'r') as f:
        prompt_template = f.read()

    asyncio.run(
        resolve_issue(
            owner=owner,
            repo=repo,
            token=token,
            username=username,
            runtime_container_image=runtime_container_image,
            max_iterations=my_args.max_iterations,
            output_dir=my_args.output_dir,
            llm_config=llm_config,
            prompt_template=prompt_template,
            issue_type=issue_type,
            repo_instruction=repo_instruction,
            issue_number=my_args.issue_number,
            comment_id=my_args.comment_id,
            target_branch=my_args.target_branch,
        )
    )


if __name__ == '__main__':
    main()
