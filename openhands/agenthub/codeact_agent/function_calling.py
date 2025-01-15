"""This file contains the function calling implementation for different actions.

This is similar to the functionality of `CodeActResponseParser`.
"""

import json

from browsergym.core.action.highlevel import HighLevelActionSet
from litellm import (
    ChatCompletionToolParam,
    ChatCompletionToolParamFunctionChunk,
    ModelResponse,
)

from openhands.controller.state.state import State
from openhands.core.exceptions import FunctionCallNotExistsError
from openhands.core.logger import openhands_logger as logger
from openhands.core.schema import ReplayDebuggingPhase
from openhands.events.action import (
    Action,
    AgentDelegateAction,
    AgentFinishAction,
    BrowseInteractiveAction,
    CmdRunAction,
    FileEditAction,
    IPythonRunCellAction,
    MessageAction,
)
from openhands.events.action.replay import (
    ReplayPhaseUpdateAction,
    ReplayToolCmdRunAction,
)
from openhands.events.tool import ToolCallMetadata

# ---------------------------------------------------------
# Tool: inspect-data
# ---------------------------------------------------------
_REPLAY_INSPECT_DATA_DESCRIPTION = """
Explains value, data flow and origin information for `expression` at `point`.
IMPORTANT: Prefer using inspect-data over inspect-point.
"""

ReplayInspectDataTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
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
    ),
)

# ---------------------------------------------------------
# Tool: inspect-point
# ---------------------------------------------------------
_REPLAY_INSPECT_POINT_DESCRIPTION = """
Explains dynamic control flow and data flow dependencies of the code at `point`.
Use this tool instead of `inspect-data` only when you don't have a specific data point to investigate.
"""

ReplayInspectPointTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='inspect-point',
        description=_REPLAY_INSPECT_POINT_DESCRIPTION.strip(),
        parameters={
            'type': 'object',
            'properties': {
                'point': {'type': 'string'},
            },
            'required': ['point'],
        },
    ),
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

# ReplaySubmitHypothesisTool = ChatCompletionToolParam(
#     type='function',
#     function=ChatCompletionToolParamFunctionChunk(
#         name='submit-hypothesis',
#         description=_REPLAY_SUBMIT_HYPOTHESIS_DESCRIPTION.strip(),
#         parameters={
#             'type': 'object',
#             'properties': {
#                 'rootCauseHypothesis': {'type': 'string'},
#                 'thinSlice': {
#                     'type': 'array',
#                     'items': {
#                         'type': 'object',
#                         'properties': {
#                             'point': {'type': 'string'},
#                             'code': {'type': 'string'},
#                             'role': {'type': 'string'},
#                         },
#                         'required': ['point', 'code', 'role'],
#                     },
#                 },
#                 'modifications': {
#                     'type': 'array',
#                     'items': {
#                         'type': 'object',
#                         'properties': {
#                             'kind': {
#                                 'type': 'string',
#                                 'enum': ['add', 'remove', 'modify'],
#                             },
#                             'newCode': {'type': 'string'},
#                             'oldCode': {'type': 'string'},
#                             'location': {'type': 'string'},
#                             'point': {'type': 'string'},
#                             # NOTE: Even though, we really want the `line` here, it will lead to much worse performance because the agent has a hard time computing correct line numbers from its point-based investigation.
#                             # Instead of requiring a line number, the final fix will be more involved, as explained in the issue.
#                             # see: https://linear.app/replay/issue/PRO-939/use-tools-data-flow-analysis-for-10608#comment-3b7ae176
#                             # 'line': {'type': 'number'},
#                             'briefExplanation': {'type': 'string'},
#                             'verificationProof': {'type': 'string'},
#                         },
#                         'required': [
#                             'kind',
#                             'location',
#                             'briefExplanation',
#                             # 'line',
#                             'verificationProof',
#                         ],
#                     },
#                 },
#             },
#             'required': ['rootCauseHypothesis', 'thinSlice', 'modifications'],
#         },
#     ),
# )
_REPLAY_SUBMIT_HYPOTHESIS_DESCRIPTION = """
# Use this tool once your investigation has yielded a complete thin slice from symptom to root cause,
# with enough proof to let a simple code editing agent fix it.
# """

ReplaySubmitHypothesisTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='submit-hypothesis',
        description=_REPLAY_SUBMIT_HYPOTHESIS_DESCRIPTION.strip(),
        parameters={
            'type': 'object',
            'properties': {
                'rootCauseHypothesis': {'type': 'string'},
                'editSuggestions': {'type': 'string'},
            },
            'required': ['rootCauseHypothesis', 'editSuggestions'],
        },
    ),
)

REPLAY_TOOLS = ['inspect-data', 'inspect-point', 'submit-hypothesis']


# ---------------------------------------------------------
# OH default tools.
# ---------------------------------------------------------
_BASH_DESCRIPTION = """Execute a bash command in the terminal.
* Long running commands: For commands that may run indefinitely, it should be run in the background and the output should be redirected to a file, e.g. command = `python3 app.py > server.log 2>&1 &`.
* Interactive: If a bash command returns exit code `-1`, this means the process is not yet finished. The assistant must then send a second call to terminal with an empty `command` (which will retrieve any additional logs), or it can send additional text (set `command` to the text) to STDIN of the running process, or it can send command=`ctrl+c` to interrupt the process.
* Timeout: If a command execution result says "Command timed out. Sending SIGINT to the process", the assistant should retry running the command in the background.
"""

CmdRunTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='execute_bash',
        description=_BASH_DESCRIPTION,
        parameters={
            'type': 'object',
            'properties': {
                'command': {
                    'type': 'string',
                    'description': 'The bash command to execute. Can be empty to view additional logs when previous exit code is `-1`. Can be `ctrl+c` to interrupt the currently running process.',
                },
            },
            'required': ['command'],
        },
    ),
)

_IPYTHON_DESCRIPTION = """Run a cell of Python code in an IPython environment.
* The assistant should define variables and import packages before using them.
* The variable defined in the IPython environment will not be available outside the IPython environment (e.g., in terminal).
"""

IPythonTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='execute_ipython_cell',
        description=_IPYTHON_DESCRIPTION,
        parameters={
            'type': 'object',
            'properties': {
                'code': {
                    'type': 'string',
                    'description': 'The Python code to execute. Supports magic commands like %pip.',
                },
            },
            'required': ['code'],
        },
    ),
)

_FILE_EDIT_DESCRIPTION = """Edit a file.
* The assistant can edit files by specifying the file path and providing a draft of the new file content.
* The draft content doesn't need to be exactly the same as the existing file; the assistant may skip unchanged lines using comments like `# unchanged` to indicate unchanged sections.
* IMPORTANT: For large files (e.g., > 300 lines), specify the range of lines to edit using `start` and `end` (1-indexed, inclusive). The range should be smaller than 300 lines.
* To append to a file, set both `start` and `end` to `-1`.
* If the file doesn't exist, a new file will be created with the provided content.

**Example 1: general edit for short files**
For example, given an existing file `/path/to/file.py` that looks like this:
(this is the end of the file)
1|class MyClass:
2|    def __init__(self):
3|        self.x = 1
4|        self.y = 2
5|        self.z = 3
6|
7|print(MyClass().z)
8|print(MyClass().x)
(this is the end of the file)

The assistant wants to edit the file to look like this:
(this is the end of the file)
1|class MyClass:
2|    def __init__(self):
3|        self.x = 1
4|        self.y = 2
5|
6|print(MyClass().y)
(this is the end of the file)

The assistant may produce an edit action like this:
path="/path/to/file.txt" start=1 end=-1
content=```
class MyClass:
    def __init__(self):
        # no changes before
        self.y = 2
        # self.z is removed

# MyClass().z is removed
print(MyClass().y)
```

**Example 2: append to file for short files**
For example, given an existing file `/path/to/file.py` that looks like this:
(this is the end of the file)
1|class MyClass:
2|    def __init__(self):
3|        self.x = 1
4|        self.y = 2
5|        self.z = 3
6|
7|print(MyClass().z)
8|print(MyClass().x)
(this is the end of the file)

To append the following lines to the file:
```python
print(MyClass().y)
```

The assistant may produce an edit action like this:
path="/path/to/file.txt" start=-1 end=-1
content=```
print(MyClass().y)
```

**Example 3: edit for long files**

Given an existing file `/path/to/file.py` that looks like this:
(1000 more lines above)
1001|class MyClass:
1002|    def __init__(self):
1003|        self.x = 1
1004|        self.y = 2
1005|        self.z = 3
1006|
1007|print(MyClass().z)
1008|print(MyClass().x)
(2000 more lines below)

The assistant wants to edit the file to look like this:

(1000 more lines above)
1001|class MyClass:
1002|    def __init__(self):
1003|        self.x = 1
1004|        self.y = 2
1005|
1006|print(MyClass().y)
(2000 more lines below)

The assistant may produce an edit action like this:
path="/path/to/file.txt" start=1001 end=1008
content=```
class MyClass:
    def __init__(self):
        # no changes before
        self.y = 2
        # self.z is removed

# MyClass().z is removed
print(MyClass().y)
```
"""

LLMBasedFileEditTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='edit_file',
        description=_FILE_EDIT_DESCRIPTION,
        parameters={
            'type': 'object',
            'properties': {
                'path': {
                    'type': 'string',
                    'description': 'The absolute path to the file to be edited.',
                },
                'new_content_draft': {
                    'type': 'string',
                    'description': 'A draft of the new content for the file being edited. Note that the assistant may skip unchanged lines.',
                },
                'start': {
                    'type': 'integer',
                    'description': 'The starting line number for the edit (1-indexed, inclusive). Default is 1.',
                },
                'end': {
                    'type': 'integer',
                    'description': 'The ending line number for the edit (1-indexed, inclusive). Default is -1 (end of file).',
                },
            },
            'required': ['path', 'content'],
        },
    ),
)

_STR_REPLACE_EDITOR_DESCRIPTION = """Custom editing tool for viewing, creating and editing files
* State is persistent across command calls and discussions with the user
* If `path` is a file, `view` displays the result of applying `cat -n`. If `path` is a directory, `view` lists non-hidden files and directories up to 2 levels deep
* The `create` command cannot be used if the specified `path` already exists as a file
* If a `command` generates a long output, it will be truncated and marked with `<response clipped>`
* The `undo_edit` command will revert the last edit made to the file at `path`

Notes for using the `str_replace` command:
* The `old_str` parameter should match EXACTLY one or more consecutive lines from the original file. Be mindful of whitespaces!
* If the `old_str` parameter is not unique in the file, the replacement will not be performed. Make sure to include enough context in `old_str` to make it unique
* The `new_str` parameter should contain the edited lines that should replace the `old_str`
"""

StrReplaceEditorTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='str_replace_editor',
        description=_STR_REPLACE_EDITOR_DESCRIPTION,
        parameters={
            'type': 'object',
            'properties': {
                'command': {
                    'description': 'The commands to run. Allowed options are: `view`, `create`, `str_replace`, `insert`, `undo_edit`.',
                    'enum': ['view', 'create', 'str_replace', 'insert', 'undo_edit'],
                    'type': 'string',
                },
                'path': {
                    'description': 'Absolute path to file or directory, e.g. `/workspace/file.py` or `/workspace`.',
                    'type': 'string',
                },
                'file_text': {
                    'description': 'Required parameter of `create` command, with the content of the file to be created.',
                    'type': 'string',
                },
                'old_str': {
                    'description': 'Required parameter of `str_replace` command containing the string in `path` to replace.',
                    'type': 'string',
                },
                'new_str': {
                    'description': 'Optional parameter of `str_replace` command containing the new string (if not given, no string will be added). Required parameter of `insert` command containing the string to insert.',
                    'type': 'string',
                },
                'insert_line': {
                    'description': 'Required parameter of `insert` command. The `new_str` will be inserted AFTER the line `insert_line` of `path`.',
                    'type': 'integer',
                },
                'view_range': {
                    'description': 'Optional parameter of `view` command when `path` points to a file. If none is given, the full file is shown. If provided, the file will be shown in the indicated line number range, e.g. [11, 12] will show lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]` shows all lines from `start_line` to the end of the file.',
                    'items': {'type': 'integer'},
                    'type': 'array',
                },
            },
            'required': ['command', 'path'],
        },
    ),
)

