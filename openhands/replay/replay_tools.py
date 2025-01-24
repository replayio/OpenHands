"""Define tools to interact with Replay recordings and the Replay agentic workflow."""

import json
from enum import Enum

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
from openhands.replay.replay_phases import get_next_agent_replay_phase


class ReplayToolType(Enum):
    Analysis = 'analysis'
    PhaseTransition = 'phase_transition'


class ReplayTool(ChatCompletionToolParam):
    replay_tool_type: ReplayToolType


class ReplayAnalysisTool(ReplayTool):
    replay_tool_type = ReplayToolType.Analysis


def replay_analysis_tool(name: str, description: str, parameters: dict) -> ReplayTool:
    tool = ReplayAnalysisTool(
        replay_tool_type=ReplayToolType.Analysis,
        type='function',
        function=ChatCompletionToolParamFunctionChunk(
            name=name, description=description, parameters=parameters
        ),
    )
    return tool


class ReplayPhaseTransitionTool(ReplayTool):
    replay_tool_type = ReplayToolType.PhaseTransition
    new_phase: ReplayPhase


def replay_phase_tool(
    new_phase: ReplayPhase, name: str, description: str, parameters: dict
):
    tool = ReplayPhaseTransitionTool(
        replay_tool_type=ReplayToolType.PhaseTransition,
        new_phase=new_phase,
        type='function',
        function=ChatCompletionToolParamFunctionChunk(
            name=name,
            description=description,
            parameters=parameters,
        ),
    )
    return tool


# ###########################################################################
# Analysis.
# ###########################################################################


_REPLAY_INSPECT_DATA_DESCRIPTION = """
Explains value, data flow and origin information for `expression` at `point`.
IMPORTANT: Prefer using inspect-data over inspect-point.
"""

ReplayInspectDataTool = replay_analysis_tool(
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

ReplayInspectPointTool = replay_analysis_tool(
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


replay_phase_transition_tools: list[ReplayPhaseTransitionTool] = [
    replay_phase_tool(
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
replay_replay_tool_type_by_name = {
    t['function']['name']: t.get('replay_tool_type', None) for t in replay_tools
}


def is_replay_tool(
    tool_name: str, replay_tool_type: ReplayToolType | None = None
) -> bool:
    own_tool_type = replay_replay_tool_type_by_name.get(tool_name, None)
    if not own_tool_type:
        return False
    return replay_tool_type is None or own_tool_type == replay_tool_type


# ###########################################################################
# Compute tools based on the current ReplayPhase.
# ###########################################################################


def get_replay_transition_tool_for_current_phase(
    current_phase: ReplayPhase, name: str | None = None
) -> ReplayTool | None:
    next_phase = get_next_agent_replay_phase(current_phase)
    if next_phase:
        transition_tools = [
            t
            for t in replay_phase_transition_tools
            if t['new_phase'] == next_phase
            and (not name or t['function']['name'] == name)
        ]
        assert len(
            transition_tools
        ), f'replay_phase_transition_tools is missing tools for new_phase: {next_phase}'
        return transition_tools[0]
    return None


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

    # Add tools to allow transitioning to next phase.
    next_phase_tool = get_replay_transition_tool_for_current_phase(replay_phase)
    if next_phase_tool:
        tools.append(next_phase_tool)

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
    name = tool_call.function.name
    if is_replay_tool(name, ReplayToolType.Analysis):
        if name == 'inspect-data':
            # Remove explanation arguments. Those are only used for self-consistency.
            arguments = {k: v for k, v in arguments.items() if 'explanation' not in k}
            action = ReplayToolCmdRunAction(
                command_name='inspect-data',
                command_args=arguments | {'recordingId': state.replay_recording_id},
            )
        elif name == 'inspect-point':
            # if arguments['expression'] == 'wiredRules':   # hackfix for 10608 experiment
            #     raise FunctionCallValidationError(f'wiredRules is irrelevant to the problem. Try something else.')
            action = ReplayToolCmdRunAction(
                command_name='inspect-point',
                command_args=arguments | {'recordingId': state.replay_recording_id},
            )
    elif is_replay_tool(name, ReplayToolType.PhaseTransition):
        # Request a phase change.
        tool = get_replay_transition_tool_for_current_phase(state.replay_phase, name)
        assert tool, f'[REPLAY] Missing ReplayPhaseTransitionTool for {state.replay_phase} in Replay tool_call: {tool_call.function.name}'
        new_phase = tool['new_phase']
        assert (
            new_phase
        ), f'[REPLAY] Missing new_phase in Replay tool_call: {tool_call.function.name}'
        action = ReplayPhaseUpdateAction(
            new_phase=new_phase, info=json.dumps(arguments)
        )
    assert action, f'[REPLAY] Unhandled Replay tool_call: {tool_call.function.name}'
    return action
