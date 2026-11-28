"""ApexVoice tenancy layer.

Isolated multi-tenant modules built against docs/commercial/
BACKEND_CONTRACTS.md. Nothing here imports the shared backend files
(app.py, config.py, database.py, telephony.py, voice_engine.py), so this
package can be developed, tested, and reviewed independently, then wired
in following docs/commercial/BACKEND_INTEGRATION_PATCH_SPEC.md.
"""

from . import api_models, routing, usage
from .auth import AuthService, hash_password, verify_password
from .errors import (
    AuthenticationFailed, Conflict, NotFound, PermissionDenied,
    PlanLimitReached, TenantNotActive, TenancyError, UnknownNumber,
    ValidationFailed,
)
from .ids import generate_prefixed_id, generate_tenant_id, is_valid_e164, normalize_phone
from .lifecycle import (
    HARBOUR_MAIN_TENANT_ID, TenantLifecycle, legacy_env_to_business_config,
    migrate_single_tenant,
)
from .models import (
    AppointmentRecord, CallRecord, CustomerRecord, MessageRecord,
    PhoneMapping, Session, Tenant, TenantConfig, TranscriptRecord,
    UsageRecord, User, validate_business_config,
)
from .rbac import PlatformOperator, TenantPrincipal, require, require_platform, role_has
from .routing import CallAdmission, TenantRouter
from .store import InMemoryStore, SQLiteStore, TenantStore
from .usage import PLAN_LIMITS_MINUTES, UsageMeter

__all__ = [
    "api_models", "routing", "usage",
    "AuthService", "hash_password", "verify_password",
    "AuthenticationFailed", "Conflict", "NotFound", "PermissionDenied",
    "PlanLimitReached", "TenantNotActive", "TenancyError", "UnknownNumber",
    "ValidationFailed",
    "generate_prefixed_id", "generate_tenant_id", "is_valid_e164", "normalize_phone",
    "HARBOUR_MAIN_TENANT_ID", "TenantLifecycle", "legacy_env_to_business_config",
    "migrate_single_tenant",
    "AppointmentRecord", "CallRecord", "CustomerRecord", "MessageRecord",
    "PhoneMapping", "Session", "Tenant", "TenantConfig", "TranscriptRecord",
    "UsageRecord", "User", "validate_business_config",
    "PlatformOperator", "TenantPrincipal", "require", "require_platform", "role_has",
    "CallAdmission", "TenantRouter",
    "InMemoryStore", "SQLiteStore", "TenantStore",
    "PLAN_LIMITS_MINUTES", "UsageMeter",
]