# from browsergym/core/action/highlevel.py
_browser_action_space = HighLevelActionSet(
    subsets=['bid', 'nav'],
    strict=False,  # less strict on the parsing of the actions
    multiaction=True,  # enable to agent to take multiple actions at once
)


_BROWSER_DESCRIPTION = """Interact with the browser using Python code.

See the description of "code" parameter for more details.

Multiple actions can be provided at once, but will be executed sequentially without any feedback from the page.
More than 2-3 actions usually leads to failure or unexpected behavior. Example:
fill('a12', 'example with "quotes"')
click('a51')
click('48', button='middle', modifiers=['Shift'])
"""

_BROWSER_TOOL_DESCRIPTION = """
The following 15 functions are available. Nothing else is supported.

goto(url: str)
    Description: Navigate to a url.
    Examples:
        goto('http://www.example.com')

go_back()
    Description: Navigate to the previous page in history.
    Examples:
        go_back()

go_forward()
    Description: Navigate to the next page in history.
    Examples:
        go_forward()

noop(wait_ms: float = 1000)
    Description: Do nothing, and optionally wait for the given time (in milliseconds).
    You can use this to get the current page content and/or wait for the page to load.
    Examples:
        noop()

        noop(500)

scroll(delta_x: float, delta_y: float)
    Description: Scroll horizontally and vertically. Amounts in pixels, positive for right or down scrolling, negative for left or up scrolling. Dispatches a wheel event.
    Examples:
        scroll(0, 200)

        scroll(-50.2, -100.5)

fill(bid: str, value: str)
    Description: Fill out a form field. It focuses the element and triggers an input event with the entered text. It works for <input>, <textarea> and [contenteditable] elements.
    Examples:
        fill('237', 'example value')

        fill('45', 'multi-line\nexample')

        fill('a12', 'example with "quotes"')

select_option(bid: str, options: str | list[str])
    Description: Select one or multiple options in a <select> element. You can specify option value or label to select. Multiple options can be selected.
    Examples:
        select_option('a48', 'blue')

        select_option('c48', ['red', 'green', 'blue'])

click(bid: str, button: Literal['left', 'middle', 'right'] = 'left', modifiers: list[typing.Literal['Alt', 'Control', 'ControlOrMeta', 'Meta', 'Shift']] = [])
    Description: Click an element.
    Examples:
        click('a51')

        click('b22', button='right')

        click('48', button='middle', modifiers=['Shift'])

dblclick(bid: str, button: Literal['left', 'middle', 'right'] = 'left', modifiers: list[typing.Literal['Alt', 'Control', 'ControlOrMeta', 'Meta', 'Shift']] = [])
    Description: Double click an element.
    Examples:
        dblclick('12')

        dblclick('ca42', button='right')

        dblclick('178', button='middle', modifiers=['Shift'])

hover(bid: str)
    Description: Hover over an element.
    Examples:
        hover('b8')

press(bid: str, key_comb: str)
    Description: Focus the matching element and press a combination of keys. It accepts the logical key names that are emitted in the keyboardEvent.key property of the keyboard events: Backquote, Minus, Equal, Backslash, Backspace, Tab, Delete, Escape, ArrowDown, End, Enter, Home, Insert, PageDown, PageUp, ArrowRight, ArrowUp, F1 - F12, Digit0 - Digit9, KeyA - KeyZ, etc. You can alternatively specify a single character you'd like to produce such as "a" or "#". Following modification shortcuts are also supported: Shift, Control, Alt, Meta, ShiftLeft, ControlOrMeta. ControlOrMeta resolves to Control on Windows and Linux and to Meta on macOS.
    Examples:
        press('88', 'Backspace')

        press('a26', 'ControlOrMeta+a')

        press('a61', 'Meta+Shift+t')

focus(bid: str)
    Description: Focus the matching element.
    Examples:
        focus('b455')

clear(bid: str)
    Description: Clear the input field.
    Examples:
        clear('996')

drag_and_drop(from_bid: str, to_bid: str)
    Description: Perform a drag & drop. Hover the element that will be dragged. Press left mouse button. Move mouse to the element that will receive the drop. Release left mouse button.
    Examples:
        drag_and_drop('56', '498')

upload_file(bid: str, file: str | list[str])
    Description: Click an element and wait for a "filechooser" event, then select one or multiple input files for upload. Relative file paths are resolved relative to the current working directory. An empty list clears the selected files.
    Examples:
        upload_file('572', '/home/user/my_receipt.pdf')

        upload_file('63', ['/home/bob/Documents/image.jpg', '/home/bob/Documents/file.zip'])
"""


