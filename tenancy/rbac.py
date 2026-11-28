"""Role-based access control for the ApexVoice tenancy layer.

Roles: owner, admin, staff, viewer, per docs/commercial/BACKEND_CONTRACTS.md.

Two principal types exist:

- TenantPrincipal: a customer user acting inside exactly one tenant. Every
  check binds the principal to a target tenant; a mismatch is forbidden,
  and tenant lifecycle actions on any other tenant are impossible.
- PlatformOperator: Harbour & Main operations staff. This is not a tenant
  user and holds no tenant role. It is the only principal allowed to
  perform cross-tenant lifecycle actions (create, suspend, reactivate,
  delete any tenant) and to read platform-level listings.
"""

from dataclasses import dataclass

from .errors import PermissionDenied

PERMISSIONS = (
    "config.read", "config.write",
    "calls.read",
    "messages.read", "messages.write",
    "appointments.read", "appointments.write",
    "customers.read",
    "usage.read",
    "billing.read",
    "users.manage",
    "tenant.suspend", "tenant.delete",
)

_ALL_TENANT = frozenset(PERMISSIONS)

ROLE_PERMISSIONS = {
    "owner": _ALL_TENANT,
    "admin": frozenset({
        "config.read", "config.write",
        "calls.read",
        "messages.read", "messages.write",
        "appointments.read", "appointments.write",
        "customers.read",
        "usage.read",
    }),
    "staff": frozenset({
        "config.read",
        "calls.read",
        "messages.read", "messages.write",
        "appointments.read", "appointments.write",
        "customers.read",
    }),
    "viewer": frozenset({
        "config.read",
        "calls.read",
        "messages.read",
        "appointments.read",
        "customers.read",
    }),
}

# Actions only a platform operator may perform across tenants.
PLATFORM_ONLY_ACTIONS = frozenset({
    "tenant.create", "tenant.list_all", "tenant.audit.read",
})


@dataclass
class TenantPrincipal:
    user_id: str
    tenant_id: str
    role: str
    kind: str = "tenant_user"

    @classmethod
    def from_user(cls, user):
        return cls(user_id=user.id, tenant_id=user.tenant_id, role=user.role)


@dataclass
class PlatformOperator:
    operator_id: str
    kind: str = "platform_operator"


def role_has(role, permission):
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def require(principal, permission, tenant_id=None):
    """Raise PermissionDenied unless the principal may do this.

    For tenant principals, tenant_id is the tenant being acted on. It
    defaults to the principal's own tenant. Acting on any other tenant is
    always denied for tenant principals, whatever the role.
    """
    if isinstance(principal, PlatformOperator):
        if permission in PLATFORM_ONLY_ACTIONS or tenant_id is not None:
            return True
        return True
    if not isinstance(principal, TenantPrincipal):
        raise PermissionDenied("unknown principal type")
    target = tenant_id if tenant_id is not None else principal.tenant_id
    if target != principal.tenant_id:
        raise PermissionDenied("a tenant user cannot act on another tenant")
    if permission in PLATFORM_ONLY_ACTIONS:
        raise PermissionDenied("this action is reserved for the platform operator")
    if not role_has(principal.role, permission):
        raise PermissionDenied(f"role {principal.role} lacks permission {permission}")
    return True


def require_platform(principal, action):
    """Raise PermissionDenied unless principal is a platform operator."""
    if not isinstance(principal, PlatformOperator):
        raise PermissionDenied("this action is reserved for the platform operator")
    if action not in PLATFORM_ONLY_ACTIONS and action not in PERMISSIONS:
        raise PermissionDenied("unknown platform action")
    return True
