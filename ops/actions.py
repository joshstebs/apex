"""Controlled platform operator administrative actions for ApexVoice.

Every action in this module:

- requires a PlatformOperator principal. Customer scoped principals
  (TenantPrincipal) are refused for every action, including actions the
  tenancy lifecycle would otherwise allow a tenant owner to perform on
  their own tenant. Platform administration is a separate surface from
  customer self service.
- delegates tenant state changes to the tenancy lifecycle, which runs
  its own authorization checks and writes its own audit entries.
- appends an ops audit entry to the store audit log with the actor,
  the action, the tenant, a timestamp, and the operator's reason.
  Suspend and delete require a non-empty reason. Delete additionally
  requires an explicit confirm flag. The store audit log is platform
  data and is not purged when a tenant is deleted, so every action
  stays verifiable after the fact.
- returns a structured result dict. Failures raise the tenancy layer's
  typed errors, which carry the contract error codes (forbidden,
  validation_failed, not_found, conflict).

Spending caps: the Phase 3 Tenant model has no field for an operator
set spending cap, so caps live in the SpendingCaps registry here and
are injected into the aggregation layer. The registry is in-memory;
the backend integration must persist caps (a tenant metadata field or
a platform table) before they can be treated as durable. Plan limits
from the tenancy usage module still apply independently of any cap.
"""

from tenancy.errors import NotFound, PermissionDenied, ValidationFailed
from tenancy.ids import generate_prefixed_id
from tenancy.lifecycle import TenantLifecycle
from tenancy.models import now_iso
from tenancy.rbac import PlatformOperator


class SpendingCaps:
    """In-memory registry of operator set spending caps, by tenant.

    A cap is a dict with optional cap_minutes and cap_cad_cents keys;
    either one being reached marks the tenant cap_exceeded in the
    platform overview. Enforcement during live calls is a backend
    concern; this registry is the record of what the operator set.
    """

    def __init__(self):
        self._caps = {}

    def get(self, tenant_id):
        cap = self._caps.get(tenant_id)
        return dict(cap) if cap else None

    def set(self, tenant_id, cap_minutes=None, cap_cad_cents=None):
        cap = {"cap_minutes": cap_minutes, "cap_cad_cents": cap_cad_cents}
        self._caps[tenant_id] = cap
        return dict(cap)

    def clear(self, tenant_id):
        return self._caps.pop(tenant_id, None) is not None


class OpsActions:
    """Platform operator actions over one TenantStore."""

    def __init__(self, store, lifecycle=None, caps=None):
        self.store = store
        self.lifecycle = lifecycle or TenantLifecycle(store)
        self.caps = caps or SpendingCaps()

    # internal helpers

    def _require_operator(self, principal):
        if not isinstance(principal, PlatformOperator):
            raise PermissionDenied(
                "platform actions are reserved for the platform operator")
        return f"platform:{principal.operator_id}"

    @staticmethod
    def _require_reason(reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationFailed(
                "a reason is required for this action",
                fields={"reason": "required"})
        return reason.strip()

    def _audit(self, actor, tenant_id, action, details):
        entry = {
            "id": generate_prefixed_id("audit_"),
            "tenant_id": tenant_id,
            "action": action,
            "actor": actor,
            "at": now_iso(),
            "details": details,
        }
        return self.store.append_audit(entry)

    @staticmethod
    def _result(action, tenant_id, actor, entry, extra=None):
        result = {
            "ok": True,
            "action": action,
            "tenant_id": tenant_id,
            "actor": actor,
            "at": entry["at"],
            "audit_id": entry["id"],
        }
        if extra:
            result.update(extra)
        return result

    def _must_get(self, tenant_id):
        tenant = self.store.get_tenant(tenant_id)
        if tenant is None:
            raise NotFound("tenant not found")
        return tenant

    # actions

    def create_tenant(self, principal, legal_name, owner_email, owner_password,
                      display_name="", plan_tier="starter",
                      timezone="America/Toronto", config=None, did=None,
                      tenant_id=None, reason=""):
        """Create a tenant with its owner user, via the lifecycle."""
        actor = self._require_operator(principal)
        tenant, owner = self.lifecycle.create_tenant(
            principal, legal_name, owner_email, owner_password,
            display_name=display_name, plan_tier=plan_tier,
            timezone=timezone, config=config, did=did, tenant_id=tenant_id)
        entry = self._audit(actor, tenant.id, "platform.tenant_created", {
            "reason": reason or "",
            "plan_tier": plan_tier,
            "owner_user_id": owner.id,
        })
        return self._result("create_tenant", tenant.id, actor, entry, {
            "status": tenant.status,
            "owner_user_id": owner.id,
        })

    def suspend_tenant(self, principal, tenant_id, reason):
        """Suspend a tenant. A reason is required and audited."""
        actor = self._require_operator(principal)
        reason = self._require_reason(reason)
        tenant = self.lifecycle.suspend_tenant(principal, tenant_id)
        entry = self._audit(actor, tenant_id, "platform.tenant_suspended",
                            {"reason": reason})
        return self._result("suspend_tenant", tenant_id, actor, entry,
                            {"status": tenant.status})

    def reactivate_tenant(self, principal, tenant_id, reason=""):
        """Reactivate a suspended tenant, via the lifecycle."""
        actor = self._require_operator(principal)
        tenant = self.lifecycle.reactivate_tenant(principal, tenant_id)
        entry = self._audit(actor, tenant_id, "platform.tenant_reactivated",
                            {"reason": reason or ""})
        return self._result("reactivate_tenant", tenant_id, actor, entry,
                            {"status": tenant.status})

    def delete_tenant(self, principal, tenant_id, reason, confirm=False):
        """Delete and purge a tenant. Requires a reason and an
        explicit confirm flag. The audit entries written here survive
        the purge because the audit log is platform data."""
        actor = self._require_operator(principal)
        reason = self._require_reason(reason)
        if confirm is not True:
            raise ValidationFailed(
                "deleting a tenant requires explicit confirmation",
                fields={"confirm": "pass confirm=True to delete"})
        self._must_get(tenant_id)
        self.lifecycle.delete_tenant(principal, tenant_id)
        entry = self._audit(actor, tenant_id, "platform.tenant_deleted",
                            {"reason": reason})
        return self._result("delete_tenant", tenant_id, actor, entry,
                            {"status": "deleted"})

    def set_spending_cap(self, principal, tenant_id, cap_minutes=None,
                         cap_cad_cents=None, reason=""):
        """Set or replace the operator spending cap for one tenant.

        At least one of cap_minutes or cap_cad_cents is required, and
        each supplied value must be non-negative.
        """
        actor = self._require_operator(principal)
        self._must_get(tenant_id)
        if cap_minutes is None and cap_cad_cents is None:
            raise ValidationFailed(
                "at least one cap value is required",
                fields={"cap": "cap_minutes or cap_cad_cents required"})
        for name, value in (("cap_minutes", cap_minutes),
                            ("cap_cad_cents", cap_cad_cents)):
            if value is not None and value < 0:
                raise ValidationFailed(
                    "cap values cannot be negative", fields={name: "negative"})
        cap = self.caps.set(tenant_id, cap_minutes=cap_minutes,
                            cap_cad_cents=cap_cad_cents)
        entry = self._audit(actor, tenant_id, "platform.spending_cap_set", {
            "reason": reason or "",
            "cap_minutes": cap_minutes,
            "cap_cad_cents": cap_cad_cents,
        })
        return self._result("set_spending_cap", tenant_id, actor, entry,
                            {"cap": cap})
