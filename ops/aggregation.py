"""Platform level aggregation for the ApexVoice operator overview.

DATA MINIMIZATION RULE: the platform overview contains aggregate counts
and tenant metadata only. It never includes one tenant's call content,
transcripts, message bodies, appointment notes, or customer personal
data. This is enforced by construction, not by filtering after the
fact: the builders in this module read only tenant registry rows,
phone mapping identifiers, configuration section presence (never
configuration values), usage records, billing state records passed in
by the caller, and the status field of call records passed in by the
caller. Transcript, message, appointment, and customer records are
never read at all.

Everything this module cannot know is reported as unknown or no_data,
never as a fabricated zero:

- Subscription state comes from billing state records passed in. A
  tenant with no record passed in is reported as state "unknown".
- Failed call metrics come only from call records passed in. When no
  records are supplied for a tenant, the result carries an explicit
  no_data marker and None counts.
- Active calls come only from an injected active call provider. When
  none is injected, the result is status "unknown" with a None count.
- Provider health comes from a HealthRegistry (see ops/health.py) and
  defaults to unknown for every provider.
- Support counts come only from an injected support provider. The
  Phase 3 packages define no support ticket record, so until a caller
  supplies counts the support summary is an explicit no_data marker.

Cost model: a tenant's estimated operating cost for a period is its
used minutes times the full per minute cost of its voice provider from
the voice package (synthesis plus the audited transport, language
model, and speech recognition allowance lines), plus the fixed per
tenant monthly allowance from the voice cost model (7.00 CAD). These
are planning estimates from the commercial pricing model, not invoice
verified charges. Revenue is the monthly list price of the tenant's
billing tier from the billing package, counted only while the
subscription state is active or past_due. Contribution is revenue
minus estimated cost.
"""

from typing import Optional

from billing.tiers import TIERS
from tenancy.models import now_iso
from tenancy.usage import PLAN_LIMITS_MINUTES, UsageMeter, current_period
from voice.providers import (
    FIXED_PER_TENANT_CAD_PER_MONTH, get_provider, total_cost_per_minute,
)
from voice.selection import default_config

from .health import HealthRegistry

# Call statuses counted as failed for the error rate. A status outside
# this set and outside a completed state still counts toward the total.
FAILED_CALL_STATUSES = frozenset({
    "failed", "error", "busy", "no_answer", "no-answer", "unanswered",
})

# BusinessConfig sections whose presence marks onboarding progress.
# Presence is checked by key and non-emptiness only; values are never
# copied into the overview.
ONBOARDING_SECTIONS = (
    "businessName", "contact", "hours", "receptionistName", "greeting",
    "services", "faqs", "bookingPrefs", "transferRules", "afterHours",
    "messageDelivery", "voice", "instructions", "industry", "timezone",
)

TENANT_STATUSES = ("trial", "active", "past_due", "suspended", "deleted")

# Subscription states in which the monthly price is treated as revenue.
REVENUE_STATES = frozenset({"active", "past_due"})

FIXED_CENTS = int(round(FIXED_PER_TENANT_CAD_PER_MONTH * 100))


def _resolve(provider, tenant_id):
    """Resolve a per tenant injected provider to a value or None.

    Accepts None, a dict keyed by tenant_id, a callable taking
    tenant_id, or an object with a .get(tenant_id) method such as
    VoiceConfigStore or the ops SpendingCaps registry.
    """
    if provider is None:
        return None
    if isinstance(provider, dict):
        return provider.get(tenant_id)
    if callable(provider):
        return provider(tenant_id)
    get = getattr(provider, "get", None)
    if get is not None:
        return get(tenant_id)
    return None


def _voice_config(voice_configs, tenant_id):
    config = _resolve(voice_configs, tenant_id)
    if config is None:
        return default_config(tenant_id)
    return config


def _per_minute_cad(voice_config):
    provider = get_provider(voice_config.provider)
    return total_cost_per_minute(provider)["total"]


def _cost_cents(minutes, per_minute_cad, include_fixed):
    cents = int(round(minutes * per_minute_cad * 100))
    if include_fixed:
        cents += FIXED_CENTS
    return cents


