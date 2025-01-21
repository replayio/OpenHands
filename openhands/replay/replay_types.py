from typing import TypedDict


class AnnotatedLocation(TypedDict, total=False):
    filePath: str
    line: int


class AnalysisToolMetadata(TypedDict, total=False):
    recordingId: str
