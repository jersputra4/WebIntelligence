"""Application error types mapped to safe, client-facing JSON responses."""
from __future__ import annotations


class AppError(Exception):
    """An error whose code/message are safe to show to the client."""

    status_code = 500
    code = "INTERNAL_ERROR"
    message = "Unexpected server error"

    def __init__(self, message: str | None = None, *, code: str | None = None,
                 status_code: int | None = None, retry_after: int | None = None):
        super().__init__(message or self.message)
        if message:
            self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.retry_after = retry_after

    def to_dict(self) -> dict:
        return {"success": False, "error": {"code": self.code, "message": self.message}}


class ValidationFailed(AppError):
    status_code = 400
    code = "INVALID_USERNAME"
    message = "Username is invalid"


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests. Please wait before searching again."


class ProviderError(AppError):
    status_code = 502
    code = "PROVIDER_ERROR"
    message = "External data provider error"


class ProviderUnauthorized(ProviderError):
    code = "PROVIDER_UNAUTHORIZED"
    message = "External data provider rejected the credentials"


class ProviderNotConfigured(ProviderError):
    code = "PROVIDER_NOT_CONFIGURED"
    message = "External data provider is not configured"


class ProviderRateLimited(ProviderError):
    status_code = 429
    code = "PROVIDER_RATE_LIMITED"
    message = "External data provider quota or rate limit reached"


class ProviderTimeout(ProviderError):
    status_code = 504
    code = "PROVIDER_TIMEOUT"
    message = "External data provider timeout"


class ProviderUnavailable(ProviderError):
    status_code = 502
    code = "PROVIDER_UNAVAILABLE"
    message = "External data provider is unavailable"


class ProviderMalformedResponse(ProviderError):
    code = "PROVIDER_MALFORMED_RESPONSE"
    message = "External data provider returned an unexpected response"
