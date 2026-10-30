class ServiceError(Exception):
    """Base for expected, user-facing failures. `code` is stable; the API maps it to an HTTP status."""
    code = "error"
    status = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    code, status = "not_found", 404


class Invalid(ServiceError):
    code, status = "invalid", 422


class ConsentRequired(ServiceError):
    code, status = "consent_required", 403


class NotApplicable(ServiceError):
    code, status = "not_applicable", 409


class Unreadable(ServiceError):
    code, status = "unreadable", 422
