"""Secure tenant data export, configuration backup, and restore checks.

Exports are built from explicit field allowlists. Password hashes,
password salts, session records, tokens, and any secret material are
excluded by construction: the allowlists simply never name those
fields, and validate_export_safety scans a finished export for
forbidden key names as a second line of defence.

An export is a JSON-serializable dict. It contains the tenant record
(public fields), the BusinessConfig document, phone number assignments,
dashboard users in their public form (the tenancy layer's
User.public_dict, which carries no credential material), and the
tenant's call, message, appointment, and usage records.

Retention defaults below come from the Phase 2 privacy analysis
(docs/commercial/PRIVACY_AND_TRUST.md) and the data retention draft
(docs/legal-drafts/DATA_RETENTION_AND_DELETION.md). They are
RECOMMENDED defaults pending professional legal review and formal
adoption as policy. They are recorded here so the operations tooling
and the policy documents cannot silently drift apart. Nothing in this
module deletes anything.
"""

import copy
import json

from tenancy.errors import ValidationFailed
from tenancy.models import TenantConfig, validate_business_config

EXPORT_VERSION = 1

# Retention recommendations from the Phase 2 privacy analysis and the
# retention and deletion draft. Status: recommended, pending legal
# review and adoption. Not a statement of law.
RETENTION_DEFAULTS = {
    "status": "recommended defaults from the Phase 2 privacy analysis, pending legal review and adoption as policy",
    "audio_recordings_days": 30,
    "audio_recordings_range_days": (30, 90),
    "transcripts_days_by_plan": {
        "starter": 90, "professional": 365, "business": 730,
    },
    "summaries_and_messages": "same period as transcripts for the tenant plan",
    "appointment_records": "same period as transcripts, unless the business designates ApexVoice as its only record under a written exception",
    "call_metadata_months": 24,
    "support_communications_months": 24,
    "security_and_audit_logs_months": (12, 24),
    "billing_records": "period required by Canadian tax and accounting law, confirmed by an accountant",
    "backups": "rolling, deleted within 30 days after source deletion where the provider supports it",
    "closure_export_window_days": 30,
}

_TENANT_FIELDS = (
    "id", "legal_name", "display_name", "status", "plan_tier",
    "timezone", "created_at", "updated_at",
)
_PHONE_FIELDS = ("did", "status", "provider")

RECORD_FIELDS = {
    "calls": (
        "id", "tenant_id", "created_at", "from_number", "to_number",
        "status", "direction", "duration_seconds", "contact_name",
        "summary", "appointment_id", "message_id",
    ),
    "messages": (
        "id", "tenant_id", "created_at", "call_id", "caller_name",
        "callback_number", "reason", "preferred_time", "urgent", "handled",
    ),
    "appointments": (
        "id", "tenant_id", "created_at", "call_id", "contact_name",
        "contact_phone", "service_name", "requested_start",
        "requested_end", "status", "notes",
    ),
    "usage": (
        "id", "tenant_id", "created_at", "call_id", "period", "minutes",
        "calls", "tts_characters", "stt_seconds",
    ),
}

EXPORTED_RECORD_KINDS = tuple(RECORD_FIELDS.keys())

# Key name fragments that must never appear anywhere in an export.
FORBIDDEN_KEY_FRAGMENTS = (
    "password", "passwd", "salt", "token", "session", "secret",
    "api_key", "apikey", "credential", "private_key", "auth_hash",
)


def _pick(source, fields):
    if source is None:
        return None
    if hasattr(source, "to_dict"):
        data = source.to_dict()
    elif isinstance(source, dict):
        data = source
    else:
        data = {name: getattr(source, name) for name in fields if hasattr(source, name)}
    return {name: copy.deepcopy(data.get(name)) for name in fields}


def config_backup(config):
    """Return the BusinessConfig document for a tenant, deep copied.

    Accepts a TenantConfig or a plain BusinessConfig dict. This is the
    same document the onboarding wizard downloads, so a backup taken
    here can be re-imported through onboarding unchanged.
    """
    if isinstance(config, TenantConfig):
        return copy.deepcopy(config.config)
    if isinstance(config, dict) and "config" in config and "tenant_id" in config:
        return copy.deepcopy(config["config"])
    return copy.deepcopy(config)


def export_tenant_data(store, tenant_id, exported_at=""):
    """Build the full export dict for one tenant from a tenancy store."""
    tenant = store.get_tenant(tenant_id)
    if tenant is None:
        raise ValueError(f"tenant not found: {tenant_id}")
    tenant_config = store.get_config(tenant_id)
    export = {
        "export_version": EXPORT_VERSION,
        "tenant_id": tenant_id,
        "exported_at": exported_at,
        "tenant": _pick(tenant, _TENANT_FIELDS),
        "config": config_backup(tenant_config) if tenant_config else None,
        "config_version": tenant_config.version if tenant_config else None,
        "phone_numbers": [
            _pick(mapping, _PHONE_FIELDS)
            for mapping in store.list_phone_mappings(tenant_id)
        ],
        "users": [
            user.public_dict() for user in store.list_users(tenant_id)
        ],
        "records": {
            kind: [
                _pick(record, RECORD_FIELDS[kind])
                for record in store.list_records(tenant_id, kind)
            ]
            for kind in EXPORTED_RECORD_KINDS
        },
    }
    problems = validate_export_safety(export)
    if problems:
        raise ValueError(
            "export failed its safety scan: " + ", ".join(problems))
    return export


def validate_export_safety(export):
    """Return a list of paths whose key names look like secret material.

    An empty list means the export passed. This is a defence in depth
    scan on top of the allowlist construction.
    """
    findings = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                if any(fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS):
                    findings.append(f"{path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(export, "$")
    return findings


def restore_readiness_check(export):
    """Check that an export's configuration can be restored.

    The configuration is parsed back through the same BusinessConfig
    validation the tenancy layer enforces on every stored config, by
    constructing a TenantConfig. Returns a dict with ok and, when the
    config does not validate, the field problems.
    """
    config = export.get("config") if isinstance(export, dict) else None
    if not isinstance(config, dict):
        return {"ok": False, "problems": {"config": "missing from export"}}
    problems = validate_business_config(config)
    if problems:
        return {"ok": False, "problems": problems}
    try:
        TenantConfig(tenant_id=export.get("tenant_id", "ten_restore_check"),
                     config=copy.deepcopy(config))
    except ValidationFailed as exc:
        return {"ok": False, "problems": exc.fields or {"config": exc.message}}
    return {"ok": True, "problems": {}}


def export_to_json(export):
    """Serialize an export dict to a JSON string."""
    return json.dumps(export, indent=2, sort_keys=True)
