import json

from openhands.core.logger import openhands_logger as logger
from openhands.events.observation.replay import ReplayPhaseUpdateObservation


def enhance_prompt(prompt: str, prefix: str, suffix: str):
    if prefix != '':
        prompt = f'{prefix}\n\n{prompt}'
    if suffix != '':
        prompt = f'{prompt}\n\n{suffix}'
    logger.info(f'[REPLAY] Enhanced prompt:\n{prompt}')
    return prompt


def replay_prompt_phase_analysis(command_result: dict, prompt: str) -> str:
    prefix = ''
    suffix = """
# Instructions
0. Take a look at below `Initial Analysis`, based on a recorded trace of the bug. Pay special attention to `IMPORTANT_NOTES`.
1. State the main problem statement. It MUST address `IMPORTANT_NOTES`. It must make sure that the application won't crash. It must fix the issue.
2. Propose a plan to fix or investigate with multiple options in order of priority.
3. Then use the `inspect-*` tools to investigate.
4. Once found, `submit-hypothesis`.


# Initial Analysis
""" + json.dumps(command_result, indent=2)
    return enhance_prompt(prompt, prefix, suffix)


def replay_prompt_phase_analysis_legacy(command_result: dict, prompt: str) -> str:
    # Old workflow: initial-analysis left hints in form of source code annotations.
    annotated_repo_path = command_result.get('annotatedRepo', '')
    comment_text = command_result.get('commentText', '')
    react_component_name = command_result.get('reactComponentName', '')
    console_error = command_result.get('consoleError', '')
    # start_location = result.get('startLocation', '')
    start_name = command_result.get('startName', '')

    # TODO: Move this to a prompt template file.
    if comment_text:
        if react_component_name:
            prefix = (
                f'There is a change needed to the {react_component_name} component.\n'
            )
        else:
            prefix = f'There is a change needed in {annotated_repo_path}:\n'
        prefix += f'{comment_text}\n\n'
    elif console_error:
        prefix = f'There is a change needed in {annotated_repo_path} to fix a console error that has appeared unexpectedly:\n'
        prefix += f'{console_error}\n\n'

    prefix += '<IMPORTANT>\n'
    prefix += 'Information about a reproduction of the problem is available in source comments.\n'
    prefix += 'You must search for these comments and use them to get a better understanding of the problem.\n'
    prefix += f'The first reproduction comment to search for is named {start_name}. Start your investigation there.\n'
    prefix += '</IMPORTANT>\n'

    suffix = ''

    return enhance_prompt(prompt, prefix, suffix)


def replay_prompt_phase_edit(obs: ReplayPhaseUpdateObservation) -> str:
    # Tell the agent to stop analyzing and start editing:
    return """
You have concluded the analysis.

IMPORTANT: NOW review, then implement the hypothesized changes using tools. The code is available in the workspace. Start by answering these questions:
  1. What is the goal of the investigation according to the initial prompt and initial analysis? IMPORTANT. PAY ATTENTION TO THIS. THIS IS THE ENTRY POINT OF EVERYTHING.
  2. Given (1), is the hypothesis's `problem` description correct? Does it match the goal of the investigation?
  3. Do the `editSuggestions` actually address the issue?
  4. Rephrase the hypothesis so that it is consistent and correct.
"""
