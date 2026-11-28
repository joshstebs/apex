"""Identifier generation and phone number normalization.

Tenant IDs use the prefix ten_ followed by urlsafe random text. Generation
is collision checked against the store so an ID is never reused.
Phone numbers are normalized to E.164 and validated before they are used
as routing keys.
"""

import re
import secrets

from .errors import ValidationFailed

TENANT_ID_PREFIX = "ten_"
_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def generate_tenant_id(store=None, length=16):
    """Return a new ten_ prefixed tenant ID, checked against the store.

    Pass a store exposing get_tenant(tenant_id) to guarantee uniqueness.
    Without a store the random space (36^16) makes collisions negligible,
    but production callers should always pass the store.
    """
    for _ in range(100):
        suffix = "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))
        candidate = TENANT_ID_PREFIX + suffix
        if store is None or store.get_tenant(candidate) is None:
            return candidate
    raise RuntimeError("could not generate a unique tenant id")


def generate_prefixed_id(prefix, length=20):
    """Return an opaque prefixed ID such as call_, msg_, user_, sess_."""
    suffix = "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))
    return prefix + suffix


def normalize_phone(raw):
    """Normalize a phone number to E.164, or raise ValidationFailed.

    Accepts common North American input: bare 10 digits, a leading 1,
    punctuation, spaces, and an existing leading plus. Numbers outside
    the North American plan must already be supplied in E.164 form.
    """
    if raw is None:
        raise ValidationFailed("phone number is required", fields={"phone": "required"})
    text = str(raw).strip()
    if not text:
        raise ValidationFailed("phone number is required", fields={"phone": "required"})
    has_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if has_plus:
        candidate = "+" + digits
    elif len(digits) == 10:
        candidate = "+1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        candidate = "+" + digits
    else:
        candidate = "+" + digits if digits else ""
    if not _E164_RE.match(candidate):
        raise ValidationFailed(
            "phone number must be a valid E.164 number",
            fields={"phone": "invalid_e164"},
        )
    return candidate


def is_valid_e164(value):
    return isinstance(value, str) and bool(_E164_RE.match(value))
