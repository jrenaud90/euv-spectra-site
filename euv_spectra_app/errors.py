class PegasusError(Exception):
    """Base application error that separates user and operator messaging."""

    def __init__(self, user_message, *, log_message=None, recoverable=False):
        super().__init__(log_message or user_message)
        self.user_message = user_message
        self.log_message = log_message or user_message
        self.recoverable = recoverable


class CatalogLookupError(PegasusError):
    """External catalog lookup failed or returned unusable data."""


class DataProcessingError(PegasusError):
    """Application could not transform or validate lookup data."""


class ModelSelectionError(PegasusError):
    """PEGASUS model selection or database access failed."""