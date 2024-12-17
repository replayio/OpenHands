import json
import re
import tempfile
from typing import Any

from openhands.events.action.commands import CmdRunAction
from openhands.events.action.replay import ReplayCmdRunAction
from openhands.events.observation.error import ErrorObservation
from openhands.events.observation.replay import ReplayCmdOutputObservation
from openhands.runtime.utils.bash import BashSession

MARKER_START = 'MARKER-gJNVWbR2W1FRxa5zkvVZtXcrep2DFHjUUNjQJErE-START'
MARKER_END = 'MARKER-gJNVWbR2W1FRxa5zkvVZtXcrep2DFHjUUNjQJErE-END'


# NOTE: We use Markers to avoid noise corrupting the JSON output.
def get_marked_output_json_string(output: str) -> str:
    """This should return a JSON-parseable string."""
    parts = re.split(f'{MARKER_START}|{MARKER_END}', output)
    if len(parts) < 3:
        raise ValueError(f'replayapi output does not contain markers: {output}')
    # Return only what is between the markers.
    return parts[1]


class ReplayCli:
    def __init__(self, bash_session: BashSession):
        self.bash_session = bash_session

    async def run_action(
        self, action: ReplayCmdRunAction
    ) -> ReplayCmdOutputObservation | ErrorObservation:
        # Fix up inputs:
        command_args = action.command_args or dict()
        if action.recording_id != '':
            command_args['recordingId'] = action.recording_id
        if action.session_id != '':
            command_args['sessionId'] = action.session_id
        if action.command_name == 'initial-analysis':
            # Hardcode the path for now. We won't need it in the long run.
            command_args['workspacePath'] = self.bash_session.workdir

        # Create temp file for input
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as input_file:
            input: dict[str, Any] = dict()
            input['command'] = action.command_name
            input['args'] = command_args
            json.dump(action.command_args, input_file)
            input_path = input_file.name
        # Create temp file for output
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as output_file:
            output_path = output_file.name
        # Construct and execute command
        command = f'/replay/replayapi/scripts/main-tool.sh {input_path} {output_path}'

        if action.in_workspace_dir:
            # Execute command from workspace directory.
            command = f'pushd {self.bash_session.workdir} > /dev/null; {command}; popd > /dev/null'

        cmd_action = CmdRunAction(
            command=command,
            thought=action.thought,
            blocking=action.blocking,
            keep_prompt=action.keep_prompt,
            hidden=action.hidden,
            confirmation_state=action.confirmation_state,
            security_risk=action.security_risk,
        )
        cmd_action.timeout = 600
        obs = self.bash_session.run(cmd_action)

        if isinstance(obs, ErrorObservation):
            return obs

        output = get_marked_output_json_string(obs.content)

        # we might not actually need a separate observation type for replay...
        return ReplayCmdOutputObservation(
            command_id=obs.command_id,
            command=obs.command,
            exit_code=obs.exit_code,
            hidden=obs.hidden,
            interpreter_details=obs.interpreter_details,
            content=output,
        )
