"""Stripe webhook signature verification and event parsing.

Implemented with the standard library only, following Stripe's documented
scheme:

- The Stripe-Signature header looks like t=TIMESTAMP,v1=SIGNATURE and may
  carry several v1 values during signing secret rotation.
- The signed payload is the timestamp, a dot, and the raw request body.
- The expected signature is the hex HMAC SHA256 of that payload, keyed with
  the endpoint webhook secret.
- Timestamps older than the tolerance (300 seconds by default) are rejected
  to limit replay.
- Signature comparison is constant time.

No network calls are made here. The caller hands in the raw body bytes and
the header value exactly as received. Verification must run on the raw body,
never on a re-serialised JSON document.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TOLERANCE_SECONDS = 300

# Distinct machine readable error codes. Callers map these to HTTP responses
# and logs without exposing secret material.
ERR_MISSING_HEADER = "missing_signature_header"
ERR_MALFORMED_HEADER = "malformed_signature_header"
ERR_MISSING_TIMESTAMP = "missing_timestamp"
ERR_INVALID_TIMESTAMP = "invalid_timestamp"
ERR_MISSING_SIGNATURE = "missing_signature"
ERR_TIMESTAMP_OUT_OF_TOLERANCE = "timestamp_out_of_tolerance"
ERR_SIGNATURE_MISMATCH = "signature_mismatch"
ERR_MALFORMED_EVENT = "malformed_event"
ERR_MISSING_SECRET = "missing_webhook_secret"


class WebhookVerificationError(ValueError):
    """Verification or parsing failed. The code attribute says why."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def parse_signature_header(header: Optional[str]) -> Tuple[int, str, List[str]]:
    """Split a Stripe-Signature header into timestamp text, int, and v1 list."""
    if header is None or not str(header).strip():
        raise WebhookVerificationError(
            ERR_MISSING_HEADER, "Stripe-Signature header is missing."
        )
    timestamp_text: Optional[str] = None
    signatures: List[str] = []
    for part in str(header).split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise WebhookVerificationError(
                ERR_MALFORMED_HEADER,
                "Stripe-Signature header contains a segment without a key.",
            )
        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "t":
            timestamp_text = value
        elif key == "v1":
            if value:
                signatures.append(value)
        # Other schemes such as v0 are ignored, matching Stripe's guidance.
    if timestamp_text is None or timestamp_text == "":
        raise WebhookVerificationError(
            ERR_MISSING_TIMESTAMP, "Stripe-Signature header has no timestamp."
        )
    try:
        timestamp = int(timestamp_text)
    except ValueError:
        raise WebhookVerificationError(
            ERR_INVALID_TIMESTAMP, "Stripe-Signature timestamp is not an integer."
        ) from None
    if not signatures:
        raise WebhookVerificationError(
            ERR_MISSING_SIGNATURE, "Stripe-Signature header has no v1 signature."
        )
    return timestamp, timestamp_text, signatures


def expected_signature(raw_body: bytes, timestamp_text: str, secret: str) -> str:
    """Compute the expected hex HMAC SHA256 for a raw body."""
    signed_payload = timestamp_text.encode("utf-8") + b"." + raw_body
    return hmac.new(
        secret.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()


def verify_signature(
    raw_body: bytes,
    header: Optional[str],
    secret: Optional[str],
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: Optional[float] = None,
) -> bool:
    """Verify a webhook delivery. Returns True or raises with a distinct code.

    Any one matching v1 value is enough, which is what makes signing secret
    rotation work while both the old and new secret are briefly in play.
    """
    if not secret:
        raise WebhookVerificationError(
            ERR_MISSING_SECRET, "No webhook secret is configured."
        )
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    timestamp, timestamp_text, signatures = parse_signature_header(header)
    current = time.time() if now is None else now
    if tolerance_seconds is not None and abs(current - timestamp) > tolerance_seconds:
        raise WebhookVerificationError(
            ERR_TIMESTAMP_OUT_OF_TOLERANCE,
            "Webhook timestamp is outside the tolerance window.",
        )
    expected = expected_signature(raw_body, timestamp_text, secret)
    for candidate in signatures:
        if hmac.compare_digest(expected, candidate):
            return True
    raise WebhookVerificationError(
        ERR_SIGNATURE_MISMATCH, "Webhook signature does not match the body."
    )


@dataclass
class WebhookEvent:
    """A parsed Stripe event, narrowed to what ApexVoice acts on."""

    id: str
    type: str
    created: Optional[int] = None
    data: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def object(self) -> Dict[str, Any]:
        obj = self.data.get("object")
        return obj if isinstance(obj, dict) else {}

    @property
    def object_status(self) -> Optional[str]:
        status = self.object.get("status")
        return status if isinstance(status, str) else None

    @property
    def tenant_id(self) -> Optional[str]:
        """Tenant id from object metadata, falling back to client reference."""
        metadata = self.object.get("metadata")
        if isinstance(metadata, dict):
            tenant = metadata.get("tenant_id")
            if isinstance(tenant, str) and tenant:
                return tenant
        subscription_details = self.object.get("subscription_details")
        if isinstance(subscription_details, dict):
            meta = subscription_details.get("metadata")
            if isinstance(meta, dict):
                tenant = meta.get("tenant_id")
                if isinstance(tenant, str) and tenant:
                    return tenant
        reference = self.object.get("client_reference_id")
        if isinstance(reference, str) and reference:
            return reference
        return None


def parse_event(raw_body: bytes) -> WebhookEvent:
    """Parse a verified raw body into a WebhookEvent."""
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise WebhookVerificationError(
            ERR_MALFORMED_EVENT, "Webhook body is not valid JSON."
        ) from None
    if not isinstance(payload, dict):
        raise WebhookVerificationError(
            ERR_MALFORMED_EVENT, "Webhook body is not a JSON object."
        )
    event_id = payload.get("id")
    event_type = payload.get("type")
    if not isinstance(event_id, str) or not event_id:
        raise WebhookVerificationError(
            ERR_MALFORMED_EVENT, "Webhook event has no id."
        )
    if not isinstance(event_type, str) or not event_type:
        raise WebhookVerificationError(
            ERR_MALFORMED_EVENT, "Webhook event has no type."
        )
    data = payload.get("data")
    created = payload.get("created")
    return WebhookEvent(
        id=event_id,
        type=event_type,
        created=created if isinstance(created, int) else None,
        data=data if isinstance(data, dict) else {},
        raw=payload,
    )


def verify_and_parse(
    raw_body: bytes,
    header: Optional[str],
    secret: Optional[str],
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: Optional[float] = None,
) -> WebhookEvent:
    """Verify first, parse second. The only order callers should use."""
    verify_signature(raw_body, header, secret, tolerance_seconds, now)
    return parse_event(raw_body)
