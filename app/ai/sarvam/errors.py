class SarvamError(Exception):
    """Raised when a Sarvam API call fails after retries."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
