"""Custom exception hierarchy for rekordbot."""


class RekordBotError(Exception):
    """Base exception for all rekordbot errors.

    Attributes:
        error: Machine-readable error code.
        detail: Human-readable explanation.
        status_code: HTTP status code for the error response.
    """

    def __init__(self, error: str, detail: str, status_code: int = 500) -> None:
        self.error = error
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ConversionError(RekordBotError):
    """Raised when audio file conversion fails."""

    def __init__(self, detail: str) -> None:
        super().__init__(error="conversion_failed", detail=detail, status_code=500)


class DuplicateTrackError(RekordBotError):
    """Raised when a duplicate track is detected."""

    def __init__(self, detail: str) -> None:
        super().__init__(error="duplicate_detected", detail=detail, status_code=409)


class TagReadError(RekordBotError):
    """Raised when reading metadata tags fails."""

    def __init__(self, detail: str) -> None:
        super().__init__(error="tag_read_failed", detail=detail, status_code=500)


class TagWriteError(RekordBotError):
    """Raised when writing metadata tags fails."""

    def __init__(self, detail: str) -> None:
        super().__init__(error="tag_write_failed", detail=detail, status_code=500)


class AnalysisError(RekordBotError):
    """Raised when audio analysis (BPM/key detection) fails."""

    def __init__(self, detail: str) -> None:
        super().__init__(error="analysis_failed", detail=detail, status_code=500)


class AiTagError(RekordBotError):
    """Raised when AI tagging (Claude API) fails."""

    def __init__(self, detail: str, status_code: int = 500) -> None:
        super().__init__(error="ai_tag_failed", detail=detail, status_code=status_code)


class OrganisationError(RekordBotError):
    """Raised when file organisation fails."""

    def __init__(self, detail: str, status_code: int = 500) -> None:
        super().__init__(error="organisation_failed", detail=detail, status_code=status_code)


class ExportError(RekordBotError):
    """Raised when Rekordbox XML export fails."""

    def __init__(self, detail: str, status_code: int = 500) -> None:
        super().__init__(error="export_failed", detail=detail, status_code=status_code)
