"""This file contains the function calling implementation for different actions.

This is similar to the functionality of `CodeActResponseParser`.
"""

import json

from litellm import (
    ChatCompletionMessageToolCall,
    ChatCompletionToolParam,
    ChatCompletionToolParamFunctionChunk,
)

from openhands.controller.state.state import State
from openhands.core.logger import openhands_logger as logger
from openhands.core.schema.replay import ReplayPhase
from openhands.events.action.replay import (
    ReplayAction,
    ReplayPhaseUpdateAction,
    ReplayToolCmdRunAction,
)


class ReplayTool(ChatCompletionToolParam):
    pass


def replay_tool(**kwargs):
    f = ChatCompletionToolParamFunctionChunk(**kwargs)
    return ReplayTool(type='function', function=f)


# ---------------------------------------------------------
# Tool: inspect-data
# ---------------------------------------------------------
_REPLAY_INSPECT_DATA_DESCRIPTION = """
Explains value, data flow and origin information for `expression` at `point`.
IMPORTANT: Prefer using inspect-data over inspect-point.
"""

ReplayInspectDataTool = replay_tool(
    name='inspect-data',
    description=_REPLAY_INSPECT_DATA_DESCRIPTION.strip(),
    parameters={
        'type': 'object',
        'properties': {
            'expression': {
                'type': 'string',
                'description': 'A valid JS expression. IMPORTANT: First pick the best expression. If the expression is an object: Prefer "array[0]" over "array" and "o.x" over "o" to get closer to the origin and creation site of important data points. Prefer nested object over primitive expressions.',
            },
            'point': {
                'type': 'string',
                'description': 'The point at which to inspect the runtime. The first point comes from the `thisPoint` in the Initial analysis.',
            },
            'explanation': {
                'type': 'string',
                'description': 'Give a concise explanation as to why you take this investigative step.',
            },
            'explanation_source': {
                'type': 'string',
                'description': 'Explain which data you saw in the previous analysis results that informs this step.',
            },
        },
        'required': ['expression', 'point', 'explanation', 'explanation_source'],
    },
)

# ---------------------------------------------------------
# Tool: inspect-point
# ---------------------------------------------------------
_REPLAY_INSPECT_POINT_DESCRIPTION = """
Explains dynamic control flow and data flow dependencies of the code at `point`.
Use this tool instead of `inspect-data` only when you don't have a specific data point to investigate.
"""

ReplayInspectPointTool = replay_tool(
    name='inspect-point',
    description=_REPLAY_INSPECT_POINT_DESCRIPTION.strip(),
    parameters={
        'type': 'object',
        'properties': {
            'point': {'type': 'string'},
        },
        'required': ['point'],
    },
)

# ---------------------------------------------------------
# Tool: SubmitHypothesis
# TODO: Divide this into multiple steps -
#   1. The first submission must be as simple as possible to take little computational effort from the analysis steps.
#   2. The second submission, after analysis has already concluded, must be as complete as possible.
# ---------------------------------------------------------
# _REPLAY_SUBMIT_HYPOTHESIS_DESCRIPTION = """
# Your investigation has yielded a complete thin slice from symptom to root cause,
# enough proof to let the `CodeEdit` agent take over to fix the bug.
# DO NOT GUESS. You must provide exact code in the exact right location to fix this bug,
# based on evidence you have gathered.
# """

