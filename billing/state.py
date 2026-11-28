"""Per tenant subscription state machine for ApexVoice billing.

State is driven only by verified webhook events. Payment failure handling is
deliberately conservative:

- A first invoice.payment_failed moves the subscription to past_due and
  opens a grace period, in days. Service continues during grace.
- If grace expires with no successful payment, the record moves to unpaid
  and a suspension recommendation flag is set. The flag is advice for the
  tenancy lifecycle to act on. Nothing in this module suspends a tenant,
  places a call, or changes telephony on its own.
- An invoice.paid at any point before cancellation recovers the record to
  active and clears the failure bookkeeping.

All timestamps are passed in by the caller so behaviour is fully testable
and this module never reads a clock implicitly except as a default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from .webhooks import WebhookEvent

DEFAULT_GRACE_DAYS = 7


class SubscriptionState(str, Enum):
    NONE = "none"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    UNPAID = "unpaid"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"


class InvalidTransitionError(RuntimeError):
    """Raised when a state change is not in the allowed transition table."""


ALLOWED_TRANSITIONS = {
    SubscriptionState.NONE: {
        SubscriptionState.TRIALING,
        SubscriptionState.ACTIVE,
        SubscriptionState.INCOMPLETE,
        SubscriptionState.CANCELED,
    },
    SubscriptionState.INCOMPLETE: {
        SubscriptionState.TRIALING,
        SubscriptionState.ACTIVE,
        SubscriptionState.PAST_DUE,
        SubscriptionState.CANCELED,
    },
    SubscriptionState.TRIALING: {
        SubscriptionState.ACTIVE,
        SubscriptionState.PAST_DUE,
        SubscriptionState.UNPAID,
        SubscriptionState.CANCELED,
    },
    SubscriptionState.ACTIVE: {
        SubscriptionState.PAST_DUE,
        SubscriptionState.UNPAID,
        SubscriptionState.CANCELED,
    },
    SubscriptionState.PAST_DUE: {
        SubscriptionState.ACTIVE,
        SubscriptionState.UNPAID,
        SubscriptionState.CANCELED,
    },
    SubscriptionState.UNPAID: {
        SubscriptionState.ACTIVE,
        SubscriptionState.CANCELED,
    },
    # A canceled tenant may come back through a brand new checkout.
    SubscriptionState.CANCELED: {
        SubscriptionState.TRIALING,
        SubscriptionState.ACTIVE,
        SubscriptionState.INCOMPLETE,
    },
}

_STATUS_TO_STATE = {
    "trialing": SubscriptionState.TRIALING,
    "active": SubscriptionState.ACTIVE,
    "past_due": SubscriptionState.PAST_DUE,
    "unpaid": SubscriptionState.UNPAID,
    "canceled": SubscriptionState.CANCELED,
    "cancelled": SubscriptionState.CANCELED,
    "incomplete": SubscriptionState.INCOMPLETE,
    "incomplete_expired": SubscriptionState.CANCELED,
    "paused": SubscriptionState.PAST_DUE,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SubscriptionRecord:
    tenant_id: str
    state: SubscriptionState = SubscriptionState.NONE
    tier_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    grace_days: int = DEFAULT_GRACE_DAYS
    failure_count: int = 0
    past_due_since: Optional[datetime] = None
    last_event_id: Optional[str] = None
    last_finalized_invoice_id: Optional[str] = None
    suspend_recommended: bool = False
    history: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tenant_id.startswith("ten_"):
            raise ValueError("tenant_id must start with 'ten_'.")

    @property
    def grace_expires_at(self) -> Optional[datetime]:
        if self.past_due_since is None:
            return None
        return self.past_due_since + timedelta(days=self.grace_days)

    @property
    def service_continues(self) -> bool:
        """True while the tenant should keep receiving service."""
        if self.state in (
            SubscriptionState.TRIALING,
            SubscriptionState.ACTIVE,
            SubscriptionState.PAST_DUE,
        ):
            return True
        return False


def can_transition(current: SubscriptionState, target: SubscriptionState) -> bool:
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())


def transition(
    record: SubscriptionRecord,
    target: SubscriptionState,
    now: Optional[datetime] = None,
    reason: str = "",
) -> SubscriptionRecord:
    moment = now or _utcnow()
    if not can_transition(record.state, target):
        raise InvalidTransitionError(
            f"Transition {record.state.value} to {target.value} is not allowed "
            f"for tenant {record.tenant_id}."
        )
    previous = record.state
    record.state = target
    record.history.append(
        {"at": moment.isoformat(), "from": previous.value, "to": target.value, "reason": reason}
    )
    return record


def _mark_past_due(record: SubscriptionRecord, now: datetime, reason: str) -> None:
    if record.state == SubscriptionState.PAST_DUE:
        record.failure_count += 1
        record.history.append(
            {"at": now.isoformat(), "from": "past_due", "to": "past_due", "reason": reason}
        )
        return
    transition(record, SubscriptionState.PAST_DUE, now, reason)
    record.failure_count += 1
    if record.past_due_since is None:
        record.past_due_since = now
    record.suspend_recommended = False


def _recover(record: SubscriptionRecord, now: datetime, reason: str) -> None:
    if record.state != SubscriptionState.ACTIVE:
        transition(record, SubscriptionState.ACTIVE, now, reason)
    else:
        record.history.append(
            {"at": now.isoformat(), "from": "active", "to": "active", "reason": reason}
        )
    record.failure_count = 0
    record.past_due_since = None
    record.suspend_recommended = False


def evaluate_grace(
    record: SubscriptionRecord, now: Optional[datetime] = None
) -> SubscriptionRecord:
    """Move a past_due record past its grace period to unpaid.

    Sets suspend_recommended instead of taking any action itself. Safe to
    call on a schedule or before serving a request. A no-op in other states.
    """
    moment = now or _utcnow()
    if record.state != SubscriptionState.PAST_DUE:
        return record
    expires = record.grace_expires_at
    if expires is not None and moment >= expires:
        transition(record, SubscriptionState.UNPAID, moment, "grace period expired")
        record.suspend_recommended = True
    return record


def handle_event(
    record: SubscriptionRecord,
    event: WebhookEvent,
    now: Optional[datetime] = None,
) -> SubscriptionRecord:
    """Apply one verified webhook event to a tenant record.

    Unknown event types are recorded in history and otherwise ignored, so a
    new Stripe event never crashes billing. Duplicate delivery of the same
    event id is also a no-op beyond history, which keeps handlers idempotent
    for the transitions that matter.
    """
    moment = now or _utcnow()
    if event.id and event.id == record.last_event_id:
        record.history.append(
            {"at": moment.isoformat(), "from": record.state.value,
             "to": record.state.value, "reason": f"duplicate event {event.type} ignored"}
        )
        return record
    if event.id:
        record.last_event_id = event.id

    obj = event.object
    customer = obj.get("customer")
    if isinstance(customer, str) and customer:
        record.stripe_customer_id = customer
    subscription = obj.get("subscription")
    if isinstance(subscription, str) and subscription:
        record.stripe_subscription_id = subscription
    if event.type.startswith("customer.subscription.") and obj.get("id"):
        record.stripe_subscription_id = str(obj["id"])
    metadata = obj.get("metadata")
    if isinstance(metadata, dict) and metadata.get("tier_id"):
        record.tier_id = str(metadata["tier_id"])

    if event.type == "checkout.session.completed":
        target = _STATUS_TO_STATE.get(event.object_status or "", SubscriptionState.ACTIVE)
        if record.state in (SubscriptionState.NONE, SubscriptionState.INCOMPLETE, SubscriptionState.CANCELED):
            _recover(record, moment, "checkout.session.completed")
        elif record.state == SubscriptionState.TRIALING and target == SubscriptionState.ACTIVE:
            _recover(record, moment, "checkout.session.completed")
        else:
            record.history.append(
                {"at": moment.isoformat(), "from": record.state.value,
                 "to": record.state.value, "reason": "checkout.session.completed noted"}
            )
    elif event.type in ("customer.subscription.created", "customer.subscription.updated"):
        target = _STATUS_TO_STATE.get(event.object_status or "")
        if target is None:
            record.history.append(
                {"at": moment.isoformat(), "from": record.state.value,
                 "to": record.state.value, "reason": f"{event.type} with unknown status noted"}
            )
        elif target == SubscriptionState.PAST_DUE:
            _mark_past_due(record, moment, event.type)
        elif target == SubscriptionState.ACTIVE:
            _recover(record, moment, event.type)
        else:
            transition(record, target, moment, event.type)
            if target == SubscriptionState.CANCELED:
                record.suspend_recommended = False
    elif event.type == "customer.subscription.deleted":
        if record.state != SubscriptionState.CANCELED:
            transition(record, SubscriptionState.CANCELED, moment, event.type)
        record.past_due_since = None
    elif event.type == "invoice.paid":
        if record.state != SubscriptionState.CANCELED:
            _recover(record, moment, "invoice.paid")
    elif event.type == "invoice.payment_failed":
        if record.state in (
            SubscriptionState.ACTIVE,
            SubscriptionState.TRIALING,
            SubscriptionState.PAST_DUE,
            SubscriptionState.INCOMPLETE,
        ):
            _mark_past_due(record, moment, "invoice.payment_failed")
            # A further failure after grace has already run out ends grace.
            evaluate_grace(record, moment)
    elif event.type == "invoice.finalized":
        invoice_id = obj.get("id")
        if isinstance(invoice_id, str):
            record.last_finalized_invoice_id = invoice_id
        record.history.append(
            {"at": moment.isoformat(), "from": record.state.value,
             "to": record.state.value, "reason": "invoice.finalized noted, no state change"}
        )
    else:
        record.history.append(
            {"at": moment.isoformat(), "from": record.state.value,
             "to": record.state.value, "reason": f"unhandled event {event.type} noted"}
        )
    return record
