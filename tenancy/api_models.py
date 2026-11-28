"""Pure request and response shaping for the tenant API contracts.

These functions contain no web framework dependency. The backend agent
maps routes to them one to one when integrating; the shapes here match
docs/commercial/BACKEND_CONTRACTS.md exactly, including the error body
{error: {code, message}} and cursor pagination {items, page}.
"""

from datetime import datetime, timezone

from .errors import ValidationFailed

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def error_body(code, message, fields=None, **extra):
    error = {"code": code, "message": message}
    if fields is not None:
        error["fields"] = fields
    error.update(extra)
    return {"error": error}


def error_body_from_exception(exc):
    fields = getattr(exc, "fields", None)
    return error_body(exc.code, exc.message, fields=fields)


def _encode_cursor(offset):
    return f"cur_{offset}"


def _decode_cursor(cursor):
    if cursor is None or cursor == "":
        return 0
    if isinstance(cursor, str) and cursor.startswith("cur_"):
        try:
            return int(cursor[4:])
        except ValueError:
            pass
    raise ValidationFailed("pagination cursor is not valid", fields={"cursor": "invalid"})


def paginate(items, limit=None, cursor=None):
    """Apply cursor pagination to an already ordered list.

    Returns (page_items, page_object). Ordering is the caller's job and
    must follow the contract: calls by startedAt descending, messages by
    receivedAt descending, appointments by requestedStart ascending.
    """
    if limit is None:
        limit = DEFAULT_LIMIT
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = _decode_cursor(cursor)
    total = len(items)
    page_items = items[offset:offset + limit]
    next_offset = offset + limit
    next_cursor = _encode_cursor(next_offset) if next_offset < total else None
    page = {"limit": limit, "nextCursor": next_cursor, "total": total}
    return page_items, page


def list_response(items, limit=None, cursor=None, shape=None):
    page_items, page = paginate(list(items), limit=limit, cursor=cursor)
    if shape is not None:
        page_items = [shape(item) for item in page_items]
    return {"items": page_items, "page": page}


