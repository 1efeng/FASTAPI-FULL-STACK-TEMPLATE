class AppError(Exception):
    """Base application error raised by service/domain code.

    Service code should not depend on FastAPI/HTTP concerns. The API layer maps
    these errors to transport-specific responses.
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ResourceNotFoundError(AppError):
    """Requested application resource does not exist."""


class PermissionDeniedError(AppError):
    """Current actor is not allowed to perform the operation."""


class ConflictError(AppError):
    """Operation conflicts with the current application state."""


class InvalidRequestError(AppError):
    """Operation cannot be performed with the supplied application input."""
