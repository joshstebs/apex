"""Monthly per-tenant usage summaries.

Builds a summary from tenancy usage records only. Nothing is estimated
beyond the cost figure, which uses the same planning rates as the
tenancy usage meter (docs in tenancy/usage.py: these are planning
estimates from the commercial pricing model, not invoice-verified
charges, and the summary text says so).

Records may be tenancy UsageRecord objects or plain dicts with the same
field names. Only records matching the requested tenant and period are
counted, so a summary built from a mixed list can never leak another
tenant's usage into the totals.
"""

try:
    from tenancy.usage import PLAN_LIMITS_MINUTES, DEFAULT_RATES_CAD_CENTS
except ImportError:  # pragma: no cover, tenancy layer is expected on the path
    PLAN_LIMITS_MINUTES = {
        "starter": 120, "professional": 350, "business": 800, "enterprise": None,
    }
    DEFAULT_RATES_CAD_CENTS = {
        "per_minute": 13.5, "per_tts_1000_characters": 10.4,
        "per_stt_minute": 0.0, "per_call": 0.0,
    }


def _field(record, name, default=0):
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def estimate_cost_cents(minutes=0.0, calls=0, tts_characters=0, stt_seconds=0.0,
                        rates=None):
    """Mirror of tenancy UsageMeter.estimate_cost_cents, kept local so a
    summary can be built from records without a store."""
    active = dict(DEFAULT_RATES_CAD_CENTS)
    if rates:
        active.update(rates)
    cents = (
        minutes * active["per_minute"]
        + calls * active["per_call"]
        + (tts_characters / 1000.0) * active["per_tts_1000_characters"]
        + (stt_seconds / 60.0) * active["per_stt_minute"]
    )
    return int(round(cents))


def monthly_summary(records, tenant_id, period, plan_tier=None, rates=None):
    """Summarize one tenant's usage records for one yyyymm period.

    Returns a dict with calls, billable minutes (the minutes stored on
    the records, which the tenancy meter already rounds up per call),
    overage minutes against the plan limit, and the estimated cost in
    CAD cents.
    """
    selected = [
        r for r in records
        if _field(r, "tenant_id", None) == tenant_id and _field(r, "period", "") == period
    ]
    minutes = sum(float(_field(r, "minutes")) for r in selected)
    calls = sum(int(_field(r, "calls")) for r in selected)
    tts = sum(int(_field(r, "tts_characters")) for r in selected)
    stt = sum(float(_field(r, "stt_seconds")) for r in selected)
    limit = PLAN_LIMITS_MINUTES.get(plan_tier) if plan_tier else None
    overage = max(0.0, minutes - limit) if limit is not None else 0.0
    return {
        "tenant_id": tenant_id,
        "period": period,
        "plan": plan_tier,
        "plan_limit_minutes": limit,
        "calls": calls,
        "minutes": minutes,
        "overage_minutes": overage,
        "tts_characters": tts,
        "stt_seconds": stt,
        "estimated_cost_cents": estimate_cost_cents(
            minutes=minutes, calls=calls, tts_characters=tts,
            stt_seconds=stt, rates=rates),
        "currency": "CAD",
    }


def _fmt_minutes(value):
    if float(value) == int(value):
        return str(int(value))
    return f"{value:.1f}"


def summary_to_text(summary, business_name=""):
    """Plain text rendering of a monthly summary, suitable for email."""
    name = business_name or summary["tenant_id"]
    lines = [
        f"ApexVoice monthly usage summary for {name}",
        f"Period: {summary['period']}",
        "",
        f"Plan: {summary['plan'] or 'not recorded'}",
        f"Calls: {summary['calls']}",
        f"Minutes used: {_fmt_minutes(summary['minutes'])}",
    ]
    if summary["plan_limit_minutes"] is not None:
        lines.append(f"Included minutes: {summary['plan_limit_minutes']}")
        lines.append(f"Overage minutes: {_fmt_minutes(summary['overage_minutes'])}")
    else:
        lines.append("Included minutes: custom plan, no fixed limit recorded")
        lines.append("Overage minutes: 0")
    dollars = summary["estimated_cost_cents"] / 100.0
    lines += [
        f"Estimated operating cost: ${dollars:.2f} CAD",
        "",
        "The cost figure is an estimate from the ApexVoice pricing model, "
        "not an invoice. Your subscription charges are the plan price plus "
        "any overage minutes at your plan rate.",
    ]
    return "\n".join(lines)
