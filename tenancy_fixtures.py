"""Shared fixtures for the tenancy test suites.

Builds two fully independent tenants (A and B) with owners, configs,
phone mappings, and one record of every tenant-owned kind each, in any
store implementation.
"""

from tenancy import (
    AppointmentRecord, AuthService, CallRecord, CustomerRecord,
    InMemoryStore, MessageRecord, PhoneMapping, PlatformOperator, SQLiteStore,
    Tenant, TenantConfig, TranscriptRecord,
)

OPERATOR = PlatformOperator(operator_id="ops-test")
PASSWORD_A = "tenant-a-password-1"
PASSWORD_B = "tenant-b-password-2"
DID_A = "+15195550101"
DID_B = "+15195550102"


def valid_config(business_name, email, phone):
    return {
        "businessName": business_name,
        "contact": {"ownerName": "Owner", "email": email, "phone": phone,
                    "address": "", "website": ""},
        "hours": {
            day: ({"open": "09:00", "close": "17:00", "closed": False}
                  if day not in ("saturday", "sunday")
                  else {"open": None, "close": None, "closed": True})
            for day in ("monday", "tuesday", "wednesday", "thursday",
                        "friday", "saturday", "sunday")
        },
        "holidays": [],
        "receptionistName": "Harper",
        "greeting": (f"Thank you for calling {business_name}. This is Harper, "
                     "an automated assistant. Calls may be recorded and "
                     "transcribed to help us serve you. How can I help?"),
        "services": [{"name": "General service", "price": "", "description": ""}],
        "faqs": [{"q": "Where are you?", "a": "At our office."}],
        "bookingPrefs": {"enabled": True, "mode": "request_only",
                         "leadTimeHours": 2, "slotLengthMinutes": 60,
                         "bufferMinutes": 15, "maxAdvanceDays": 30,
                         "collectFields": ["name", "phone"],
                         "confirmationMethod": "callback", "notes": ""},
        "transferRules": {"enabled": False, "numbers": [],
                          "triggers": ["caller asks for a person"],
                          "maxAttempts": 2, "fallback": "take_message"},
        "afterHours": {"behaviour": "take_message",
                       "greeting": "We are closed. Please leave a message.",
                       "emergencyTransferEnabled": False,
                       "emergencyNumber": "", "expectedCallback": "next business day"},
        "messageDelivery": {"methods": ["email", "dashboard"], "emailTo": [email],
                            "smsTo": [], "urgentOnlySms": True,
                            "dailySummary": True, "dailySummaryTime": "08:00"},
        "voice": {"voiceId": "21m00Tcm4TlvDq8ikWAM", "personality": "warm",
                  "speakingRate": "normal", "language": "en-CA"},
        "instructions": "",
        "industry": "general_small_business",
        "timezone": "America/Toronto",
    }


def make_store(kind):
    if kind == "memory":
        return InMemoryStore()
    if kind == "sqlite":
        return SQLiteStore(":memory:")
    raise ValueError(kind)


STORE_KINDS = ("memory", "sqlite")


def build_two_tenants(store):
    """Create tenants A and B with owners, configs, DIDs, and records."""
    auth = AuthService(store)
    world = {"store": store, "auth": auth}
    for label, tenant_id, did, email, password, plan in (
        ("a", "ten_alpha", DID_A, "owner-a@example.com", PASSWORD_A, "starter"),
        ("b", "ten_beta", DID_B, "owner-b@example.com", PASSWORD_B, "professional"),
    ):
        tenant = Tenant(id=tenant_id, legal_name=f"Business {label.upper()} Inc.",
                        status="active", plan_tier=plan)
        store.create_tenant(tenant)
        owner = auth.create_user(tenant_id, email, password, "owner")
        config = valid_config(f"Business {label.upper()}", email, did)
        store.put_config(TenantConfig(tenant_id=tenant_id, config=config,
                                      version=1, updated_by=owner.id))
        store.add_phone_mapping(PhoneMapping(did=did, tenant_id=tenant_id))
        store.put_record("calls", CallRecord(
            id=f"call_{label}1", tenant_id=tenant_id,
            from_number="+15195550177", to_number=did, status="answered",
            duration_seconds=180, contact_name=f"Caller {label.upper()}",
            summary=f"Summary for {label}"))
        store.put_record("messages", MessageRecord(
            id=f"msg_{label}1", tenant_id=tenant_id, call_id=f"call_{label}1",
            caller_name=f"Caller {label.upper()}", callback_number="+15195550177",
            reason=f"Reason {label}", preferred_time="Morning"))
        store.put_record("appointments", AppointmentRecord(
            id=f"appt_{label}1", tenant_id=tenant_id, call_id=f"call_{label}1",
            contact_name=f"Caller {label.upper()}", contact_phone="+15195550177",
            service_name="General service",
            requested_start="2026-12-01T14:00:00Z",
            requested_end="2026-12-01T15:00:00Z", status="requested"))
        store.put_record("transcripts", TranscriptRecord(
            id=f"tr_{label}1", tenant_id=tenant_id, call_id=f"call_{label}1",
            speaker="caller", text=f"Secret words from tenant {label}", at_seconds=3))
        store.put_record("customers", CustomerRecord(
            id=f"cust_{label}1", tenant_id=tenant_id,
            phone_number="+15195550177", display_name=f"Caller {label.upper()}"))
        world[label] = {"tenant": tenant, "owner": owner, "did": did,
                        "email": email, "password": password, "config": config}
    return world
