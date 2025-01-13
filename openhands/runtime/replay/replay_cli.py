import json
import os
import tempfile
from typing import Any

from openhands.events.action.commands import CmdRunAction
from openhands.events.action.replay import (
    ReplayCmdRunActionBase,
    ReplayToolCmdRunAction,
)
from openhands.events.observation.error import ErrorObservation
from openhands.events.observation.replay import (
    ReplayCmdOutputObservationBase,
    ReplayInternalCmdOutputObservation,
    ReplayToolCmdOutputObservation,
)
from openhands.runtime.utils.bash import BashSession


class ReplayCli:
    def __init__(self, bash_session: BashSession):
        self.bash_session = bash_session

    async def run_action(
        self, action: ReplayCmdRunActionBase
    ) -> ReplayCmdOutputObservationBase | ErrorObservation:
        # Fix up inputs:
        command_args = action.command_args or dict()
        if action.recording_id != '':
            command_args['recordingId'] = action.recording_id
        if action.session_id != '':
            command_args['sessionId'] = action.session_id
        if action.command_name == 'initial-analysis':
            # Hardcode the path for now. We won't need it in the long run.
            command_args['workspacePath'] = self.bash_session.workdir

        with (
            tempfile.NamedTemporaryFile(
                mode='w+', suffix='.json', delete=True
            ) as input_file,
            tempfile.NamedTemporaryFile(
                mode='w+', suffix='.json', delete=True
            ) as output_file,
        ):
            # Give permissions.
            os.chmod(input_file.name, 0o666)
            os.chmod(output_file.name, 0o666)

            # Prepare input.
            input: dict[str, Any] = dict()
            input['command'] = action.command_name
            input['args'] = command_args
            input_file.seek(0)
            json.dump(input, input_file)
            input_file.flush()
            input_path = input_file.name

            # Construct and execute command.
            output_path = output_file.name
            command = f'/replay/replayapi/main-tool.sh {input_path} {output_path}'

            if action.in_workspace_dir:
                # Work from the workspace directory.
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

            if obs.exit_code != 0:
                return ErrorObservation(
                    f'ReplayCli command "{obs.command}" failed with exit code {obs.exit_code} for input_path={input_path}: STDOUT={obs.content}'
                )

            try:
                output_file.seek(0)
                content = output_file.read()
                output: dict = json.loads(content)
            except json.JSONDecodeError:
                if content == '':
                    return ErrorObservation(
                        f'ReplayCli result is empty (command={obs.command}): STDOUT={obs.content}',
                    )
                return ErrorObservation(
                    f'Failed to parse JSON from ReplayCli result (command={obs.command}): STDOUT={obs.content}; FILE_CONTENTS={content}',
                )
            except Exception as e:
                return ErrorObservation(
                    f'Failed to read ReplayCli result: {str(e)}',
                )

            if output.get('status') != 'success':
                return ErrorObservation(
                    f'ReplayCli result was not a success: {output.get("error")}\n  errorDetails={output.get("errorDetails")}'
                )

            result = output.get('result')
            ObservationClass = (
                ReplayToolCmdOutputObservation
                if isinstance(action, ReplayToolCmdRunAction)
                else ReplayInternalCmdOutputObservation
            )
            return ObservationClass(
                command_id=obs.command_id,
                command=obs.command,
                exit_code=obs.exit_code,
                hidden=obs.hidden,
                interpreter_details=obs.interpreter_details,
                # We provide the analysis data as-is in a human-readable JSON format, to keep things concise.
                content=json.dumps(result),
            )
