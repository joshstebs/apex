"""Tenant lifecycle: creation, suspension, reactivation, deletion, and
migration of the existing single-business installation.

Lifecycle actions across tenants are platform operator actions. A tenant
owner may suspend or delete only their own tenant (enforced through the
RBAC require check). Deletion purges every record the tenant owns and
leaves a platform-side audit entry; the audit log itself is platform data
and is not purged, so a deletion remains verifiable after the fact.
"""

from .auth import AuthService
from .errors import NotFound, ValidationFailed
from .ids import generate_prefixed_id, generate_tenant_id, normalize_phone
from .models import PhoneMapping, Tenant, TenantConfig, now_iso
from .rbac import PlatformOperator, TenantPrincipal, require, require_platform

HARBOUR_MAIN_TENANT_ID = "ten_harbour_main"
LEGACY_DID = "+12267732234"


def _audit(store, tenant_id, action, actor, details=None):
    entry = {
        "id": generate_prefixed_id("audit_"),
        "tenant_id": tenant_id,
        "action": action,
        "actor": actor,
        "at": now_iso(),
        "details": details or {},
    }
    return store.append_audit(entry)


def _actor_label(principal):
    if isinstance(principal, PlatformOperator):
        return f"platform:{principal.operator_id}"
    return f"user:{principal.user_id}"


class TenantLifecycle:
    def __init__(self, store, auth=None):
        self.store = store
        self.auth = auth or AuthService(store)

    def create_tenant(self, principal, legal_name, owner_email, owner_password,
                      display_name="", plan_tier="starter", timezone="America/Toronto",
                      config=None, did=None, tenant_id=None):
        """Platform only. Creates the tenant, its owner user, and
        optionally its first configuration and phone mapping."""
        require_platform(principal, "tenant.create")
        tenant = Tenant(
            id=tenant_id or generate_tenant_id(self.store),
            legal_name=legal_name, display_name=display_name or legal_name,
            status="active", plan_tier=plan_tier, timezone=timezone)
        self.store.create_tenant(tenant)
        owner = self.auth.create_user(tenant.id, owner_email, owner_password, "owner")
        if config is not None:
            self.store.put_config(TenantConfig(
                tenant_id=tenant.id, config=config, version=1, updated_by=owner.id))
        if did is not None:
            self.store.add_phone_mapping(PhoneMapping(
                did=normalize_phone(did), tenant_id=tenant.id))
        _audit(self.store, tenant.id, "tenant.created", _actor_label(principal),
               {"plan_tier": plan_tier, "owner_user_id": owner.id})
        return tenant, owner

    def suspend_tenant(self, principal, tenant_id):
        if isinstance(principal, TenantPrincipal):
            require(principal, "tenant.suspend", tenant_id=tenant_id)
        else:
            require_platform(principal, "tenant.suspend")
        tenant = self._must_get(tenant_id)
        tenant.status = "suspended"
        self.store.update_tenant(tenant)
        _audit(self.store, tenant_id, "tenant.suspended", _actor_label(principal))
        return tenant

    def reactivate_tenant(self, principal, tenant_id):
        require_platform(principal, "tenant.suspend")
        tenant = self._must_get(tenant_id)
        if tenant.status != "suspended":
            raise ValidationFailed("only a suspended tenant can be reactivated",
                                   fields={"status": "not_suspended"})
        tenant.status = "active"
        self.store.update_tenant(tenant)
        _audit(self.store, tenant_id, "tenant.reactivated", _actor_label(principal))
        return tenant

    def delete_tenant(self, principal, tenant_id):
        """Purge a tenant and everything it owns. Platform operator, or
        the tenant's own owner. Other tenants are untouched."""
        if isinstance(principal, TenantPrincipal):
            require(principal, "tenant.delete", tenant_id=tenant_id)
        else:
            require_platform(principal, "tenant.delete")
        self._must_get(tenant_id)
        _audit(self.store, tenant_id, "tenant.deleted", _actor_label(principal))
        self.store.purge_tenant(tenant_id)
        return True

    def _must_get(self, tenant_id):
        tenant = self.store.get_tenant(tenant_id)
        if tenant is None:
            raise NotFound("tenant not found")
        return tenant