for _, action in _browser_action_space.action_set.items():
    assert (
        action.signature in _BROWSER_TOOL_DESCRIPTION
    ), f'Browser description mismatch. Please double check if the BrowserGym updated their action space.\n\nAction: {action.signature}'
    assert (
        action.description in _BROWSER_TOOL_DESCRIPTION
    ), f'Browser description mismatch. Please double check if the BrowserGym updated their action space.\n\nAction: {action.description}'

BrowserTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='browser',
        description=_BROWSER_DESCRIPTION,
        parameters={
            'type': 'object',
            'properties': {
                'code': {
                    'type': 'string',
                    'description': (
                        'The Python code that interacts with the browser.\n'
                        + _BROWSER_TOOL_DESCRIPTION
                    ),
                }
            },
            'required': ['code'],
        },
    ),
)

_FINISH_DESCRIPTION = """Finish the interaction when the task is complete OR if the assistant cannot proceed further with the task."""

FinishTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='finish',
        description=_FINISH_DESCRIPTION,
    ),
)


def combine_thought(action: Action, thought: str) -> Action:
    if not hasattr(action, 'thought'):
        return action
    if thought:
        action.thought = thought
    return action


def response_to_actions(response: ModelResponse, state: State) -> list[Action]:
    actions: list[Action] = []
    assert len(response.choices) == 1, 'Only one choice is supported for now'
    assistant_msg = response.choices[0].message
    if assistant_msg.tool_calls:
        # Check if there's assistant_msg.content. If so, add it to the thought
        thought = ''
        if isinstance(assistant_msg.content, str):
            thought = assistant_msg.content
        elif isinstance(assistant_msg.content, list):
            for msg in assistant_msg.content:
                if msg['type'] == 'text':
                    thought += msg['text']

        # Process each tool call to OpenHands action
        for i, tool_call in enumerate(assistant_msg.tool_calls):
            action: Action
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.decoder.JSONDecodeError as e:
                raise RuntimeError(
                    f'Failed to parse tool call arguments: {tool_call.function.arguments}'
                ) from e
            if tool_call.function.name == 'execute_bash':
                action = CmdRunAction(**arguments)
            elif tool_call.function.name in REPLAY_TOOLS:
                logger.info(
                    f'[REPLAY] TOOL_CALL {tool_call.function.name} - arguments: {json.dumps(arguments, indent=2)}'
                )
                if tool_call.function.name == 'inspect-data':
                    # Remove explanation props.
                    arguments = {
                        k: v for k, v in arguments.items() if 'explanation' not in k
                    }
                    action = ReplayToolCmdRunAction(
                        command_name='inspect-data',
                        command_args=arguments
                        | {'recordingId': state.replay_recording_id},
                    )
                elif tool_call.function.name == 'inspect-point':
                    # if arguments['expression'] == 'wiredRules':   # hackfix for 10608 experiment
                    #     raise FunctionCallValidationError(f'wiredRules is irrelevant to the problem. Try something else.')
                    action = ReplayToolCmdRunAction(
                        command_name='inspect-point',
                        command_args=arguments
                        | {'recordingId': state.replay_recording_id},
                    )
                elif tool_call.function.name == 'submit-hypothesis':
                    action = ReplayPhaseUpdateAction(
                        new_phase=ReplayDebuggingPhase.Edit
                    )
                else:
                    raise ValueError(
                        f'Unknown Replay tool. Make sure to add them all to REPLAY_TOOLS: {tool_call.function.name}'
                    )
            elif tool_call.function.name == 'execute_ipython_cell':
                action = IPythonRunCellAction(**arguments)
            elif tool_call.function.name == 'delegate_to_browsing_agent':
                action = AgentDelegateAction(
                    agent='BrowsingAgent',
                    inputs=arguments,
                )
            elif tool_call.function.name == 'finish':
                action = AgentFinishAction()
            elif tool_call.function.name == 'edit_file':
                action = FileEditAction(**arguments)
            elif tool_call.function.name == 'str_replace_editor':
                # We implement this in agent_skills, which can be used via Jupyter
                # convert tool_call.function.arguments to kwargs that can be passed to file_editor
                code = f'print(file_editor(**{arguments}))'
                logger.debug(
                    f'TOOL CALL: str_replace_editor -> file_editor with code: {code}'
                )
                action = IPythonRunCellAction(code=code, include_extra=False)
            elif tool_call.function.name == 'browser':
                action = BrowseInteractiveAction(browser_actions=arguments['code'])
            else:
                raise FunctionCallNotExistsError(
                    f'Tool {tool_call.function.name} is not registered. (arguments: {arguments}). Please check the tool name and retry with an existing tool.'
                )

            # We only add thought to the first action
            if i == 0:
                action = combine_thought(action, thought)
            # Add metadata for tool calling
            action.tool_call_metadata = ToolCallMetadata(
                tool_call_id=tool_call.id,
                function_name=tool_call.function.name,
                model_response=response,
                total_calls_in_response=len(assistant_msg.tool_calls),
            )
            actions.append(action)
    else:
        actions.append(
            MessageAction(content=assistant_msg.content, wait_for_response=True)
        )

    assert len(actions) >= 1
    return actions


