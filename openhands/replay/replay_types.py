from typing import TypedDict


class AnnotatedLocation(TypedDict, total=False):
    filePath: str
    line: int


class AnalysisToolMetadata(TypedDict, total=False):
    recordingId: str


class AnnotateResult(TypedDict, total=False):
    point: str
    commentText: str | None
    annotatedRepo: str | None
    annotatedLocations: list[AnnotatedLocation] | None
    pointLocation: str | None
    metadata: AnalysisToolMetadata | None
