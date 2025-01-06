from dataclasses import dataclass

from openhands.core.schema import ObservationType
from openhands.events.observation.observation import Observation


@dataclass
class ReplayCmdOutputObservationBase(Observation):
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
