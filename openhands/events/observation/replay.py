from abc import ABC
from dataclasses import dataclass

from openhands.core.schema import ObservationType
from openhands.core.schema.replay import ReplayDebuggingPhase
from openhands.events.observation.observation import Observation


@dataclass
class ReplayObservation(Observation, ABC):
    pass


@dataclass
class ReplayCmdOutputObservationBase(ReplayObservation, ABC):
    """This data class represents the output of a replay command."""

    command_id: int
    command: str
    exit_code: int = 0
    hidden: bool = False
    interpreter_details: str = ''

    @property
    def error(self) -> bool:
        return self.exit_code != 0

    @property
    def message(self) -> str:
        return f'Command `{self.command}` executed with exit code {self.exit_code}.'

    def __str__(self) -> str:
        return f'**{self.__class__.__name__} (source={self.source}, exit code={self.exit_code})**\n{self.content}'


@dataclass
class ReplayInternalCmdOutputObservation(ReplayCmdOutputObservationBase):
    observation: str = ObservationType.RUN_REPLAY_INTERNAL


@dataclass
class ReplayToolCmdOutputObservation(ReplayCmdOutputObservationBase):
    observation: str = ObservationType.RUN_REPLAY_TOOL


@dataclass
class ReplayPhaseUpdateObservation(ReplayObservation):
    new_phase: ReplayDebuggingPhase
    observation: str = ObservationType.REPLAY_UPDATE_PHASE

    @property
    def message(self) -> str:
        return 'Tools were updated.'

    def __str__(self) -> str:
        return f'**{self.__class__.__name__} (source={self.source}): {self.content}**'