def get_default_tools(
    codeact_enable_browsing: bool = False,
    codeact_enable_llm_editor: bool = False,
    codeact_enable_jupyter: bool = False,
) -> list[ChatCompletionToolParam]:
    tools = [CmdRunTool, FinishTool]
    if codeact_enable_browsing:
        tools.append(BrowserTool)
    if codeact_enable_jupyter:
        tools.append(IPythonTool)
    if codeact_enable_llm_editor:
        tools.append(LLMBasedFileEditTool)
    return tools


def get_tools(
    codeact_enable_browsing: bool = False,
    codeact_enable_llm_editor: bool = False,
    codeact_enable_jupyter: bool = False,
    codeact_enable_replay: bool = False,
    codeact_replay_phase: ReplayDebuggingPhase = ReplayDebuggingPhase.Normal,
) -> list[ChatCompletionToolParam]:
    default_tools = get_default_tools(
        codeact_enable_browsing,
        codeact_enable_llm_editor,
        codeact_enable_jupyter,
    )
    if not codeact_enable_replay or codeact_replay_phase == ReplayDebuggingPhase.Normal:
        # Use the default tools when not in a Replay-specific phase.
        return default_tools

    if codeact_enable_replay:
        analysis_tools = [
            ReplayInspectDataTool,
            ReplayInspectPointTool,
            ReplaySubmitHypothesisTool,
        ]
        if codeact_replay_phase == ReplayDebuggingPhase.Analysis:
            # Analysis tools only. This phase is concluded upon submit-hypothesis.
            tools = analysis_tools
        elif codeact_replay_phase == ReplayDebuggingPhase.Edit:
            # Combine default and analysis tools.
            tools = default_tools + analysis_tools
        else:
            raise ValueError(
                f'Unhandled ReplayDebuggingPhase in get_tools: {codeact_replay_phase}'
            )

    return tools