def _section_present(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def onboarding_status(tenant_config):
    """Which BusinessConfig sections are present, by name only."""
    if tenant_config is None:
        return {
            "status": "not_started",
            "present": [],
            "missing": list(ONBOARDING_SECTIONS),
            "percent": 0,
            "config_version": None,
        }
    document = tenant_config.config or {}
    present = [name for name in ONBOARDING_SECTIONS
               if name in document and _section_present(document[name])]
    missing = [name for name in ONBOARDING_SECTIONS if name not in present]
    percent = int(round(100.0 * len(present) / len(ONBOARDING_SECTIONS)))
    return {
        "status": "complete" if not missing else "partial",
        "present": present,
        "missing": missing,
        "percent": percent,
        "config_version": tenant_config.version,
    }


def _subscription(billing_record, tenant):
    """Subscription state and revenue from one billing record or None."""
    if billing_record is None:
        return {"status": "no_record", "state": "unknown", "tier_id": None}, None
    state = getattr(billing_record, "state", "unknown")
    state_value = state.value if hasattr(state, "value") else str(state)
    tier_id = getattr(billing_record, "tier_id", None) or tenant.plan_tier
    revenue = None
    if state_value in REVENUE_STATES:
        tier = TIERS.get(tier_id)
        revenue = tier.monthly_price_cad_cents if tier is not None else None
    else:
        revenue = 0
    info = {"status": "available", "state": state_value, "tier_id": tier_id}
    return info, revenue


def _record_status(record):
    if isinstance(record, dict):
        return str(record.get("status", ""))
    return str(getattr(record, "status", ""))


def _call_metrics(records):
    """Failed call count and error rate from supplied records only."""
    if records is None:
        return {"status": "no_data", "total": None, "failed": None,
                "error_rate": None}
    records = list(records)
    total = len(records)
    failed = sum(1 for r in records if _record_status(r) in FAILED_CALL_STATUSES)
    return {
        "status": "available",
        "total": total,
        "failed": failed,
        "error_rate": (failed / total) if total else None,
    }


def _normalize_cap(raw):
    if not raw:
        return None
    return {
        "cap_minutes": raw.get("cap_minutes"),
        "cap_cad_cents": raw.get("cap_cad_cents"),
    }


def _spending(tenant, used_minutes, estimated_cost_cents, cap):
    limit = PLAN_LIMITS_MINUTES.get(tenant.plan_tier)
    remaining = None if limit is None else max(0.0, limit - used_minutes)
    percent = None
    if limit:
        percent = round(100.0 * used_minutes / limit, 1)
    if cap and cap.get("cap_minutes") is not None and used_minutes >= cap["cap_minutes"]:
        status = "cap_exceeded"
    elif cap and cap.get("cap_cad_cents") is not None and estimated_cost_cents >= cap["cap_cad_cents"]:
        status = "cap_exceeded"
    elif limit is not None and used_minutes >= limit:
        status = "at_or_over_limit"
    elif limit is None and not cap:
        status = "unlimited"
    elif percent is not None and percent >= 80.0:
        status = "near_limit"
    else:
        status = "within_limit"
    return {
        "plan_limit_minutes": limit,
        "used_minutes": used_minutes,
        "remaining_minutes": remaining,
        "percent_used": percent,
        "cap": cap,
        "status": status,
    }


def _usage_history(store, tenant_id, per_minute_cad, include_fixed):
    by_period = {}
    for record in store.list_records(tenant_id, "usage"):
        bucket = by_period.setdefault(record.period, {
            "period": record.period, "used_minutes": 0.0, "call_count": 0,
        })
        bucket["used_minutes"] += record.minutes
        bucket["call_count"] += record.calls
    history = []
    for period in sorted(by_period):
        bucket = by_period[period]
        bucket["estimated_cost_cents"] = _cost_cents(
            bucket["used_minutes"], per_minute_cad, include_fixed)
        history.append(bucket)
    return history


def _active_call_view(raw):
    """Metadata only view of one active call supplied by a provider."""
    if isinstance(raw, dict):
        return {
            "call_id": raw.get("call_id") or raw.get("id"),
            "tenant_id": raw.get("tenant_id"),
            "started_at": raw.get("started_at") or raw.get("created_at"),
            "direction": raw.get("direction"),
            "status": raw.get("status"),
        }
    return {
        "call_id": getattr(raw, "id", None),
        "tenant_id": getattr(raw, "tenant_id", None),
        "started_at": getattr(raw, "created_at", None),
        "direction": getattr(raw, "direction", None),
        "status": getattr(raw, "status", None),
    }


def _active_calls_block(active_calls):
    if active_calls is None:
        return {"status": "unknown", "count": None, "calls": None}
    raw = active_calls() if callable(active_calls) else list(active_calls)
    calls = [_active_call_view(item) for item in raw]
    return {"status": "available", "count": len(calls), "calls": calls}


def _support_block(support_counts):
    if support_counts is None:
        return {"status": "no_data", "open_total": None, "by_tenant": None}
    data = support_counts() if callable(support_counts) else support_counts
    by_tenant = {}
    for tenant_id, value in dict(data).items():
        if isinstance(value, dict):
            by_tenant[tenant_id] = int(value.get("open", 0))
        else:
            by_tenant[tenant_id] = int(value)
    return {
        "status": "available",
        "open_total": sum(by_tenant.values()),
        "by_tenant": by_tenant,
    }


def build_tenant_row(store, tenant, *, period=None, billing_records=None,
                     call_records=None, voice_configs=None, spending_caps=None):
    """One tenant's platform row: metadata and aggregates only."""
    period = period or current_period()
    meter = UsageMeter(store)
    summary = meter.summary(tenant.id, period)
    used_minutes = summary["used_minutes"]

    voice_config = _voice_config(voice_configs, tenant.id)
    per_minute = _per_minute_cad(voice_config)

    deleted = tenant.status == "deleted"
    include_fixed = not deleted
    if deleted:
        estimated_cost = 0
    else:
        estimated_cost = _cost_cents(used_minutes, per_minute, include_fixed)

    subscription, revenue = _subscription(
        _resolve(billing_records, tenant.id), tenant)
    if deleted:
        revenue = 0
    contribution = None
    if revenue is not None:
        contribution = revenue - estimated_cost

    cap = _normalize_cap(_resolve(spending_caps, tenant.id))
    if deleted:
        spending = {
            "plan_limit_minutes": PLAN_LIMITS_MINUTES.get(tenant.plan_tier),
            "used_minutes": used_minutes,
            "remaining_minutes": 0.0,
            "percent_used": None,
            "cap": cap,
            "status": "closed",
        }
    else:
        spending = _spending(tenant, used_minutes, estimated_cost, cap)

    return {
        "tenant_id": tenant.id,
        "business_name": tenant.display_name,
        "legal_name": tenant.legal_name,
        "status": tenant.status,
        "plan_tier": tenant.plan_tier,
        "timezone": tenant.timezone,
        "created_at": tenant.created_at,
        "subscription": subscription,
        "phone_numbers": [m.did for m in store.list_phone_mappings(tenant.id)],
        "onboarding": onboarding_status(store.get_config(tenant.id)),
        "voice": {"tier": voice_config.tier, "provider": voice_config.provider},
        "usage": {
            "period": period,
            "used_minutes": used_minutes,
            "call_count": summary["call_count"],
            "tts_characters": summary["tts_characters"],
            "stt_seconds": summary["stt_seconds"],
        },
        "usage_history": _usage_history(
            store, tenant.id, per_minute, include_fixed),
        "estimated_cost_cents": estimated_cost,
        "revenue_cents": revenue,
        "contribution_cents": contribution,
        "currency": "CAD",
        "spending": spending,
        "calls": _call_metrics(_resolve(call_records, tenant.id)),
    }


def build_platform_overview(store, *, period=None, billing_records=None,
                            call_records=None, active_calls=None,
                            voice_configs=None, spending_caps=None,
                            health_registry=None, support_counts=None):
    """The full platform overview document.

    All parameters after the store are injected data providers; see the
    module docstring for what each one supplies and what happens when
    it is absent. Nothing is measured or invented here.
    """
    period = period or current_period()
    tenants = store.list_tenants()
    rows = [
        build_tenant_row(
            store, tenant, period=period, billing_records=billing_records,
            call_records=call_records, voice_configs=voice_configs,
            spending_caps=spending_caps)
        for tenant in tenants
    ]

    by_status = {status: 0 for status in TENANT_STATUSES}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1

    revenue_known = [r for r in rows if r["revenue_cents"] is not None]
    totals = {
        "tenant_count": len(rows),
        "tenants_by_status": by_status,
        "tenants_without_billing_record": len(rows) - len(revenue_known),
        "current_period": {
            "period": period,
            "used_minutes": sum(r["usage"]["used_minutes"] for r in rows),
            "call_count": sum(r["usage"]["call_count"] for r in rows),
            "estimated_cost_cents": sum(r["estimated_cost_cents"] for r in rows),
            "revenue_cents": sum(r["revenue_cents"] for r in revenue_known),
            "contribution_cents": sum(
                r["contribution_cents"] for r in revenue_known),
        },
    }

    metric_rows = [r["calls"] for r in rows if r["calls"]["status"] == "available"]
    if metric_rows:
        total_calls = sum(m["total"] for m in metric_rows)
        total_failed = sum(m["failed"] for m in metric_rows)
        call_metrics = {
            "status": "available" if len(metric_rows) == len(rows) else "partial",
            "total": total_calls,
            "failed": total_failed,
            "error_rate": (total_failed / total_calls) if total_calls else None,
        }
    else:
        call_metrics = {"status": "no_data", "total": None, "failed": None,
                        "error_rate": None}

    registry = health_registry or HealthRegistry()
    active = _active_calls_block(active_calls)
    if active["status"] == "available":
        counts = {}
        for call in active["calls"]:
            if call["tenant_id"]:
                counts[call["tenant_id"]] = counts.get(call["tenant_id"], 0) + 1
        active["by_tenant"] = counts
    else:
        active["by_tenant"] = None

    return {
        "generated_at": now_iso(),
        "period": period,
        "totals": totals,
        "tenants": rows,
        "call_metrics": call_metrics,
        "provider_health": registry.to_dicts(),
        "active_calls": active,
        "support": _support_block(support_counts),
    }


def build_audit_view(store, tenant_id=None):
    """Audit entries exactly as stored. The audit log is platform data
    and survives tenant deletion, so deletions stay verifiable."""
    return {"entries": store.list_audit(tenant_id)}
