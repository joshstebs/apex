"""ApexVoice billing readiness package.

Test mode only preparation: tier definitions, webhook signature
verification, a per tenant subscription state machine, usage reconciliation,
and pure Stripe request payload builders. Nothing in this package makes a
network call, creates a charge, or activates live billing.
"""

from .config import BillingConfig, BillingModeError
from .payloads import (
    build_billing_portal_payload,
    build_checkout_session_payload,
    build_subscription_update_payload,
)
from .state import (
    SubscriptionRecord,
    SubscriptionState,
    evaluate_grace,
    handle_event,
)
from .tiers import TIERS, Tier, get_tier, stripe_setup_checklist
from .usage import (
    CallUsage,
    UsageSummary,
    meter_report_payload,
    reconcile_usage,
    summarize_usage,
)
from .webhooks import (
    WebhookEvent,
    WebhookVerificationError,
    parse_event,
    verify_and_parse,
    verify_signature,
)

__version__ = "0.1.0"

__all__ = [
    "BillingConfig",
    "BillingModeError",
    "TIERS",
    "Tier",
    "get_tier",
    "stripe_setup_checklist",
    "WebhookEvent",
    "WebhookVerificationError",
    "parse_event",
    "verify_and_parse",
    "verify_signature",
    "SubscriptionRecord",
    "SubscriptionState",
    "evaluate_grace",
    "handle_event",
    "CallUsage",
    "UsageSummary",
    "meter_report_payload",
    "reconcile_usage",
    "summarize_usage",
    "build_billing_portal_payload",
    "build_checkout_session_payload",
    "build_subscription_update_payload",
]
