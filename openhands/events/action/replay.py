import json
from dataclasses import dataclass
from typing import Any, ClassVar

from openhands.core.schema import ActionType
from openhands.events.action.action import (
    Action,
    ActionConfirmationStatus,
    ActionSecurityRisk,
)


@dataclass
class ReplayCmdRunAction(Action):
    # Name of the command in @replayapi/cli.
    command_name: str

    # Args to be passed to the cli command.
    command_args: dict[str, Any] | None = None

    # The thought/prompt message that triggered this action.
    thought: str = ''

    blocking: bool = True
    keep_prompt: bool = False
    hidden: bool = False
    action: str = ActionType.RUN_REPLAY
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk | None = None

    # Whether to execute the command from the workspace directory, independent of CWD.
    in_workspace_dir: bool = True

    # Other Replay fields.
    recording_id: str = ''
    session_id: str = ''

    @property
    def message(self) -> str:
        return f'ReplayCommand: {self.command_name} {json.dumps(self.command_args)}'

    def __str__(self) -> str:
        ret = f'**ReplayCmdRunAction (source={self.source})**\n'
        if self.thought:
            ret += f'THOUGHT: {self.thought}\n'
        ret += f'{self.message}'
        return ret