def iso_from_epoch(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shape_tenant(tenant, phone_mappings=None):
    body = {
        "id": tenant.id,
        "displayName": tenant.display_name,
        "legalName": tenant.legal_name,
        "status": tenant.status,
        "timezone": tenant.timezone,
        "planId": tenant.plan_tier,
        "createdAt": tenant.created_at,
    }
    if phone_mappings is not None:
        body["phoneNumbers"] = [
            {
                "id": "num_" + "".join(ch for ch in mapping.did if ch.isdigit()),
                "phoneNumber": mapping.did,
                "status": mapping.status,
            }
            for mapping in phone_mappings
        ]
    return body


def shape_user(user):
    return {"id": user.id, "email": user.email, "role": user.role}


def login_response(token, session, user, tenant):
    return {
        "sessionToken": token,
        "expiresAt": iso_from_epoch(session.expires_at_epoch),
        "user": shape_user(user),
        "tenant": {
            "id": tenant.id,
            "displayName": tenant.display_name,
            "status": tenant.status,
        },
    }


def session_response(session, user, tenant):
    return {
        "user": shape_user(user),
        "tenant": {
            "id": tenant.id,
            "displayName": tenant.display_name,
            "status": tenant.status,
        },
        "role": user.role,
        "expiresAt": iso_from_epoch(session.expires_at_epoch),
    }


def shape_config_response(tenant_config, notices=None):
    return {
        "version": tenant_config.version,
        "updatedAt": tenant_config.updated_at,
        "updatedBy": tenant_config.updated_by,
        "config": tenant_config.config,
        "notices": notices or [],
    }


def config_save_response(tenant_config, notices=None):
    return {
        "version": tenant_config.version,
        "updatedAt": tenant_config.updated_at,
        "notices": notices or [],
    }


def greeting_notices(config):
    """Non-blocking save notices, per the contract: warn, never block,
    when a greeting lacks the AI or recording disclosure wording."""
    notices = []
    for field_name in ("greeting",):
        text = (config.get(field_name) or "").lower()
        if "recorded" not in text and "transcribed" not in text:
            notices.append({
                "field": field_name,
                "message": "Your greeting does not mention that calls may be recorded or transcribed. The recommended wording is available in onboarding.",
            })
        if "automated" not in text and "ai" not in text:
            notices.append({
                "field": field_name,
                "message": "Your greeting does not identify the assistant as automated. Callers should be told they are speaking with an AI assistant.",
            })
    return notices


def shape_call(call):
    return {
        "id": call.id,
        "startedAt": call.created_at,
        "direction": call.direction,
        "fromNumber": call.from_number,
        "toNumber": call.to_number,
        "status": call.status,
        "durationSeconds": call.duration_seconds,
        "contactName": call.contact_name,
        "summary": call.summary,
        "appointmentId": call.appointment_id,
        "messageId": call.message_id,
        "recordingUrl": None,
        "endedAt": getattr(call, "ended_at", None),
    }


def shape_call_detail(call, transcripts=None, recording=None):
    """Call detail body: the call plus its transcript turns and recording.

    Transcript records are tenant records in their own right; the adapter
    loads the ones whose call_id matches and passes them in. Recording is
    an explicit object: when the adapter has no recording information the
    body says so instead of implying one exists.
    """
    body = shape_call(call)
    turns = []
    for turn in transcripts or []:
        if getattr(turn, "call_id", None) != call.id:
            continue
        turns.append({
            "speaker": turn.speaker,
            "text": turn.text,
            "atSeconds": turn.at_seconds,
        })
    body["transcript"] = turns
    body["recording"] = recording if recording is not None else {
        "status": "unavailable", "url": None,
    }
    return body


def shape_message(message):
    return {
        "id": message.id,
        "callId": message.call_id,
        "receivedAt": message.created_at,
        "callerName": message.caller_name,
        "callbackNumber": message.callback_number,
        "reason": message.reason,
        "preferredTime": message.preferred_time,
        "urgent": message.urgent,
        "handled": message.handled,
        "delivery": list(getattr(message, "delivery", None) or []),
    }


def shape_appointment(appointment):
    return {
        "id": appointment.id,
        "callId": appointment.call_id,
        "createdAt": appointment.created_at,
        "contactName": appointment.contact_name,
        "contactPhone": appointment.contact_phone,
        "serviceName": appointment.service_name,
        "requestedStart": appointment.requested_start,
        "requestedEnd": appointment.requested_end,
        "status": appointment.status,
        "notes": appointment.notes,
    }


def shape_customer(customer):
    return {
        "id": customer.id,
        "phoneNumber": customer.phone_number,
        "displayName": customer.display_name,
        "firstSeenAt": customer.first_seen_at,
        "lastSeenAt": customer.last_seen_at,
        "notes": customer.notes,
    }


def shape_usage(summary, plan_tier, included_minutes, overage_rate_cents=35):
    used = int(summary["used_minutes"])
    overage = 0
    if included_minutes is not None:
        overage = max(0, used - int(included_minutes))
    period = summary["period"]
    year, month = int(period[:4]), int(period[4:6])
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {
        "tenantId": summary["tenant_id"],
        "period": period,
        "periodStart": f"{period[:4]}-{period[4:6]}-01T00:00:00Z",
        "periodEnd": f"{end_year:04d}-{end_month:02d}-01T00:00:00Z",
        "planId": plan_tier,
        "includedMinutes": included_minutes,
        "usedMinutes": used,
        "overageMinutes": overage,
        "callCount": summary["call_count"],
        "ttsCharacters": summary["tts_characters"],
        "sttSeconds": summary["stt_seconds"],
        "estimatedCost": {
            "amount_cents": summary["estimated_cost_cents"],
            "currency": summary["currency"],
            "basis": "estimated from recorded usage events",
        },
        "overageRate": {
            "amount_cents": overage_rate_cents,
            "currency": "CAD",
            "per": "minute",
        },
    }


def shape_subscription(record, portal_available=False):
    """Subscription body for GET /api/tenants/{id}/subscription.

    Accepts the billing package's SubscriptionRecord, or None for a
    tenant with no subscription, which the contract represents with
    status "none". Billing period bounds live in Stripe until the
    billing package stores them, so they are honest nulls here rather
    than invented dates.
    """
    if record is None:
        return {
            "status": "none",
            "planId": None,
            "currentPeriodStart": None,
            "currentPeriodEnd": None,
            "portalAvailable": bool(portal_available),
            "suspendRecommended": False,
        }
    state = getattr(record, "state", None)
    status = getattr(state, "value", state)
    grace = getattr(record, "grace_expires_at", None)
    return {
        "status": status,
        "planId": getattr(record, "tier_id", None),
        "stripeCustomerId": getattr(record, "stripe_customer_id", None),
        "stripeSubscriptionId": getattr(record, "stripe_subscription_id", None),
        "currentPeriodStart": None,
        "currentPeriodEnd": None,
        "graceExpiresAt": grace.isoformat() if grace is not None else None,
        "suspendRecommended": bool(getattr(record, "suspend_recommended", False)),
        "portalAvailable": bool(portal_available),
    }
