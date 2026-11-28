"""Exceptions for the ApexVoice tenancy layer.

Every error carries a stable machine readable code matching the error
catalogue in docs/commercial/BACKEND_CONTRACTS.md.
"""


class TenancyError(Exception):
    code = "tenancy_error"
    http_status = 400

    def __init__(self, message, fields=None):
        super().__init__(message)
        self.message = message
        self.fields = fields


class ValidationFailed(TenancyError):
    code = "validation_failed"
    http_status = 400


class AuthenticationFailed(TenancyError):
    code = "unauthenticated"
    http_status = 401


class PermissionDenied(TenancyError):
    code = "forbidden"
    http_status = 403


class NotFound(TenancyError):
    code = "not_found"
    http_status = 404


class Conflict(TenancyError):
    code = "conflict"
    http_status = 409


class PlanLimitReached(TenancyError):
    code = "plan_limit_reached"
    http_status = 402


class UnknownNumber(TenancyError):
    code = "number_not_in_service"
    http_status = 404


class TenantNotActive(TenancyError):
    code = "tenant_not_active"
    http_status = 403