def legacy_env_to_business_config(env, owner_email, business_name=None):
    """Map a legacy environment-style config dict to a BusinessConfig.

    Accepts the variable names the single-tenant deployment used
    (BUSINESS_NAME, BUSINESS_PHONE, BUSINESS_SERVICES, BUSINESS_HOURS,
    BUSINESS_ADDRESS, OWNER_PHONE, BUSINESS_TIMEZONE) and produces a
    contract-shaped document with conservative defaults where the legacy
    config carried no equivalent. Nothing is invented about prices or
    availability: services carry an empty price string, which the
    assistant must treat as no price to state.
    """
    name = business_name or env.get("BUSINESS_NAME") or env.get("RECEPTIONIST_BUSINESS_NAME") or "Harbour & Main"
    phone = env.get("BUSINESS_PHONE") or env.get("OWNER_PHONE") or LEGACY_DID
    services_text = env.get("BUSINESS_SERVICES", "")
    services = [{"name": item.strip(), "price": "", "description": ""}
                for item in services_text.split(",") if item.strip()]
    weekday = {"open": "09:00", "close": "17:00", "closed": False}
    weekend = {"open": None, "close": None, "closed": True}
    hours = {day: dict(weekday) for day in
             ("monday", "tuesday", "wednesday", "thursday", "friday")}
    hours["saturday"] = dict(weekend)
    hours["sunday"] = dict(weekend)
    hours_note = env.get("BUSINESS_HOURS", "")
    instructions = (
        "Migrated from the legacy single-tenant configuration. "
        f"Legacy hours text: {hours_note}. Review and correct the "
        "structured hours, greeting, and services in onboarding.")
    return {
        "businessName": name,
        "contact": {
            "ownerName": env.get("OWNER_NAME", ""),
            "email": owner_email,
            "phone": normalize_phone(phone),
            "address": env.get("BUSINESS_ADDRESS", ""),
            "website": env.get("BUSINESS_WEBSITE", ""),
        },
        "hours": hours,
        "holidays": [],
        "receptionistName": env.get("RECEPTIONIST_NAME", "Harper"),
        "greeting": (
            f"Thank you for calling {name}. This is an automated assistant. "
            "Calls may be recorded and transcribed to help us serve you. "
            "How can I help you today?"),
        "services": services,
        "faqs": [],
        "bookingPrefs": {
            "enabled": True, "mode": "request_only", "leadTimeHours": 2,
            "slotLengthMinutes": 60, "bufferMinutes": 15, "maxAdvanceDays": 30,
            "collectFields": ["name", "phone", "service", "preferred_time"],
            "confirmationMethod": "callback", "notes": "",
        },
        "transferRules": {
            "enabled": False, "numbers": [],
            "triggers": ["caller asks for a person"],
            "maxAttempts": 2, "fallback": "take_message",
        },
        "afterHours": {
            "behaviour": "take_message",
            "greeting": (
                f"Thank you for calling {name}. Our office is currently closed. "
                "This is an automated assistant. Calls may be recorded and "
                "transcribed. Please leave a message and we will call you back "
                "on the next business day."),
            "emergencyTransferEnabled": False,
            "emergencyNumber": "",
            "expectedCallback": "next business day",
        },
        "messageDelivery": {
            "methods": ["email", "dashboard"], "emailTo": [owner_email],
            "smsTo": [], "urgentOnlySms": True, "dailySummary": True,
            "dailySummaryTime": "08:00",
        },
        "voice": {
            "voiceId": env.get("ELEVENLABS_DEFAULT_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
            "personality": "warm, clear, and efficient",
            "speakingRate": "normal", "language": "en-CA",
        },
        "instructions": instructions,
        "industry": env.get("BUSINESS_INDUSTRY", "general_small_business"),
        "timezone": env.get("BUSINESS_TIMEZONE", "America/Toronto"),
    }


def migrate_single_tenant(store, config_dict, did, owner_email, owner_password,
                          tenant_id=HARBOUR_MAIN_TENANT_ID, operator=None):
    """Build the Harbour & Main tenant from the legacy installation.

    config_dict may be a full BusinessConfig document (it is validated
    and stored unchanged) or a legacy env-style dict (it is mapped with
    legacy_env_to_business_config). The existing DID is mapped to the new
    tenant so callers keep reaching the same business, and the owner can
    log in with the supplied credentials. Existing call data is not
    copied: the backend integration spec describes backfilling tenant_id
    on existing rows to this tenant id instead.

    Returns (tenant, owner_user).
    """
    operator = operator or PlatformOperator(operator_id="migration")
    auth = AuthService(store)
    if isinstance(config_dict, dict) and "businessName" in config_dict:
        config = config_dict
        business_name = config_dict["businessName"]
        timezone_name = config_dict.get("timezone", "America/Toronto")
    else:
        config = legacy_env_to_business_config(config_dict or {}, owner_email)
        business_name = config["businessName"]
        timezone_name = config["timezone"]
    tenant = Tenant(
        id=tenant_id, legal_name=business_name, display_name=business_name,
        status="active", plan_tier="professional", timezone=timezone_name)
    store.create_tenant(tenant)
    owner = auth.create_user(tenant.id, owner_email, owner_password, "owner")
    store.put_config(TenantConfig(
        tenant_id=tenant.id, config=config, version=1, updated_by=owner.id))
    store.add_phone_mapping(PhoneMapping(
        did=normalize_phone(did or LEGACY_DID), tenant_id=tenant.id))
    _audit(store, tenant.id, "tenant.migrated_from_single_tenant",
           _actor_label(operator), {"did": normalize_phone(did or LEGACY_DID)})
    return tenant, owner
