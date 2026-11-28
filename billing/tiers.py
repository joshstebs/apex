"""Subscription tier definitions for ApexVoice.

Prices are recommendations only. They are not approved prices and nothing in
this module creates products, prices, or charges. Stripe identifiers are
placeholders that stay None until someone creates the matching objects in
the Stripe test dashboard by hand.

All money is Canadian dollars, stored as integer cents to avoid float drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Tier:
    id: str
    name: str
    monthly_price_cad_cents: int
    included_minutes: Optional[int]
    overage_cad_cents_per_minute: Optional[int]
    custom: bool = False
    # Filled in only after the objects exist in the Stripe test dashboard.
    price_id: Optional[str] = None
    overage_price_id: Optional[str] = None

    @property
    def monthly_price_cad(self) -> float:
        return self.monthly_price_cad_cents / 100


TIERS: Dict[str, Tier] = {
    "starter": Tier(
        id="starter",
        name="Starter",
        monthly_price_cad_cents=4900,
        included_minutes=120,
        overage_cad_cents_per_minute=40,
    ),
    "professional": Tier(
        id="professional",
        name="Professional",
        monthly_price_cad_cents=9900,
        included_minutes=350,
        overage_cad_cents_per_minute=35,
    ),
    "business": Tier(
        id="business",
        name="Business",
        monthly_price_cad_cents=19900,
        included_minutes=800,
        overage_cad_cents_per_minute=30,
    ),
    "enterprise": Tier(
        id="enterprise",
        name="Enterprise",
        # Custom pricing, from this floor. Included minutes and overage are
        # negotiated per contract, so they are deliberately unset.
        monthly_price_cad_cents=49900,
        included_minutes=None,
        overage_cad_cents_per_minute=None,
        custom=True,
    ),
}


def get_tier(tier_id: str) -> Tier:
    try:
        return TIERS[tier_id]
    except KeyError:
        raise ValueError(f"Unknown tier: {tier_id!r}") from None


def stripe_setup_checklist() -> List[str]:
    """What a person must create in the Stripe test dashboard, in order.

    Nothing here is created by code. Each item names the tier field that gets
    filled in once the test mode object exists.
    """
    items: List[str] = [
        "Confirm the Stripe account is in test mode before creating anything.",
        "Create one product per tier: ApexVoice Starter, ApexVoice Professional, "
        "ApexVoice Business, ApexVoice Enterprise.",
        "Create a billing meter for overage minutes (event name "
        "apexvoice_overage_minutes, aggregation summarize, value is minutes).",
        "Configure the customer billing portal in test mode: subscription "
        "update, cancellation, invoice history, and payment method update on.",
    ]
    for tier in TIERS.values():
        if tier.custom:
            items.append(
                f"Tier {tier.id}: no self serve price. Sales assisted only, "
                f"from ${tier.monthly_price_cad:.2f} CAD per month. Leave "
                "price_id and overage_price_id as None."
            )
            continue
        items.append(
            f"Tier {tier.id}: create a recurring monthly price of "
            f"${tier.monthly_price_cad:.2f} CAD on the {tier.name} product and "
            f"record it in tiers.TIERS[{tier.id!r}].price_id."
        )
        items.append(
            f"Tier {tier.id}: create a metered overage price at "
            f"${tier.overage_cad_cents_per_minute / 100:.2f} CAD per minute "
            f"linked to the overage meter and record it in "
            f"tiers.TIERS[{tier.id!r}].overage_price_id."
        )
    items.append(
        "Create a webhook endpoint for the backend billing route in test mode "
        "and store its signing secret under the STRIPE_WEBHOOK_SECRET "
        "environment variable name. Never paste the value into code or docs."
    )
    return items
