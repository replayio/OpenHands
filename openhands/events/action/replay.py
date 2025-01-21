import json
from dataclasses import dataclass
from typing import Any, ClassVar

from openhands.core.schema import ActionType
from openhands.core.schema.replay import ReplayDebuggingPhase
from openhands.events.action.action import (
    Action,
    ActionConfirmationStatus,
    ActionSecurityRisk,
)


@dataclass
class ReplayAction(Action):
    pass


# NOTE: We need the same class twice because a lot of the agent logic is based on isinstance checks.
@dataclass
class ReplayCmdRunActionBase(ReplayAction):
    # Name of the command in @replayapi/cli.
    command_name: str

    # Args to be passed to the cli command.
    command_args: dict[str, Any] | None = None

    # The thought/prompt message that triggered this action.
    thought: str = ''

    blocking: bool = True
    keep_prompt: bool = False
    hidden: bool = False
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk | None = None

    # Whether to execute the command from the workspace directory, independent of CWD.
    in_workspace_dir: bool = False

    # Other Replay fields.
    recording_id: str = ''
    session_id: str = ''

    @property
    def message(self) -> str:
        return f'[REPLAY] {json.dumps({"command": self.command_name, "args": self.command_args})}'

    def __str__(self) -> str:
        ret = f'**{self.__class__.__name__} (source={self.source})**\n'
        if self.thought:
            ret += f'THOUGHT: {self.thought}\n'
        ret += f'{self.message}'
        return ret


# The pure "command run actions" are used internally and should be hidden from the agent.
@dataclass
class ReplayInternalCmdRunAction(ReplayCmdRunActionBase):
    action: str = ActionType.RUN_REPLAY_INTERNAL


# The tool actions should be visible to the agent.
@dataclass
class ReplayToolCmdRunAction(ReplayCmdRunActionBase):
    action: str = ActionType.RUN_REPLAY_TOOL


@dataclass
class ReplayPhaseUpdateAction(ReplayAction):
    new_phase: ReplayDebuggingPhase

    thought: str = ''
    info: str = ''

    action: str = ActionType.REPLAY_UPDATE_PHASE
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk | None = None

    @property
    def message(self) -> str:
        return f'{self.__class__.__name__}: {self.new_phase}'

    def __str__(self) -> str:
        ret = f'[{self.message}] {self.info}'
        return ret
