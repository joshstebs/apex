"""Data models for the ApexVoice tenancy layer.

Every tenant-owned record carries tenant_id. TenantConfig wraps the frozen
BusinessConfig document from docs/commercial/BACKEND_CONTRACTS.md and
validates it on construction, so an invalid configuration can never be
stored through this layer.
"""

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from .errors import ValidationFailed
from .ids import is_valid_e164

TENANT_STATUSES = ("trial", "active", "past_due", "suspended", "deleted")
ROLES = ("owner", "admin", "staff", "viewer")
INDUSTRIES = (
    "plumbing_hvac", "auto_repair", "dental_medical", "real_estate",
    "salon_barbershop", "restaurant", "professional_services",
    "general_small_business",
)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
PLAN_TIERS = ("starter", "professional", "business", "enterprise")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_time(value):
    return isinstance(value, str) and bool(_TIME_RE.match(value))


def validate_business_config(config):
    """Validate a BusinessConfig dict against the frozen contract schema.

    Returns a dict of dotted field path to problem description. An empty
    dict means the document is valid.
    """
    fields = {}
    if not isinstance(config, dict):
        return {"config": "must be an object"}

    name = config.get("businessName")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 120):
        fields["businessName"] = "required, 1 to 120 characters"

    contact = config.get("contact")
    if not isinstance(contact, dict):
        fields["contact"] = "required object"
    else:
        email = contact.get("email")
        if not isinstance(email, str) or not _EMAIL_RE.match(email):
            fields["contact.email"] = "a valid email address is required"
        phone = contact.get("phone")
        if not is_valid_e164(phone):
            fields["contact.phone"] = "an E.164 phone number is required"

    hours = config.get("hours")
    if not isinstance(hours, dict):
        fields["hours"] = "required object with the seven weekday keys"
    else:
        for day in WEEKDAYS:
            entry = hours.get(day)
            if not isinstance(entry, dict):
                fields[f"hours.{day}"] = "required"
                continue
            if entry.get("closed"):
                continue
            open_t, close_t = entry.get("open"), entry.get("close")
            if not _is_time(open_t) or not _is_time(close_t):
                fields[f"hours.{day}.open"] = "open and close in HH:MM are required when not closed"
            elif open_t >= close_t:
                fields[f"hours.{day}.open"] = "opening time must be earlier than closing time"

    holidays = config.get("holidays", [])
    if not isinstance(holidays, list):
        fields["holidays"] = "must be an array"
    else:
        for i, item in enumerate(holidays):
            if not isinstance(item, dict) or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(item.get("date", ""))):
                fields[f"holidays.{i}.date"] = "date in YYYY-MM-DD is required"
            elif not item.get("name"):
                fields[f"holidays.{i}.name"] = "name is required"

    rec_name = config.get("receptionistName")
    if not isinstance(rec_name, str) or not (1 <= len(rec_name.strip()) <= 40):
        fields["receptionistName"] = "required, 1 to 40 characters"

    greeting = config.get("greeting")
    if not isinstance(greeting, str) or not (10 <= len(greeting) <= 600):
        fields["greeting"] = "required, 10 to 600 characters"

    services = config.get("services", [])
    if not isinstance(services, list) or len(services) > 50:
        fields["services"] = "must be an array of at most 50 items"
    else:
        for i, item in enumerate(services):
            if not isinstance(item, dict) or not item.get("name"):
                fields[f"services.{i}.name"] = "name is required"

    faqs = config.get("faqs", [])
    if not isinstance(faqs, list) or len(faqs) > 100:
        fields["faqs"] = "must be an array of at most 100 items"
    else:
        for i, item in enumerate(faqs):
            if not isinstance(item, dict) or not item.get("q") or not item.get("a"):
                fields[f"faqs.{i}"] = "each faq needs a non-empty q and a"

    booking = config.get("bookingPrefs")
    if not isinstance(booking, dict):
        fields["bookingPrefs"] = "required object"
    else:
        if booking.get("mode", "request_only") != "request_only":
            fields["bookingPrefs.mode"] = "only request_only is available in the first release"
        if booking.get("confirmationMethod", "callback") not in ("callback", "email", "sms"):
            fields["bookingPrefs.confirmationMethod"] = "must be callback, email, or sms"
        for key in ("leadTimeHours", "slotLengthMinutes", "bufferMinutes", "maxAdvanceDays"):
            if key in booking and (not isinstance(booking[key], int) or booking[key] < 0):
                fields[f"bookingPrefs.{key}"] = "must be a non-negative integer"

    transfer = config.get("transferRules")
    if not isinstance(transfer, dict):
        fields["transferRules"] = "required object"
    else:
        attempts = transfer.get("maxAttempts", 2)
        if not isinstance(attempts, int) or not (1 <= attempts <= 3):
            fields["transferRules.maxAttempts"] = "must be an integer from 1 to 3"
        if transfer.get("fallback", "take_message") not in ("take_message", "voicemail_prompt"):
            fields["transferRules.fallback"] = "must be take_message or voicemail_prompt"
        for i, number in enumerate(transfer.get("numbers", [])):
            if not isinstance(number, dict) or not is_valid_e164(number.get("phone")):
                fields[f"transferRules.numbers.{i}.phone"] = "an E.164 phone number is required"

    after = config.get("afterHours")
    if not isinstance(after, dict):
        fields["afterHours"] = "required object"
    else:
        behaviour = after.get("behaviour")
        if behaviour not in ("take_message", "take_message_and_offer_emergency_transfer", "transfer_only", "closed_message_only"):
            fields["afterHours.behaviour"] = "unsupported after-hours behaviour"
        if not after.get("greeting"):
            fields["afterHours.greeting"] = "an after-hours greeting is required"
        offers_transfer = after.get("emergencyTransferEnabled") or behaviour in (
            "take_message_and_offer_emergency_transfer", "transfer_only")
        if offers_transfer and not is_valid_e164(after.get("emergencyNumber")):
            fields["afterHours.emergencyNumber"] = "an E.164 emergency number is required when transfers are offered"

    delivery = config.get("messageDelivery")
    if not isinstance(delivery, dict):
        fields["messageDelivery"] = "required object"
    else:
        methods = delivery.get("methods")
        if not isinstance(methods, list) or not methods or not set(methods) <= {"email", "sms", "dashboard"}:
            fields["messageDelivery.methods"] = "a non-empty array drawn from email, sms, dashboard"
        else:
            if "email" in methods and not delivery.get("emailTo"):
                fields["messageDelivery.emailTo"] = "required when email delivery is enabled"
            if "sms" in methods and not delivery.get("smsTo"):
                fields["messageDelivery.smsTo"] = "required when sms delivery is enabled"

    voice = config.get("voice")
    if not isinstance(voice, dict):
        fields["voice"] = "required object"
    else:
        if not voice.get("voiceId"):
            fields["voice.voiceId"] = "required"
        if voice.get("speakingRate", "normal") not in ("slow", "normal", "fast"):
            fields["voice.speakingRate"] = "must be slow, normal, or fast"
        personality = voice.get("personality", "")
        if isinstance(personality, str) and len(personality) > 200:
            fields["voice.personality"] = "at most 200 characters"

    instructions = config.get("instructions", "")
    if not isinstance(instructions, str) or len(instructions) > 4000:
        fields["instructions"] = "must be a string of at most 4000 characters"

    if config.get("industry") not in INDUSTRIES:
        fields["industry"] = "must be one of the catalogue industries"

    timezone_name = config.get("timezone")
    if not isinstance(timezone_name, str) or "/" not in timezone_name and timezone_name != "UTC":
        fields["timezone"] = "an IANA timezone name is required"

    return fields


