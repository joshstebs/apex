"""Pure request payload builders for Stripe billing.

These functions return plain dicts shaped like the Stripe API requests for a
Checkout Session, a Billing Portal Session, and a subscription update. They
contain no secrets, make no network calls, and send nothing. A backend route
owned by the backend agent is responsible for ever transmitting them, in
test mode, with a test key it loads itself.

Every payload carries the tenant id in metadata, and Checkout also sets it
as client_reference_id, so webhook events can be routed back to exactly one
tenant and cross checked against each other.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .tiers import get_tier

_PRICE_PLACEHOLDER = "PRICE_NOT_CREATED_IN_TEST_MODE"
_OVERAGE_PRICE_PLACEHOLDER = "OVERAGE_PRICE_NOT_CREATED_IN_TEST_MODE"


def _require_tenant(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.startswith("ten_"):
        raise ValueError("tenant_id must start with 'ten_'.")
    return tenant_id


def _require_url(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.startswith(("https://", "http://")):
        raise ValueError(f"{name} must be an absolute URL.")
    return value


def build_checkout_session_payload(
    tenant_id: str,
    tier_id: str,
    success_url: str,
    cancel_url: str,
    customer_email: Optional[str] = None,
    trial_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Checkout Session payload for a new self serve subscription."""
    _require_tenant(tenant_id)
    _require_url("success_url", success_url)
    _require_url("cancel_url", cancel_url)
    tier = get_tier(tier_id)
    if tier.custom:
        raise ValueError(
            "Enterprise is sales assisted. There is no self serve checkout payload."
        )
    line_items = [
        {
            "price": tier.price_id or _PRICE_PLACEHOLDER,
            "quantity": 1,
        },
        {
            # Metered overage price. Quantity is set by reported usage, not here.
            "price": tier.overage_price_id or _OVERAGE_PRICE_PLACEHOLDER,
        },
    ]
    subscription_data: Dict[str, Any] = {
        "metadata": {"tenant_id": tenant_id, "tier_id": tier.id},
    }
    if trial_days:
        subscription_data["trial_period_days"] = int(trial_days)
    payload: Dict[str, Any] = {
        "mode": "subscription",
        "line_items": line_items,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": tenant_id,
        "metadata": {"tenant_id": tenant_id, "tier_id": tier.id},
        "subscription_data": subscription_data,
        "billing_address_collection": "required",
        "tax_id_collection": {"enabled": True},
    }
    if customer_email:
        payload["customer_email"] = customer_email
    return payload


def build_billing_portal_payload(
    tenant_id: str,
    stripe_customer_id: str,
    return_url: str,
    configuration_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Billing Portal Session payload. The portal is configured in Stripe.

    Portal features such as plan change, cancellation, invoice history, and
    payment method update are enabled in the Stripe dashboard configuration,
    not in this payload. The configuration id is included only when the
    caller supplies the test mode configuration created there.
    """
    _require_tenant(tenant_id)
    _require_url("return_url", return_url)
    if not stripe_customer_id:
        raise ValueError("stripe_customer_id is required for a portal session.")
    payload: Dict[str, Any] = {
        "customer": stripe_customer_id,
        "return_url": return_url,
    }
    if configuration_id:
        payload["configuration"] = configuration_id
    return payload


def build_subscription_update_payload(
    tenant_id: str,
    subscription_item_id: str,
    new_tier_id: str,
    proration_behavior: str = "create_prorations",
) -> Dict[str, Any]:
    """Subscription update payload for an upgrade or a downgrade.

    proration_behavior is passed through as the proration flag: use
    create_prorations for immediate upgrades, always_invoice when finance
    wants the difference billed right away, or none for a change that takes
    effect cleanly at period end, which is the safer default for downgrades.
    The caller chooses. This builder only validates and shapes the payload.
    """
    _require_tenant(tenant_id)
    if proration_behavior not in ("create_prorations", "always_invoice", "none"):
        raise ValueError(f"Unsupported proration_behavior: {proration_behavior!r}")
    if not subscription_item_id:
        raise ValueError("subscription_item_id is required for a plan change.")
    tier = get_tier(new_tier_id)
    if tier.custom:
        raise ValueError("Enterprise plan changes are handled from the contract.")
    return {
        "items": [
            {
                "id": subscription_item_id,
                "price": tier.price_id or _PRICE_PLACEHOLDER,
            }
        ],
        "proration_behavior": proration_behavior,
        "metadata": {"tenant_id": tenant_id, "tier_id": tier.id},
    }
