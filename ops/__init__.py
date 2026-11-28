"""ApexVoice platform operations layer (Phase 4).

Built on the Phase 3 packages (tenancy, voice, billing) without
modifying them. Three parts:

- aggregation: the platform overview document. Aggregate counts and
  tenant metadata only, never call content or customer personal data.
  Anything not supplied by a caller is reported as unknown or no_data.
- actions: controlled platform operator administrative actions with
  mandatory audit entries, delegating state changes to the tenancy
  lifecycle.
- health: provider health records. Health is recorded input from real
  probes, never measured or inferred by this package, and defaults to
  unknown for every provider.
"""

from .actions import OpsActions, SpendingCaps
from .aggregation import (
    FAILED_CALL_STATUSES, ONBOARDING_SECTIONS, build_audit_view,
    build_platform_overview, build_tenant_row, onboarding_status,
)
from .health import HEALTH_STATUSES, PROVIDERS, HealthRegistry, ProviderHealth

__all__ = [
    "OpsActions", "SpendingCaps",
    "FAILED_CALL_STATUSES", "ONBOARDING_SECTIONS", "build_audit_view",
    "build_platform_overview", "build_tenant_row", "onboarding_status",
    "HEALTH_STATUSES", "PROVIDERS", "HealthRegistry", "ProviderHealth",
]