@dataclass
class Tenant:
    id: str
    legal_name: str
    display_name: str = ""
    status: str = "active"
    plan_tier: str = "starter"
    timezone: str = "America/Toronto"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def __post_init__(self):
        if not self.id.startswith("ten_"):
            raise ValidationFailed("tenant id must carry the ten_ prefix", fields={"id": "bad_prefix"})
        if self.status not in TENANT_STATUSES:
            raise ValidationFailed("unknown tenant status", fields={"status": "unknown"})
        if self.plan_tier not in PLAN_TIERS:
            raise ValidationFailed("unknown plan tier", fields={"plan_tier": "unknown"})
        if not self.display_name:
            self.display_name = self.legal_name

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class TenantConfig:
    """A tenant's BusinessConfig document plus optimistic-lock version."""

    tenant_id: str
    config: dict
    version: int = 1
    updated_at: str = field(default_factory=now_iso)
    updated_by: str = ""

    def __post_init__(self):
        problems = validate_business_config(self.config)
        if problems:
            raise ValidationFailed("business configuration is invalid", fields=problems)

    @property
    def business_name(self):
        return self.config.get("businessName", "")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class PhoneMapping:
    did: str
    tenant_id: str
    status: str = "active"
    provider: str = "signalwire"
    provider_number_id: str = ""
    created_at: str = field(default_factory=now_iso)

    def __post_init__(self):
        if not is_valid_e164(self.did):
            raise ValidationFailed("did must be E.164", fields={"did": "invalid_e164"})

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class User:
    id: str
    tenant_id: str
    email: str
    role: str
    password_salt: str = ""
    password_hash: str = ""
    password_iterations: int = 0
    status: str = "active"
    created_at: str = field(default_factory=now_iso)
    last_login_at: str = ""

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValidationFailed("unknown role", fields={"role": "unknown"})
        self.email = self.email.strip().lower()

    def public_dict(self):
        return {"id": self.id, "tenant_id": self.tenant_id, "email": self.email,
                "role": self.role, "status": self.status}

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class Session:
    id: str
    tenant_id: str
    user_id: str
    token_hash: str
    created_at_epoch: float = 0.0
    expires_at_epoch: float = 0.0
    revoked: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class _Record:
    id: str
    tenant_id: str
    created_at: str = field(default_factory=now_iso)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class CallRecord(_Record):
    from_number: str = ""
    to_number: str = ""
    status: str = "answered"
    direction: str = "inbound"
    duration_seconds: int = 0
    contact_name: str = ""
    summary: object = None
    appointment_id: object = None
    message_id: object = None


@dataclass
class MessageRecord(_Record):
    call_id: object = None
    caller_name: str = ""
    callback_number: str = ""
    reason: str = ""
    preferred_time: str = ""
    urgent: bool = False
    handled: bool = False


@dataclass
class AppointmentRecord(_Record):
    call_id: object = None
    contact_name: str = ""
    contact_phone: str = ""
    service_name: str = ""
    requested_start: str = ""
    requested_end: str = ""
    status: str = "requested"
    notes: str = ""


@dataclass
class TranscriptRecord(_Record):
    call_id: str = ""
    speaker: str = "caller"
    text: str = ""
    at_seconds: int = 0


@dataclass
class CustomerRecord(_Record):
    phone_number: str = ""
    display_name: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    notes: str = ""


@dataclass
class UsageRecord(_Record):
    call_id: object = None
    period: str = ""
    minutes: float = 0.0
    calls: int = 0
    tts_characters: int = 0
    stt_seconds: float = 0.0


RECORD_KINDS = {
    "calls": CallRecord,
    "messages": MessageRecord,
    "appointments": AppointmentRecord,
    "transcripts": TranscriptRecord,
    "customers": CustomerRecord,
    "usage": UsageRecord,
}
