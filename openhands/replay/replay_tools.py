"""Define tools to interact with Replay recordings and the Replay agentic workflow."""

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
from openhands.replay.replay_phases import get_replay_child_phase


class ReplayTool(ChatCompletionToolParam):
    pass


def replay_tool(name: str, description: str, parameters: dict) -> ReplayTool:
    f = ChatCompletionToolParamFunctionChunk(
        name=name, description=description, parameters=parameters
    )
    return ReplayTool(type='function', function=f)


# ###########################################################################
# Analysis.
# ###########################################################################


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
                'description': 'The point at which to inspect the recorded program.',
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


# ###########################################################################
# Phase transitions + submissions.
# ###########################################################################


class ReplaySubmitTool(ReplayTool):
    new_phase: ReplayPhase


def replay_submit_tool(
    new_phase: ReplayPhase, name: str, description: str, parameters: dict
):
    return ReplaySubmitTool(
        new_phase=new_phase,
        type='function',
        function=ChatCompletionToolParamFunctionChunk(
            name=name, description=description, parameters=parameters
        ),
    )


replay_phase_transition_tools: list[ReplaySubmitTool] = [
    replay_submit_tool(
        ReplayPhase.Edit,
        'submit',
        """Conclude your analysis.""",
        {
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
            'required': ['problem', 'rootCauseHypothesis'],
        },
    )
]

# ###########################################################################
# Bookkeeping + utilities.
# ###########################################################################

replay_analysis_tools: list[ReplayTool] = [
    ReplayInspectDataTool,
    ReplayInspectPointTool,
]

replay_tools: list[ReplayTool] = [
    *replay_analysis_tools,
    *replay_phase_transition_tools,
]
replay_tool_names: set[str] = set([t['function']['name'] for t in replay_tools])


def is_replay_tool(tool_name: str) -> bool:
    return tool_name in replay_tool_names


# ###########################################################################
# Compute tools based on the current ReplayPhase.
# ###########################################################################


def get_replay_tools(
    replay_phase: ReplayPhase, default_tools: list[ChatCompletionToolParam]
) -> list[ChatCompletionToolParam]:
    if replay_phase == ReplayPhase.Normal:
        # Use the default tools when not in a Replay-specific phase.
        tools = default_tools
    elif replay_phase == ReplayPhase.Analysis:
        # Only allow analysis in this phase.
        tools = replay_analysis_tools
    elif replay_phase == ReplayPhase.Edit:
        # Combine default and analysis tools.
        tools = default_tools + replay_analysis_tools
    else:
        raise ValueError(f'Unhandled ReplayPhase in get_tools: {replay_phase}')

    # Add phase transition tools.
    next_phase = get_replay_child_phase(replay_phase)
    if next_phase:
        tools += [t for t in replay_phase_transition_tools if t.new_phase == next_phase]

    # Return all tools.
    return tools


# ###########################################################################
# Tool call handling.
# ###########################################################################


def handle_replay_tool_call(
    tool_call: ChatCompletionMessageToolCall, arguments: dict, state: State
) -> ReplayAction:
    logger.info(
        f'[REPLAY] TOOL_CALL {tool_call.function.name} - arguments: {json.dumps(arguments, indent=2)}'
    )
    action: ReplayAction
    if tool_call.function.name == 'inspect-data':
        # Remove explanation arguments. Those are only used for self-consistency.
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
    elif isinstance(tool_call, ReplaySubmitTool):
        # Request a phase change.
        action = ReplayPhaseUpdateAction(
            new_phase=tool_call.new_phase, info=json.dumps(arguments)
        )
    else:
        raise ValueError(
            f'Unknown Replay tool. Make sure to add them all to REPLAY_TOOLS: {tool_call.function.name}'
        )
    return action
