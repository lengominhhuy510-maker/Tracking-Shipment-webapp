class ExternalIntegrationError(Exception):
    """Provider call failed at the transport/parsing boundary (Decision 0005)."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable
