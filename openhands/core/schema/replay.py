from enum import Enum


class ReplayPhase(str, Enum):
    """All Replay phases that an agent can be in."""

    Normal = 'normal'
    """The agent does not have access to a recording.
    """

    Analysis = 'analysis'
    """The agent uses initial-analysis data and dedicated tools to analyze a Replay recording.
    """
    ConfirmAnalysis = 'confirm_analysis'
    """The agent is confirming the analysis.
    """

    Edit = 'edit'
    """The agent finally edits the code.
    """
