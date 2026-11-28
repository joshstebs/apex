"""Per-tenant usage metering, plan limits, and spend estimates.

Usage is recorded as tenant-owned usage records in the store, so one
tenant's usage is structurally incapable of appearing in another tenant's
totals. Monthly periods use yyyymm keys matching the Redis account key
pattern apex:t:{tenant_id}:acct:{yyyymm}.

Billable minutes follow the contract assumption: each call's minutes are
rounded up to the next whole minute.
"""

import math
from datetime import datetime, timezone

from .errors import PlanLimitReached
from .ids import generate_prefixed_id
from .models import UsageRecord

PLAN_LIMITS_MINUTES = {
    "starter": 120,
    "professional": 350,
    "business": 800,
    "enterprise": None,
}

# Default estimated rates in CAD cents. These are planning estimates from
# the commercial pricing model, not invoice-verified charges. Callers can
# pass their own rates dict.
DEFAULT_RATES_CAD_CENTS = {
    "per_minute": 13.5,
    "per_tts_1000_characters": 10.4,
    "per_stt_minute": 0.0,
    "per_call": 0.0,
}


def current_period(at=None):
    moment = at or datetime.now(timezone.utc)
    return moment.strftime("%Y%m")


class UsageMeter:
    def __init__(self, store, rates=None):
        self.store = store
        self.rates = dict(DEFAULT_RATES_CAD_CENTS)
        if rates:
            self.rates.update(rates)

    def record(self, tenant_id, minutes=0.0, calls=0, tts_characters=0,
               stt_seconds=0.0, call_id=None, period=None, billable=False):
        """Record one usage event for a tenant.

        minutes is the raw call duration in minutes. When billable is
        true, minutes are first rounded up per call to whole minutes.
        """
        raw_minutes = float(minutes)
        stored_minutes = float(math.ceil(raw_minutes)) if billable and raw_minutes > 0 else raw_minutes
        record = UsageRecord(
            id=generate_prefixed_id("use_"), tenant_id=tenant_id,
            call_id=call_id, period=period or current_period(),
            minutes=stored_minutes, calls=int(calls),
            tts_characters=int(tts_characters), stt_seconds=float(stt_seconds))
        return self.store.put_record("usage", record)

    def record_call(self, tenant_id, duration_seconds, tts_characters=0,
                    stt_seconds=0.0, call_id=None, period=None):
        return self.record(
            tenant_id, minutes=duration_seconds / 60.0, calls=1,
            tts_characters=tts_characters, stt_seconds=stt_seconds,
            call_id=call_id, period=period, billable=True)

    def summary(self, tenant_id, period=None):
        period = period or current_period()
        records = [r for r in self.store.list_records(tenant_id, "usage")
                   if r.period == period]
        minutes = sum(r.minutes for r in records)
        calls = sum(r.calls for r in records)
        tts = sum(r.tts_characters for r in records)
        stt = sum(r.stt_seconds for r in records)
        return {
            "tenant_id": tenant_id,
            "period": period,
            "used_minutes": minutes,
            "call_count": calls,
            "tts_characters": tts,
            "stt_seconds": stt,
            "estimated_cost_cents": self.estimate_cost_cents(
                minutes=minutes, calls=calls, tts_characters=tts, stt_seconds=stt),
            "currency": "CAD",
        }

    def estimate_cost_cents(self, minutes=0.0, calls=0, tts_characters=0, stt_seconds=0.0):
        cents = (
            minutes * self.rates["per_minute"]
            + calls * self.rates["per_call"]
            + (tts_characters / 1000.0) * self.rates["per_tts_1000_characters"]
            + (stt_seconds / 60.0) * self.rates["per_stt_minute"]
        )
        return int(round(cents))

    def plan_limit_minutes(self, tenant_id):
        tenant = self.store.get_tenant(tenant_id)
        if tenant is None:
            return None
        return PLAN_LIMITS_MINUTES.get(tenant.plan_tier)

    def remaining_minutes(self, tenant_id, period=None):
        limit = self.plan_limit_minutes(tenant_id)
        if limit is None:
            return None
        used = self.summary(tenant_id, period)["used_minutes"]
        return max(0.0, limit - used)

    def overage_minutes(self, tenant_id, period=None):
        limit = self.plan_limit_minutes(tenant_id)
        if limit is None:
            return 0.0
        used = self.summary(tenant_id, period)["used_minutes"]
        return max(0.0, used - limit)

    def is_hard_stopped(self, tenant_id, period=None):
        remaining = self.remaining_minutes(tenant_id, period)
        return remaining is not None and remaining <= 0

    def check_hard_stop(self, tenant_id, period=None):
        if self.is_hard_stopped(tenant_id, period):
            raise PlanLimitReached("this business has reached its included minutes")
        return True
