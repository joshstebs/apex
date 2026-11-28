"""Per tenant usage accounting and reconciliation for ApexVoice billing.

Rounding rule, stated once and applied everywhere: minutes are rounded up
per call, matching telephony practice. A 61 second call bills as 2 minutes,
a 60 second call as 1 minute, and a 1 second call as 1 minute. Period totals
are sums of per call rounded minutes, never a rounding of the raw total, so
local accounting and the meter report always agree.

Nothing in this module sends anything. The meter report is a payload dict
shaped for Stripe Billing Meters with a summarize aggregation, ready for a
backend route to submit later.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Union

from .tiers import Tier, get_tier

METER_EVENT_NAME = "apexvoice_overage_minutes"
DEFAULT_DRIFT_THRESHOLD_MINUTES = 5


@dataclass(frozen=True)
class CallUsage:
    """One call's usage. Provide duration_seconds, or minutes as a fallback."""

    tenant_id: str
    duration_seconds: Optional[float] = None
    minutes: Optional[float] = None
    call_id: Optional[str] = None

    def billable_minutes(self) -> int:
        if self.duration_seconds is not None:
            if self.duration_seconds <= 0:
                return 0
            return int(math.ceil(self.duration_seconds / 60))
        if self.minutes is not None:
            if self.minutes <= 0:
                return 0
            return int(math.ceil(self.minutes))
        return 0


UsageInput = Union[CallUsage, Dict[str, Any]]


def _coerce(record: UsageInput) -> CallUsage:
    if isinstance(record, CallUsage):
        return record
    if isinstance(record, dict):
        return CallUsage(
            tenant_id=str(record.get("tenant_id", "")),
            duration_seconds=record.get("duration_seconds"),
            minutes=record.get("minutes"),
            call_id=record.get("call_id"),
        )
    raise TypeError(f"Unsupported usage record: {type(record)!r}")


@dataclass
class UsageSummary:
    tenant_id: str
    tier_id: str
    total_minutes: int
    included_minutes: Optional[int]
    included_consumed: Optional[int]
    overage_minutes: Optional[int]
    overage_amount_cad_cents: Optional[int]
    call_count: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "tier_id": self.tier_id,
            "total_minutes": self.total_minutes,
            "included_minutes": self.included_minutes,
            "included_consumed": self.included_consumed,
            "overage_minutes": self.overage_minutes,
            "overage_amount_cad_cents": self.overage_amount_cad_cents,
            "call_count": self.call_count,
        }


def summarize_usage(
    tenant_id: str,
    tier_id: str,
    records: Iterable[UsageInput],
) -> UsageSummary:
    """Total one tenant's period usage and price the overage.

    Records belonging to other tenants are ignored, so a mixed export can be
    passed safely and one tenant can never be billed for another's minutes.
    Enterprise is custom priced, so its overage fields are None rather than
    a guessed number.
    """
    if not tenant_id.startswith("ten_"):
        raise ValueError("tenant_id must start with 'ten_'.")
    tier: Tier = get_tier(tier_id)
    total = 0
    count = 0
    for raw in records:
        record = _coerce(raw)
        if record.tenant_id != tenant_id:
            continue
        total += record.billable_minutes()
        count += 1
    if tier.custom or tier.included_minutes is None or tier.overage_cad_cents_per_minute is None:
        return UsageSummary(
            tenant_id=tenant_id,
            tier_id=tier.id,
            total_minutes=total,
            included_minutes=tier.included_minutes,
            included_consumed=None,
            overage_minutes=None,
            overage_amount_cad_cents=None,
            call_count=count,
        )
    included_consumed = min(total, tier.included_minutes)
    overage = max(0, total - tier.included_minutes)
    return UsageSummary(
        tenant_id=tenant_id,
        tier_id=tier.id,
        total_minutes=total,
        included_minutes=tier.included_minutes,
        included_consumed=included_consumed,
        overage_minutes=overage,
        overage_amount_cad_cents=overage * tier.overage_cad_cents_per_minute,
        call_count=count,
    )


def meter_report_payload(
    summary: UsageSummary,
    timestamp: int,
    stripe_customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Stripe Billing Meter event payload for the overage minutes.

    Shaped for a meter configured with summarize aggregation: one event per
    tenant per period carrying the period overage total, not one event per
    call. Payload only. Nothing is transmitted by this module.
    """
    if summary.overage_minutes is None:
        raise ValueError(
            "Custom tiers have no metered overage rate. "
            "Bill enterprise overage from the contract, not the meter."
        )
    payload: Dict[str, Any] = {
        "event_name": METER_EVENT_NAME,
        "action": "summarize",
        "timestamp": int(timestamp),
        "value": str(summary.overage_minutes),
        "payload": {
            "tenant_id": summary.tenant_id,
            "tier_id": summary.tier_id,
            "total_minutes": str(summary.total_minutes),
            "included_minutes": str(summary.included_minutes),
            "overage_minutes": str(summary.overage_minutes),
        },
    }
    if stripe_customer_id:
        payload["identifier"] = f"{summary.tenant_id}:{int(timestamp)}"
        payload["payload"]["stripe_customer_id"] = stripe_customer_id
    return payload


@dataclass
class ReconciliationResult:
    tenant_id: str
    local_minutes: int
    reported_minutes: int
    drift_minutes: int
    threshold_minutes: int
    drift_exceeded: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "local_minutes": self.local_minutes,
            "reported_minutes": self.reported_minutes,
            "drift_minutes": self.drift_minutes,
            "threshold_minutes": self.threshold_minutes,
            "drift_exceeded": self.drift_exceeded,
        }


def reconcile_usage(
    tenant_id: str,
    local_minutes: int,
    reported_minutes: int,
    threshold_minutes: int = DEFAULT_DRIFT_THRESHOLD_MINUTES,
) -> ReconciliationResult:
    """Compare locally metered minutes against what was reported to Stripe.

    Drift is the absolute difference. Drift strictly greater than the
    threshold is flagged for a human to investigate before the invoice is
    trusted. Drift at exactly the threshold is not flagged.
    """
    drift = abs(int(local_minutes) - int(reported_minutes))
    return ReconciliationResult(
        tenant_id=tenant_id,
        local_minutes=int(local_minutes),
        reported_minutes=int(reported_minutes),
        drift_minutes=drift,
        threshold_minutes=int(threshold_minutes),
        drift_exceeded=drift > int(threshold_minutes),
    )