# ReplaySubmitHypothesisTool = ReplayToolDefinition(
#     name='submit-hypothesis',
#     description=_REPLAY_SUBMIT_HYPOTHESIS_DESCRIPTION.strip(),
#     parameters={
#         'type': 'object',
#         'properties': {
#             'rootCauseHypothesis': {'type': 'string'},
#             'thinSlice': {
#                 'type': 'array',
#                 'items': {
#                     'type': 'object',
#                     'properties': {
#                         'point': {'type': 'string'},
#                         'code': {'type': 'string'},
#                         'role': {'type': 'string'},
#                     },
#                     'required': ['point', 'code', 'role'],
#                 },
#             },
#             'modifications': {
#                 'type': 'array',
#                 'items': {
#                     'type': 'object',
#                     'properties': {
#                         'kind': {
#                             'type': 'string',
#                             'enum': ['add', 'remove', 'modify'],
#                         },
#                         'newCode': {'type': 'string'},
#                         'oldCode': {'type': 'string'},
#                         'location': {'type': 'string'},
#                         'point': {'type': 'string'},
#                         # NOTE: Even though, we really want the `line` here, it will lead to much worse performance because the agent has a hard time computing correct line numbers from its point-based investigation.
#                         # Instead of requiring a line number, the final fix will be more involved, as explained in the issue.
#                         # see: https://linear.app/replay/issue/PRO-939/use-tools-data-flow-analysis-for-10608#comment-3b7ae176
#                         # 'line': {'type': 'number'},
#                         'briefExplanation': {'type': 'string'},
#                         'verificationProof': {'type': 'string'},
#                     },
#                     'required': [
#                         'kind',
#                         'location',
#                         'briefExplanation',
#                         # 'line',
#                         'verificationProof',
#                     ],
#                 },
#             },
#         },
#         'required': ['rootCauseHypothesis', 'thinSlice', 'modifications'],
#     },
# )
_REPLAY_SUBMIT_HYPOTHESIS_DESCRIPTION = """
# Use this tool to conclude your analysis and move on to code editing.
# """

ReplaySubmitHypothesisTool = replay_tool(
    name='submit-hypothesis',
    description=_REPLAY_SUBMIT_HYPOTHESIS_DESCRIPTION.strip(),
    parameters={
        'type': 'object',
        'properties': {
            'problem': {
                'type': 'string',
                'description': 'One-sentence explanation of the core problem that this will solve.',
            },
            'rootCauseHypothesis': {'type': 'string'},
            'editSuggestions': {
                'type': 'string',
                'description': 'Provide suggestions to fix the bug, if you know enough about the code that requires modification.',
            },
        },
        'required': ['rootCauseHypothesis'],
    },
)

replay_tools: list[ReplayTool] = [
    ReplayInspectDataTool,
    ReplayInspectPointTool,
    ReplaySubmitHypothesisTool,
]
replay_tool_names: set[str] = set([t.function['name'] for t in replay_tools])


def is_replay_tool(tool_name: str) -> bool:
    return tool_name in replay_tool_names


def handle_replay_tool_call(
    tool_call: ChatCompletionMessageToolCall, arguments: dict, state: State
) -> ReplayAction:
    logger.info(
        f'[REPLAY] TOOL_CALL {tool_call.function.name} - arguments: {json.dumps(arguments, indent=2)}'
    )
    action: ReplayAction
    if tool_call.function.name == 'inspect-data':
        # Remove explanation props.
        arguments = {k: v for k, v in arguments.items() if 'explanation' not in k}
        action = ReplayToolCmdRunAction(
            command_name='inspect-data',
            command_args=arguments | {'recordingId': state.replay_recording_id},
        )
    elif tool_call.function.name == 'inspect-point':
        # if arguments['expression'] == 'wiredRules':   # hackfix for 10608 experiment
        #     raise FunctionCallValidationError(f'wiredRules is irrelevant to the problem. Try something else.')
        action = ReplayToolCmdRunAction(
            command_name='inspect-point',
            command_args=arguments | {'recordingId': state.replay_recording_id},
        )
    elif tool_call.function.name == 'submit-hypothesis':
        action = ReplayPhaseUpdateAction(
            new_phase=ReplayPhase.Edit, info=json.dumps(arguments)
        )
    else:
        raise ValueError(
            f'Unknown Replay tool. Make sure to add them all to REPLAY_TOOLS: {tool_call.function.name}'
        )
    return action


def get_replay_tools(
    replay_phase: ReplayPhase, default_tools: list[ChatCompletionToolParam]
) -> list[ChatCompletionToolParam]:
    if replay_phase == ReplayPhase.Normal:
        # Use the default tools when not in a Replay-specific phase.
        return default_tools

    analysis_tools = [
        ReplayInspectDataTool,
        ReplayInspectPointTool,
    ]
    if replay_phase == ReplayPhase.Analysis:
        # Analysis tools only. This phase is concluded upon submit-hypothesis.
        tools = analysis_tools + [ReplaySubmitHypothesisTool]
    elif replay_phase == ReplayPhase.Edit:
        # Combine default and analysis tools.
        tools = default_tools + analysis_tools
    else:
        raise ValueError(f'Unhandled ReplayPhase in get_tools: {replay_phase}')
    return tools
