"""
ApexVoice AI: Vercel-Ready Autonomous Telephony Platform
- SignalWire Compatibility API (cXML/LaML) with X-SignalWire-Signature verification
- Opaque short-lived TTS clip IDs (/api/tts/clip/{clip_id}.mp3) with zero conversation text in URLs
- Atomic concurrency (MAX_CONCURRENT_CALLS=1) and budget ($5.00 USD) locks across Vercel instances
- Hugging Face Inference Router (router.huggingface.co/v1/chat/completions, meta-llama/Llama-3.1-8B-Instruct)
- ElevenLabs TTS (eleven_turbo_v2_5)
- Outbound calling completely disabled
- Secret-safe /api/health and /api/settings endpoints
"""
import os
import sqlite3
import sys
import re
import glob
import json
import uuid
import hmac
import math
import time
import urllib.parse
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from config import settings
from database import Database
from voice_engine import VoiceEngine
from telephony import TelephonyGateway

db = Database(settings.DB_PATH)
voice_engine = VoiceEngine()
telephony = TelephonyGateway()


def release_call_slot_safely(call_id: str, expected_total_cost: float) -> bool:
    """Reconcile a call's reservation exactly once, without leaking secrets or failing telephony.

    Failed reconciliation is logged with a truncated call identifier and leaves durable
    accounting/lock data intact so a retried completion callback can reconcile later.
    """
    safe_call_id = (call_id or "")[-8:]
    try:
        ok, err, _outcome = db.release_call_slot(call_id, cost_delta=expected_total_cost)
    except Exception as exc:  # accounting failures must not break call control responses
        print(f"[Apex] budget reconciliation deferred for call ...{safe_call_id}: {type(exc).__name__}")
        return False
    if not ok:
        print(f"[Apex] budget reconciliation deferred for call ...{safe_call_id}: {err}")
        db.note_ops_error("budget_reconciliation_deferred")
        return False
    return True

def seed_default_assistants():
    existing = db.list_assistants()
    if not existing:
        prompt_files = glob.glob(os.path.join(os.path.dirname(__file__), "prompts", "*.json"))
        for pfile in prompt_files:
            try:
                with open(pfile, "r") as f:
                    tpl = json.load(f)
                    db.create_or_update_assistant(tpl)
            except Exception as e:
                print(f"Error loading {pfile}: {e}")

seed_default_assistants()

def reconstruct_public_webhook_url(request_url_str: str, headers: Dict[str, str]) -> str:
    """Reconstructs the canonical public URL behind Vercel's edge proxy for signature verification."""
    norm = {k.lower(): v for k, v in (headers or {}).items()}
    proto = norm.get("x-forwarded-proto")
    host = norm.get("x-forwarded-host") or norm.get("host")
    if proto and host:
        parsed = urllib.parse.urlsplit(request_url_str)
        return urllib.parse.urlunsplit((proto.split(",")[0].strip(), host.split(",")[0].strip(), parsed.path, parsed.query, ""))
    return request_url_str

CLOSING_REQUESTS = {"goodbye", "bye", "that's all", "hang up", "thanks goodbye", "thank you goodbye"}


def is_closing_request(user_input: str) -> bool:
    """Match a whole closing phrase. Substrings such as a caller's name must not hang up."""
    normalized = re.sub(r"[^\w\s']", "", (user_input or "").casefold().replace("’", "'")).strip()
    return normalized in CLOSING_REQUESTS


def remember_caller_message(call_id: str) -> None:
    """Keep the caller's own words when the model never emitted a structured message.

    This is the voicemail path. Audio recording stays off; only the transcript is stored.
    """
    try:
        call = db.get_call(call_id)
        if not call:
            return
        extracted = dict(call.get("extracted_data") or {})
        existing = extracted.get("save_receptionist_message")
        if isinstance(existing, dict) and existing:
            return
        transcripts = db.get_call_transcripts(call_id)
        message = voicemail_from_transcripts(call, transcripts)
        if not message:
            return
        extracted["save_receptionist_message"] = message
        db.update_call(call_id, {
            "extracted_data": extracted,
            "outcome_status": "recorded_for_followup",
        })
    except (RuntimeError, OSError, sqlite3.Error, ValueError, TypeError):
        db.note_ops_error("voicemail_capture_failed")


def voicemail_from_transcripts(call: Dict[str, Any], transcripts: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Caller words to store when no structured tool message exists. No provider calls."""
    extracted = call.get("extracted_data") or {}
    existing = extracted.get("save_receptionist_message") if isinstance(extracted, dict) else None
    if isinstance(existing, dict) and existing:
        return None
    caller_lines = [
        str(entry.get("message", "")).strip()
        for entry in transcripts
        if entry.get("speaker") in ("human", "user") and str(entry.get("message", "")).strip()
    ]
    if not caller_lines:
        return None
    dynamic = call.get("dynamic_vars_applied") or {}
    caller_number = str(dynamic.get("caller_number") or "") if isinstance(dynamic, dict) else ""
    if not caller_number:
        caller_number = str(call.get("phone_number") or "")
    return {
        "caller_name": "",
        "callback_number": caller_number,
        "reason": " ".join(caller_lines)[:1000],
        "preferred_contact_time": "",
        "capture": "voicemail",
    }


def recovery_duration_seconds(call: Dict[str, Any], manual: bool = False) -> Optional[int]:
    """Seconds to bill when the carrier never sends a terminal callback.

    Automatic recovery waits until the hard cap plus the grace period.
    The estimate is the hard cap, or the last observed elapsed time when that is
    higher, and never more than the cap plus the grace period.
    """
    started_raw = str(call.get("started_at") or "")
    try:
        started = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    limit = settings.MAX_CALL_DURATION_SECONDS
    grace = settings.STALE_SETTLEMENT_GRACE_SECONDS
    if elapsed < (limit if manual else limit + grace):
        return None
    try:
        last_known = max(0, int(call.get("duration_seconds") or 0))
    except (TypeError, ValueError):
        last_known = 0
    return min(max(last_known, limit), limit + grace)


def apply_call_settlement(call_id: str, duration: int, source: str, carrier_status: Optional[str] = None) -> str:
    """Settle a reservation once. A later carrier callback adjusts a stale estimate."""
    if source not in ("carrier", "stale_estimate", "manual"):
        raise ValueError("Invalid settlement source")
    ceiling = settings.MAX_CALL_DURATION_SECONDS + settings.STALE_SETTLEMENT_GRACE_SECONDS
    if duration < 0 or (source != "carrier" and duration > ceiling) or duration > 86400:
        raise ValueError("Invalid settlement duration")
    if settings.STAGING and source != "carrier":
        # Live stale sweeps do not run against the zero staging budget.
        pass
    cost = VoiceEngine.calculate_call_cost(int(duration), provider="signalwire")
    ok, err, outcome = db.release_call_slot(call_id, cost["cost_total"], source=source)
    if not ok or not outcome:
        raise RuntimeError(err or "Call settlement unavailable")
    call = db.get_call(call_id)
    if outcome == "already_released" or not call:
        return outcome
    reservation = db.get_reservation(call_id) or {}
    authoritative = reservation.get("settlement_source") or source
    if source != "carrier" and authoritative == "carrier":
        return outcome
    status = carrier_status if authoritative == "carrier" else "stale_unsettled"
    if source == "carrier":
        status = carrier_status or "completed"
    db.update_call(call_id, {
        "status": status,
        "duration_seconds": int(duration),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "cost_telephony": cost["cost_telephony"],
        "cost_llm": cost["cost_llm"],
        "cost_tts": cost["cost_tts"],
        "cost_total": cost["cost_total"],
        "settlement_source": authoritative if authoritative == "carrier" else source,
        "outcome_status": "settled" if authoritative == "carrier" else "stale_unsettled",
    })
    if status == "stale_unsettled" and settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
        try:
            db._upstash_cmd(["ZADD", "apex:stale_calls", str(int(time.time())), call_id])
            db._upstash_cmd(["ZREMRANGEBYRANK", "apex:stale_calls", "0", "-51"])
            db._upstash_cmd(["EXPIRE", "apex:stale_calls", str(db.ACCOUNTING_TTL_SECONDS)])
        except Exception:
            db.note_ops_error("stale_index_unavailable")
    return outcome


def sweep_stale_reservations(manual_call_id: Optional[str] = None) -> List[Dict[str, str]]:
    """Settle hosted calls that outlived the carrier callback window. One charge each."""
    if not (settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN):
        return []
    call_ids: List[str] = []
    if manual_call_id:
        call_ids.append(manual_call_id)
    else:
        holder = db._upstash_cmd(["GET", db.ACTIVE_CALL_KEY])
        if isinstance(holder, str) and holder:
            call_ids.append(holder)
        recent = db._upstash_cmd(["ZREVRANGE", "apex:recent_calls", "0", "49"])
        if isinstance(recent, list):
            for item in recent:
                if isinstance(item, str) and item not in call_ids:
                    call_ids.append(item)
    report = []
    for call_id in call_ids:
        call = db.get_call(call_id)
        if not call or call.get("status") not in ("in-progress", "ending", "stale_unsettled"):
            continue
        duration = recovery_duration_seconds(call, manual=bool(manual_call_id))
        if duration is None:
            continue
        remember_caller_message(call_id)
        outcome = apply_call_settlement(call_id, duration, "manual" if manual_call_id else "stale_estimate")
        report.append({"call_id": call_id, "outcome": outcome, "duration_seconds": str(duration)})
    return report


def staging_cxml_block() -> Optional[str]:
    """Staging cannot admit or continue a live call. Returns cXML when blocked."""
    if not settings.STAGING:
        return None
    if not db.staging_request_allowed():
        db.note_ops_error("staging_rate_limited")
        return telephony.build_signalwire_cxml_hangup(
            "This staging line is rate limited and cannot accept calls. Goodbye."
        )
    return telephony.build_signalwire_cxml_hangup(
        "This staging line does not accept live calls. Goodbye."
    )


def build_conversation_history(transcripts: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    roles = {"assistant": "assistant", "human": "user", "user": "user"}
    conversation = [
        {"role": roles[entry["speaker"]], "content": entry["message"]}
        for entry in transcripts
        if entry["speaker"] in roles
    ]
    return conversation[-16:]


def create_voice_clip(spoken_text: str, voice_id: Optional[str]) -> Optional[str]:
    """Return a clip id only after audio is cached. Otherwise the carrier uses <Say>.

    A <Play> URL that later returns 503 leaves the caller in silence. Storage failure
    and synthesis failure both fall back before that URL is placed in the cXML.
    """
    if settings.use_carrier_speech() or not (voice_engine.elevenlabs_key or "").strip():
        return None
    voice = voice_id or settings.ELEVENLABS_DEFAULT_VOICE_ID
    try:
        clip_id = db.create_tts_clip(spoken_text, voice_id=voice)
    except (RuntimeError, sqlite3.Error):
        print("[Apex] TTS clip storage unavailable; falling back to carrier speech")
        db.note_ops_error("tts_storage_unavailable")
        return None
    try:
        audio = voice_engine.synthesize_speech_elevenlabs(spoken_text, voice_id=voice)
    except Exception:
        audio = None
    if not audio:
        print("[Apex] TTS synthesis failed; falling back to carrier speech")
        db.note_ops_error("tts_synthesis_failed")
        return None
    if not db.cache_tts_audio(clip_id, audio):
        print("[Apex] TTS audio cache unavailable; falling back to carrier speech")
        db.note_ops_error("tts_cache_unavailable")
        return None
    return clip_id


def handle_signalwire_inbound_or_connect(
    params: Dict[str, str],
    query_params: Dict[str, str]
) -> str:
    """
    Handles authenticated POST /webhooks/signalwire/voice for incoming calls to +1 226-773-0802.
    Acquires atomic concurrency & budget lock, stores greeting under an opaque short-lived clip_id,
    and returns SignalWire cXML.
    """
    blocked = staging_cxml_block()
    if blocked:
        return blocked
    call_id = (params.get("CallSid") or "").strip()
    if not call_id:
        if os.getenv("VERCEL"):
            return telephony.build_signalwire_cxml_hangup("Invalid call identifier. Goodbye.")
        call_id = f"call_{uuid.uuid4().hex[:12]}"
    from_number = params.get("From", "Unknown")
    # Only accept incoming calls for the number configured by the operator.
    # This prevents another DID in the same account from being unintentionally answered.
    dialed = params.get("To", "")
    if settings.REQUIRE_MATCHING_INBOUND_NUMBER and dialed != settings.SIGNALWIRE_PHONE_NUMBER:
        return telephony.build_signalwire_cxml_hangup(
            "This line is not configured for the automated receptionist. Goodbye."
        )
    if not settings.RECEPTIONIST_ENABLED:
        return telephony.build_signalwire_cxml_hangup(
            "The automated receptionist is not yet available. Please contact the business directly."
        )
    # Production calls must never proceed in an unconfigured text-only/silent demo.
    if os.getenv("VERCEL") and not (
        settings.CRON_SECRET and settings.get_webhook_signing_key()
        and settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN
        and settings.ELEVENLABS_API_KEY and settings.HUGGINGFACE_API_KEY
        and settings.PUBLIC_URL.startswith("https://")
    ):
        return telephony.build_signalwire_cxml_hangup(
            "The receptionist is temporarily unavailable. Please contact Harbour and Main directly."
        )
    assistant_id = settings.INBOUND_ASSISTANT_ID
    if settings.ALLOW_INBOUND_ASSISTANT_OVERRIDE and query_params.get("assistant_id"):
        assistant_id = query_params["assistant_id"]
    ast = db.get_assistant(assistant_id)
    if not ast:
        # Do not silently select an unrelated outbound assistant.
        return telephony.build_signalwire_cxml_hangup(
            "The receptionist is temporarily unavailable. Please contact the business directly."
        )

    greeting = VoiceEngine.render_prompt(
        ast["first_message"], {"business_name": settings.RECEPTIONIST_BUSINESS_NAME}
    )

    call_record = {
        "id": call_id,
        "assistant_id": ast["id"],
        "phone_number": from_number,
        "direction": "inbound",
        "provider": "signalwire",
        "status": "in-progress",
        "goal": "Answer incoming call",
        "dynamic_vars_applied": {"user_name": "Josh Stebs", "caller_number": from_number},
        "duration_seconds": 0,
        "started_at": datetime.utcnow().isoformat()
    }

    # Atomic admission is the single source of truth for retries and concurrency.
    try:
        admitted, _err_msg, outcome = db.try_acquire_call_slot(call_record)
    except RuntimeError:
        admitted, outcome = False, None
    if not admitted:
        if outcome == "duplicate":
            # A completed CallSid must never be re-admitted as a fresh billable call.
            return telephony.build_signalwire_cxml_hangup(
                "This call session has already ended. Goodbye."
            )
        return telephony.build_signalwire_cxml_hangup(
            "Sorry, this line is currently busy or has reached its usage limit. Please try again later."
        )

    replay = outcome == "replay"
    if not replay:
        db.add_transcript_message(call_id, "assistant", greeting, latency_ms=95)
    clip_id = create_voice_clip(greeting, ast.get("voice_id"))

    return telephony.build_signalwire_cxml_gather(
        call_id=call_id,
        assistant_id=ast["id"],
        spoken_text=greeting,
        clip_id=clip_id
    )

def end_from_gather(call_id: str, local_cost: float) -> None:
    remember_caller_message(call_id)
    if os.getenv("VERCEL"):
        # Hangup cXML is an instruction to the carrier. Keep the reservation in
        # place until the signed terminal callback reports the billed duration.
        db.mark_call_ending(call_id)
    else:
        db.update_call(call_id, {"status": "completed", "ended_at": datetime.now(timezone.utc).isoformat()})
        release_call_slot_safely(call_id, local_cost)


def handle_signalwire_gather_turn(
    params: Dict[str, str],
    query_params: Dict[str, str]
) -> str:
    """
    Handles authenticated POST /webhooks/signalwire/gather when caller speaks or presses digits.
    """
    blocked = staging_cxml_block()
    if blocked:
        return blocked
    call_id = params.get("CallSid", "")
    if not call_id or (query_params.get("call_id") and query_params["call_id"] != call_id):
        return telephony.build_signalwire_cxml_hangup("Invalid call session. Goodbye.")
    assistant_id = query_params.get("assistant_id", "")
    speech_result = params.get("SpeechResult", "").strip()
    digits = params.get("Digits", "").strip()
    user_input = speech_result or (f"Pressed {digits}" if digits else "")

    call = db.get_call(call_id) if call_id else None
    if not call:
        return telephony.build_signalwire_cxml_hangup("Thank you for calling. Goodbye!")
    if os.getenv("VERCEL"):
        if db._upstash_cmd(["EXISTS", db.CALL_PAUSE_KEY]):
            return telephony.build_signalwire_cxml_hangup("This line is temporarily unavailable. Goodbye.")
        holder = db._upstash_cmd(["GET", db.ACTIVE_CALL_KEY])
        if holder != call_id or call.get("status") != "in-progress":
            return telephony.build_signalwire_cxml_hangup("This call session has ended. Goodbye.")

    # Carrier termination and final settlement are handled independently of this turn.
    try:
        started = datetime.fromisoformat(call["started_at"].replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        new_duration = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    except (ValueError, KeyError, TypeError):
        return telephony.build_signalwire_cxml_hangup("Unable to verify call duration. Goodbye.")
    if new_duration >= settings.MAX_CALL_DURATION_SECONDS:
        cost_info = VoiceEngine.calculate_call_cost(settings.MAX_CALL_DURATION_SECONDS, provider="signalwire")
        end_from_gather(call_id, cost_info["cost_total"])
        return telephony.build_signalwire_cxml_hangup(
            f"We have reached our {settings.MAX_CALL_DURATION_SECONDS // 60} minute call time limit. Thank you and goodbye!"
        )

    if not user_input:
        end_from_gather(call_id, 0.0)
        return telephony.build_signalwire_cxml_hangup("I didn't hear anything. Goodbye!")

    ast = db.get_assistant(call.get("assistant_id") or assistant_id)
    if not ast:
        return telephony.build_signalwire_cxml_hangup(
            "The receptionist is temporarily unavailable. Please contact the business directly."
        )

    # Redis state is authoritative across Vercel instances.
    conv_history = build_conversation_history(db.get_call_transcripts(call_id))
    db.add_transcript_message(call_id, "human", user_input)

    dynamic_vars = {"business_name": settings.RECEPTIONIST_BUSINESS_NAME, **(call.get("dynamic_vars_applied") or {})}
    rendered_prompt = VoiceEngine.render_prompt(ast["system_prompt"], dynamic_vars)

    ai_result = voice_engine.generate_chat_response(
        system_prompt=rendered_prompt,
        conversation_history=conv_history,
        new_human_input=user_input,
        temperature=ast.get("temperature", 0.4),
        tools=ast.get("tools", [])
    )

    reply_text = ai_result["text"]
    detected_tool = ai_result.get("tool_call")
    db.add_transcript_message(call_id, "assistant", reply_text, latency_ms=ai_result["latency_ms"])

    extracted = call.get("extracted_data", {})
    if detected_tool:
        extracted[detected_tool.get("tool", "unnamed_tool")] = detected_tool.get("parameters", {})
        db.update_call(call_id, {"extracted_data": extracted, "outcome_status": "recorded_for_followup"})
        db.add_transcript_message(
            call_id, "tool", f"Details captured: {detected_tool.get('tool')} {json.dumps(detected_tool.get('parameters', {}))}"
        )

    cost_info = VoiceEngine.calculate_call_cost(new_duration, provider="signalwire")
    db.update_call(call_id, {
        "duration_seconds": new_duration,
        "cost_telephony": cost_info["cost_telephony"],
        "cost_llm": cost_info["cost_llm"],
        "cost_tts": cost_info["cost_tts"],
        "cost_total": cost_info["cost_total"]
    })

    clip_id = create_voice_clip(reply_text, ast.get("voice_id"))

    if is_closing_request(user_input):
        end_from_gather(call_id, cost_info["cost_total"])
        return telephony.build_signalwire_cxml_hangup(reply_text, clip_id=clip_id)

    return telephony.build_signalwire_cxml_gather(
        call_id=call_id,
        assistant_id=ast["id"],
        spoken_text=reply_text,
        clip_id=clip_id
    )

def get_sanitized_health_and_settings() -> Dict[str, Any]:
    """Returns strictly non-sensitive readiness flags and operational limits. Never exposes secrets."""
    report = {
        "status": "ok",
        "environment": settings.APEX_ENVIRONMENT,
        "staging": settings.STAGING,
        "telephony_provider": settings.TELEPHONY_PROVIDER,
        "inbound_live_calls_possible": settings.inbound_live_calls_possible(),
        "default_provider": settings.DEFAULT_TELEPHONY_PROVIDER,
        "signalwire_space_configured": bool(settings.SIGNALWIRE_SPACE_URL),
        "receptionist_provider_ready": bool(
            settings.SIGNALWIRE_PROJECT_ID
            and settings.SIGNALWIRE_API_TOKEN
            and settings.get_webhook_signing_key()
            and settings.UPSTASH_REDIS_REST_URL
            and settings.UPSTASH_REDIS_REST_TOKEN
            and settings.ELEVENLABS_API_KEY
            and settings.HUGGINGFACE_API_KEY
            and settings.PUBLIC_URL.startswith("https://")
        ),
        "signalwire_credentials_configured": bool(settings.SIGNALWIRE_PROJECT_ID and settings.SIGNALWIRE_API_TOKEN),
        "webhook_signature_enforced": settings.ENFORCE_WEBHOOK_SIGNATURE,
        "webhook_signing_key_configured": bool(settings.get_webhook_signing_key()),
        "elevenlabs_configured": bool(settings.ELEVENLABS_API_KEY),
        "elevenlabs_model_id": settings.ELEVENLABS_MODEL_ID,
        "huggingface_configured": bool(settings.HUGGINGFACE_API_KEY),
        "huggingface_router_endpoint": settings.HUGGINGFACE_ROUTER_URL,
        "huggingface_llm_model": settings.HUGGINGFACE_LLM_MODEL,
        "durable_storage_backend": settings.durable_storage_backend(),
        "durable_storage_configured": (
            settings.durable_storage_backend() == "upstash_redis" if os.getenv("VERCEL")
            else settings.durable_storage_backend() in ("upstash_redis", "turso_libsql")
        ),
        "max_concurrent_calls": settings.MAX_CONCURRENT_CALLS,
        "active_calls_count": None,
        "max_call_duration_seconds": settings.MAX_CALL_DURATION_SECONDS,
        "monthly_budget_limit_usd": settings.MONTHLY_BUDGET_LIMIT_USD,
        "current_monthly_spend_usd": None,
        "tts_clip_ttl_seconds": settings.TTS_CLIP_TTL_SECONDS,
        "outbound_calling_enabled": False,
        "receptionist_enabled": settings.RECEPTIONIST_ENABLED,
        "inbound_number_restricted": settings.REQUIRE_MATCHING_INBOUND_NUMBER,
        "configured_receptionist": settings.INBOUND_ASSISTANT_ID,
        "carrier_termination_configured": bool(
            settings.SIGNALWIRE_PROJECT_ID and settings.SIGNALWIRE_API_TOKEN
        ),
        "external_deadline_scheduler_configured": bool(settings.CRON_SECRET),
        "stale_settlement_grace_seconds": settings.STALE_SETTLEMENT_GRACE_SECONDS,
    }
    if settings.STAGING:
        configured = bool(settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN)
        report["redis_configured"] = configured
        report["redis_reachable"] = db.probe_redis() if configured else False
    return report


def summarize_call(call: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Dashboard call row. Omits phone numbers and any secret-like fields."""
    if not call:
        return None
    return {
        "id": call.get("id"),
        "status": call.get("status"),
        "direction": call.get("direction"),
        "provider": call.get("provider"),
        "started_at": call.get("started_at"),
        "ended_at": call.get("ended_at"),
        "duration_seconds": call.get("duration_seconds"),
        "outcome_status": call.get("outcome_status"),
        "cost_total": call.get("cost_total"),
        "settlement_source": call.get("settlement_source"),
    }


def sanitize_message(message: Any) -> Dict[str, Any]:
    if not isinstance(message, dict):
        return {}
    hidden = ("key", "token", "secret", "password", "authorization")
    return {
        str(key): value
        for key, value in message.items()
        if not any(part in str(key).lower() for part in hidden)
    }


def log_ops_failure(section: str, exc: BaseException) -> None:
    """Write a secret-free line to stderr so Vercel runtime logs show the failure."""
    text = str(exc).replace("\n", " ")[:300]
    print(f"[Apex] {section}: {type(exc).__name__}: {text}", file=sys.stderr, flush=True)


def redis_configured() -> bool:
    return bool(settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN)


def build_operations_dashboard() -> Dict[str, Any]:
    """Admin-only operations snapshot. Spend is the app estimate, not a carrier invoice."""
    reserve, reserve_error = db._call_reserve_usd()
    unavailable: List[str] = []
    notices: List[str] = []
    spend = None
    if os.getenv("VERCEL") and not redis_configured():
        notices.append(
            "Shared Redis is not configured. Spend, live calls, and message history stay empty "
            "until UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN are set."
        )
        unavailable.extend(["budget", "calls", "messages", "stale_unsettled"])
        return _dashboard_payload(
            reserve, reserve_error, spend, False, False, None, [], [], [], [], notices, unavailable
        )
    try:
        spend = db.get_monthly_spend()
    except (RuntimeError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
        log_ops_failure("dashboard budget", exc)
        unavailable.append("budget")
        notices.append("Spend could not be read. Shared Redis is required on Vercel.")
    paused = False
    scheduler = False
    live = None
    recent: List[Dict[str, Any]] = []
    try:
        if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
            paused = bool(db._upstash_cmd(["EXISTS", db.CALL_PAUSE_KEY]))
            scheduler = bool(db._upstash_cmd(["GET", db.SCHEDULER_KEY]))
            holder = db._upstash_cmd(["GET", db.ACTIVE_CALL_KEY])
            if isinstance(holder, str) and holder:
                live = summarize_call(db.get_call(holder)) or {"id": holder, "status": "unknown"}
        recent = [row for row in (summarize_call(call) for call in db.list_recent_calls()) if row]
    except (RuntimeError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
        log_ops_failure("dashboard calls", exc)
        unavailable.append("calls")
        notices.append("Recent calls are unavailable without shared Redis.")
    messages: List[Dict[str, Any]] = []
    try:
        for item in db.list_receptionist_messages():
            messages.append({
                "call_id": item.get("call_id"),
                "started_at": item.get("started_at"),
                "message": sanitize_message(item.get("message")),
            })
    except (RuntimeError, OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as exc:
        log_ops_failure("dashboard messages", exc)
        unavailable.append("messages")
        notices.append("Message history is unavailable without shared Redis.")
    try:
        errors = db.list_ops_errors()
    except (RuntimeError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
        log_ops_failure("dashboard errors", exc)
        errors = []
        unavailable.append("errors")
    stale_unsettled: List[Dict[str, Any]] = []
    try:
        stale_unsettled = [row for row in (summarize_call(call) for call in db.list_stale_calls()) if row]
    except (RuntimeError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
        log_ops_failure("dashboard stale", exc)
        unavailable.append("stale_unsettled")
    return _dashboard_payload(
        reserve, reserve_error, spend, paused, scheduler, live, recent, stale_unsettled,
        messages, errors, notices, unavailable,
    )


def _dashboard_payload(reserve, reserve_error, spend, paused, scheduler, live, recent, stale_unsettled, messages, errors, notices, unavailable) -> Dict[str, Any]:
    return {
        "environment": settings.APEX_ENVIRONMENT,
        "staging": settings.STAGING,
        "telephony_provider": settings.TELEPHONY_PROVIDER,
        "inbound_live_calls_possible": settings.inbound_live_calls_possible(),
        "outbound_calling_enabled": False,
        "receptionist_enabled": settings.RECEPTIONIST_ENABLED,
        "paused": paused,
        "scheduler_recently_seen": scheduler,
        "budget": {
            "spend_usd": spend,
            "cap_usd": settings.MONTHLY_BUDGET_LIMIT_USD,
            "reserve_usd": reserve,
            "reserve_configuration": "blocked" if reserve_error else "ok",
        },
        "live_call": live,
        "recent_calls": recent,
        "stale_unsettled": stale_unsettled,
        "messages": messages,
        "errors": errors,
        "notices": notices,
        "unavailable": unavailable,
    }

DRILL_SIGNING_KEY = "staging-drill-signing-key"


def _receptionist_template() -> Dict[str, Any]:
    path = os.path.join(os.path.dirname(__file__), "prompts", "harbour_main_receptionist.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _seed_drill_reservation(call_id: str, reserve: float = 1.0) -> None:
    month = datetime.utcnow().strftime("%Y-%m")
    accounting = {"call_id": call_id, "month": month, "reserve": reserve, "reconciled": False}
    raw = json.dumps(accounting)
    ttl = str(db.ACCOUNTING_TTL_SECONDS)
    db._upstash_cmd(["SET", f"apex:drill:acct:{call_id}", raw, "EX", ttl])
    db._upstash_cmd(["SET", f"apex:drill:lock:{call_id}", call_id])
    db._upstash_cmd(["SET", f"apex:drill:spend:{call_id}", str(reserve)])
    db._upstash_cmd(["SET", f"apex:drill:reserve:{call_id}", raw, "EX", ttl])


def _cleanup_drill(call_id: str) -> None:
    if not redis_configured():
        return
    for key in (
        f"apex:drill:acct:{call_id}",
        f"apex:drill:lock:{call_id}",
        f"apex:drill:spend:{call_id}",
        f"apex:drill:reserve:{call_id}",
        f"apex:drill:message:{call_id}",
        f"apex:settle:{call_id}",
    ):
        try:
            db._upstash_cmd(["DEL", key])
        except Exception:
            return


def run_staging_exercise() -> Dict[str, Any]:
    """Run the receptionist path in-process. Never calls SignalWire or ElevenLabs.

    Live webhooks stay refused. Settlement, when Redis is configured, uses only
    apex:drill:* keys so the live slot and monthly spend are untouched.
    """
    if not settings.STAGING:
        raise RuntimeError("Staging exercise refused")
    template = _receptionist_template()
    greeting = VoiceEngine.render_prompt(
        template.get("first_message") or "Hello.",
        {"business_name": settings.RECEPTIONIST_BUSINESS_NAME},
    )
    inbound_cxml = telephony.build_signalwire_cxml_gather(
        "drill-inbound", template.get("id") or "tpl_hm_receptionist", greeting, clip_id=None
    )
    model_text = (
        "I have the message for the team.\n```json\n"
        '{"tool":"save_receptionist_message","parameters":'
        '{"caller_name":"Sam","callback_number":"+15195550100",'
        '"reason":"Dock question","preferred_contact_time":"morning"}}\n```'
    )
    spoken, tool = voice_engine.parse_tool_response(model_text, template.get("tools") or [])
    history = build_conversation_history([
        {"speaker": "assistant", "message": greeting},
        {"speaker": "tool", "message": "Details captured: save_receptionist_message"},
        {"speaker": "human", "message": "This is Sam. Please call me about the dock."},
    ])
    voicemail = voicemail_from_transcripts(
        {
            "phone_number": "+15195550100",
            "dynamic_vars_applied": {"caller_number": "+15195550100"},
            "extracted_data": {},
        },
        [
            {"speaker": "assistant", "message": greeting},
            {"speaker": "human", "message": "The shipment is at the side door."},
            {"speaker": "human", "message": "Goodbye"},
        ],
    )
    call_id = "drill" + uuid.uuid4().hex[:16]
    status_params = {"CallSid": call_id, "CallStatus": "completed", "CallDuration": "30"}
    status_url = "https://staging.invalid/webhooks/signalwire/status"
    signature = telephony.compute_signalwire_laml_signature(DRILL_SIGNING_KEY, status_url, status_params)
    forged = signature[:-1] + ("A" if not signature.endswith("A") else "B")
    signature_valid = hmac.compare_digest(
        signature, telephony.compute_signalwire_laml_signature(DRILL_SIGNING_KEY, status_url, status_params)
    )
    forged_rejected = not hmac.compare_digest(forged, signature)
    tampered = dict(status_params, CallDuration="999")
    tampered_rejected = telephony.compute_signalwire_laml_signature(
        DRILL_SIGNING_KEY, status_url, tampered
    ) != signature
    live_block = staging_cxml_block() or ""
    configured = redis_configured()
    reachable = db.probe_redis() if configured else False
    message_round_trip = False
    settlement = "skipped"
    duplicate = "skipped"
    spend_unchanged = None
    steps_ok = True
    if configured and reachable and tool:
        try:
            _seed_drill_reservation(call_id, 1.0)
            encoded = json.dumps(tool["parameters"])
            db._upstash_cmd(["SET", f"apex:drill:message:{call_id}", encoded, "EX", "120"])
            echoed = json.loads(db._upstash_cmd(["GET", f"apex:drill:message:{call_id}"]))
            message_round_trip = echoed.get("caller_name") == "Sam"
            first_cost = VoiceEngine.calculate_call_cost(30, provider="signalwire")["cost_total"]
            ok, err, settlement = db.release_call_slot(call_id, first_cost, source="carrier", ledger="drill")
            if not ok:
                settlement = err or "failed"
                steps_ok = False
            spend_after = float(db._upstash_cmd(["GET", f"apex:drill:spend:{call_id}"]) or 0)
            second_cost = VoiceEngine.calculate_call_cost(90, provider="signalwire")["cost_total"]
            ok2, err2, duplicate = db.release_call_slot(call_id, second_cost, source="carrier", ledger="drill")
            if not ok2:
                duplicate = err2 or "failed"
                steps_ok = False
            spend_after_duplicate = float(db._upstash_cmd(["GET", f"apex:drill:spend:{call_id}"]) or 0)
            spend_unchanged = abs(spend_after - spend_after_duplicate) < 1e-6
            live_lock = db._upstash_cmd(["GET", db.ACTIVE_CALL_KEY])
            if live_lock:
                steps_ok = False
        finally:
            _cleanup_drill(call_id)
    elif configured and not reachable:
        settlement = "redis_unreachable"
        duplicate = "redis_unreachable"
        steps_ok = False
    summary = {
        "staging": True,
        "providers_contacted": False,
        "redis_configured": configured,
        "redis_reachable": reachable,
        "ok": bool(
            steps_ok and signature_valid and forged_rejected and tampered_rejected
            and tool and tool.get("tool") == "save_receptionist_message"
            and voicemail and voicemail.get("capture") == "voicemail"
            and "<Play" not in inbound_cxml and "<Say" in inbound_cxml
            and "does not accept live calls" in live_block
        ),
        "steps": [
            {"name": "redis_round_trip", "ok": (not configured) or reachable},
            {
                "name": "inbound",
                "ok": "<Play" not in inbound_cxml and "<Say" in inbound_cxml,
                "speech": "say",
                "played_audio": False,
            },
            {
                "name": "speech_turn",
                "ok": "```" not in spoken and bool(tool) and all(
                    "Details captured" not in turn["content"] for turn in history
                ),
                "spoken_text": spoken,
                "history_hides_tool_events": all("Details captured" not in turn["content"] for turn in history),
            },
            {
                "name": "message_capture",
                "ok": bool(tool) and tool.get("parameters", {}).get("caller_name") == "Sam",
                "tool": None if not tool else tool.get("tool"),
                "redis_round_trip": message_round_trip,
            },
            {
                "name": "voicemail",
                "ok": bool(voicemail) and voicemail.get("capture") == "voicemail" and "side door" in voicemail.get("reason", ""),
                "capture": None if not voicemail else voicemail.get("capture"),
            },
            {
                "name": "signed_status",
                "ok": signature_valid and forged_rejected and tampered_rejected,
                "signature_valid": signature_valid,
                "forged_rejected": forged_rejected,
                "settlement": settlement,
            },
            {
                "name": "duplicate_status",
                "ok": (not configured) or (duplicate == "already_released" and spend_unchanged is True),
                "settlement": duplicate,
                "spend_unchanged": spend_unchanged,
            },
            {"name": "live_admission_refused", "ok": "does not accept live calls" in live_block},
        ],
    }
    if not configured:
        summary["notice"] = "Redis is not configured, so the drill ledger was not written."
    return summary


# =========================================================================
# FASTAPI APPLICATION (VERCEL ASGI RUNTIME)
# =========================================================================
try:
    from fastapi import FastAPI, Request, HTTPException
    from starlette.concurrency import run_in_threadpool
    from fastapi.responses import HTMLResponse, JSONResponse, Response
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    app = FastAPI(
        title="ApexVoice AI Production Platform",
        description="SignalWire & ElevenLabs Autonomous Inbound Voice Agent on Vercel",
        version="1.2.0"
    )

    # No permissive CORS. Browser admin access is same-origin only.
    from fastapi import Depends
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    bearer = HTTPBearer(auto_error=False)

    def require_admin(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        token = os.getenv("APEX_ADMIN_TOKEN", "")
        if not token or not credentials or not hmac.compare_digest(credentials.credentials, token):
            raise HTTPException(status_code=401, detail="Administrator authentication required",
                                headers={"WWW-Authenticate": "Bearer"})

    @app.on_event("startup")
    def startup_event():
        seed_default_assistants()

    class AssistantPayload(BaseModel):
        id: Optional[str] = None
        name: str
        description: Optional[str] = ""
        category: Optional[str] = "custom"
        system_prompt: str
        first_message: str
        voice_provider: Optional[str] = "elevenlabs"
        voice_id: Optional[str] = "21m00Tcm4TlvDq8ikWAM"
        voice_settings: Optional[Dict[str, Any]] = {"stability": 0.5, "similarity_boost": 0.75}
        llm_provider: Optional[str] = "huggingface"
        llm_model: Optional[str] = "meta-llama/Llama-3.1-8B-Instruct"
        temperature: Optional[float] = 0.4
        dynamic_variables: Optional[List[str]] = []
        tools: Optional[List[Dict[str, Any]]] = []

    class CallDispatchPayload(BaseModel):
        assistant_id: str
        phone_number: str
        provider: Optional[str] = "simulator"
        goal: Optional[str] = ""
        dynamic_vars: Optional[Dict[str, Any]] = {}

    class SimulationTurnPayload(BaseModel):
        call_id: str
        user_message: str

    @app.get("/api/health")
    def health_check():
        return get_sanitized_health_and_settings()

    def require_operations(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        token = os.getenv("APEX_OPERATIONS_TOKEN", "")
        admin = os.getenv("APEX_ADMIN_TOKEN", "")
        if len(token) < 32 or token == admin or not credentials or not hmac.compare_digest(
            credentials.credentials.encode(), token.encode()
        ):
            raise HTTPException(status_code=401, detail="Operations authentication required")
        if not os.getenv("VERCEL") or settings.durable_storage_backend() != "upstash_redis":
            raise HTTPException(status_code=503, detail="Durable call control unavailable")

    @app.get("/api/operations", dependencies=[Depends(require_operations)])
    def operations_status(response: Response):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        try:
            paused, spend, scheduler_at = db._upstash_cmd([
                "MGET", db.CALL_PAUSE_KEY, f"apex:spend:{month}", db.SCHEDULER_KEY
            ])
            estimated = float(spend) if spend is not None else 0.0
            if not math.isfinite(estimated) or estimated < 0 or db._call_reserve_usd()[1]:
                raise ValueError("Invalid spend")
        except (RuntimeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Operations state unavailable") from exc
        flags = get_sanitized_health_and_settings()
        response.headers["Cache-Control"] = "no-store"
        return {
            "paused": paused is not None,
            "estimatedSpendUsd": estimated,
            "budgetUsd": flags["monthly_budget_limit_usd"],
            "schedulerRecentlySeen": bool(scheduler_at),
            "carrierBillingCapVerified": None
        }

    @app.post("/api/operations/pause", dependencies=[Depends(require_operations)])
    def pause_calls(response: Response):
        # Set the flag and capture the active slot atomically with respect to admission.
        try:
            call_id = db._upstash_cmd([
                "EVAL", "redis.call('SET', KEYS[1], '1'); return redis.call('GET', KEYS[2])",
                "2", db.CALL_PAUSE_KEY, db.ACTIVE_CALL_KEY
            ])
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Could not verify the pause") from exc
        carrier = "no_active_call"
        if call_id:
            try:
                carrier = "requested" if telephony.terminate_signalwire_call(call_id) else "unconfirmed"
            except (RuntimeError, ValueError, OSError):
                carrier = "unconfirmed"
        response.headers["Cache-Control"] = "no-store"
        return {"paused": True, "carrierTermination": carrier}

    @app.get("/api/settings")
    def get_settings():
        return get_sanitized_health_and_settings()

    @app.get("/api/assistants")
    def get_assistants(admin=Depends(require_admin)):
        return {"assistants": db.list_assistants()}

    @app.get("/api/assistants/{assistant_id}")
    def get_assistant(assistant_id: str, admin=Depends(require_admin)):
        ast = db.get_assistant(assistant_id)
        if not ast:
            raise HTTPException(status_code=404, detail="Assistant not found")
        return {"assistant": ast}

    @app.post("/api/assistants")
    def save_assistant(payload: AssistantPayload, admin=Depends(require_admin)):
        if os.getenv("VERCEL"):
            raise HTTPException(status_code=503, detail="This feature is disabled until durable support is implemented")
        data = payload.model_dump()
        if not data.get("id"):
            data["id"] = f"ast_{uuid.uuid4().hex[:10]}"
        aid = db.create_or_update_assistant(data)
        return {"success": True, "assistant_id": aid}

    @app.get("/api/templates")
    def get_templates(admin=Depends(require_admin)):
        prompt_files = glob.glob(os.path.join(os.path.dirname(__file__), "prompts", "*.json"))
        templates = []
        for pfile in prompt_files:
            try:
                with open(pfile, "r") as f:
                    templates.append(json.load(f))
            except Exception:
                pass
        return {"templates": templates}

    @app.post("/api/calls/dispatch")
    def dispatch_call(payload: CallDispatchPayload, admin=Depends(require_admin)):
        # Outbound PSTN calling is completely disabled.
        # Staging and the mock carrier cannot place a customer call of any kind.
        if settings.STAGING or settings.TELEPHONY_PROVIDER == "mock":
            raise HTTPException(
                status_code=403,
                detail="Staging cannot place outbound or customer calls."
            )
        if payload.provider != "simulator":
            raise HTTPException(
                status_code=403,
                detail="Outbound calling is completely disabled. Only inbound SignalWire calls and browser simulations are permitted."
            )

        if os.getenv("VERCEL"):
            raise HTTPException(status_code=503, detail="This feature is disabled until durable support is implemented")
        ast = db.get_assistant(payload.assistant_id)
        if not ast:
            raise HTTPException(status_code=404, detail="Assistant not found")

        call_id = f"call_{uuid.uuid4().hex[:12]}"
        first_msg = VoiceEngine.render_prompt(ast["first_message"], payload.dynamic_vars)
        call_record = {
            "id": call_id,
            "assistant_id": ast["id"],
            "phone_number": payload.phone_number,
            "direction": "outbound",
            "provider": "simulator",
            "status": "in-progress",
            "goal": payload.goal or ast["description"],
            "dynamic_vars_applied": payload.dynamic_vars
        }
        db.create_call(call_record)
        db.add_transcript_message(call_id, "assistant", first_msg, latency_ms=120)
        return {
            "success": True,
            "call_id": call_id,
            "first_message": first_msg,
            "dispatch_details": {"call_id": call_id, "status": "in-progress", "provider": "simulator"}
        }

    @app.post("/api/calls/{call_id}/approve")
    def approve_outbound_call(call_id: str, admin=Depends(require_admin)):
        raise HTTPException(
            status_code=403,
            detail="Outbound calling is completely disabled."
        )

    @app.get("/api/receptionist/messages")
    def list_receptionist_messages(admin=Depends(require_admin)):
        try:
            messages = db.list_receptionist_messages()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Receptionist messages are unavailable") from exc
        return JSONResponse({"messages": messages}, headers={"Cache-Control": "private, no-store"})

    @app.get("/api/calls")
    def list_calls(admin=Depends(require_admin)):
        if os.getenv("VERCEL"):
            raise HTTPException(status_code=503, detail="Durable call listing is not implemented")
        return {"calls": db.list_calls()}

    @app.get("/api/calls/{call_id}")
    def get_call_details(call_id: str, admin=Depends(require_admin)):
        c = db.get_call(call_id)
        if not c:
            raise HTTPException(status_code=404, detail="Call not found")
        transcripts = db.get_call_transcripts(call_id)
        return {"call": c, "transcripts": transcripts}

    @app.post("/api/staging/exercise")
    def staging_exercise(request: Request):
        if not settings.STAGING:
            raise HTTPException(status_code=404, detail="Not found")
        token = os.getenv("APEX_ADMIN_TOKEN", "")
        header = request.headers.get("authorization", "")
        presented = header[7:] if header.startswith("Bearer ") else ""
        if not token or not presented or not hmac.compare_digest(presented, token):
            raise HTTPException(status_code=401, detail="Administrator authentication required",
                                headers={"WWW-Authenticate": "Bearer"})
        try:
            payload = run_staging_exercise()
        except Exception as exc:
            log_ops_failure("staging exercise", exc)
            raise HTTPException(status_code=503, detail="Staging exercise failed") from exc
        return JSONResponse(payload, headers={"Cache-Control": "private, no-store"})

    @app.get("/api/dashboard")
    def operations_dashboard(admin=Depends(require_admin)):
        try:
            payload = build_operations_dashboard()
        except Exception as exc:
            log_ops_failure("dashboard", exc)
            payload = _dashboard_payload(
                None, "blocked", None, False, False, None, [], [], [], [],
                ["Operations data could not be loaded."], ["dashboard"],
            )
        return JSONResponse(payload, headers={"Cache-Control": "private, no-store"})

    @app.post("/api/calls/{call_id}/terminate")
    def terminate_call(call_id: str, admin=Depends(require_admin)):
        if settings.STAGING or settings.TELEPHONY_PROVIDER == "mock":
            raise HTTPException(status_code=403, detail="Mock telephony cannot control a live call.")
        if os.getenv("VERCEL"):
            c = db.get_call(call_id)
            if not c:
                raise HTTPException(status_code=404, detail="Call not found")
            if c.get("provider") != "signalwire" or c.get("direction") != "inbound":
                raise HTTPException(status_code=400, detail="Only inbound SignalWire calls can be terminated")
            if c.get("status") not in ("in-progress", "ending"):
                raise HTTPException(status_code=409, detail="Call is no longer active")
            if db._upstash_cmd(["GET", db.ACTIVE_CALL_KEY]) != call_id:
                raise HTTPException(status_code=409, detail="Call no longer owns the active slot")
            remember_caller_message(call_id)
            try:
                requested = telephony.terminate_signalwire_call(call_id)
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            if not requested:
                raise HTTPException(status_code=502, detail="Carrier did not accept termination")
            # Carrier callback owns final state and actual duration; do not fake completion.
            return {"success": True, "call_id": call_id, "termination_requested": True}
        c = db.get_call(call_id)
        if not c:
            raise HTTPException(status_code=404, detail="Call not found")
        remember_caller_message(call_id)
        cost_info = VoiceEngine.calculate_call_cost(c["duration_seconds"], provider=c["provider"])
        db.update_call(call_id, {
            "status": "completed",
            "ended_at": datetime.utcnow().isoformat(),
            "cost_telephony": cost_info["cost_telephony"],
            "cost_llm": cost_info["cost_llm"],
            "cost_tts": cost_info["cost_tts"],
            "cost_total": cost_info["cost_total"]
        })
        reconciled = release_call_slot_safely(call_id, cost_info["cost_total"])
        return {"success": True, "call_id": call_id, "cost_breakdown": cost_info,
                "budget_reconciled": reconciled}

    @app.post("/api/simulate/turn")
    def simulate_conversation_turn(payload: SimulationTurnPayload, admin=Depends(require_admin)):
        if os.getenv("VERCEL"):
            raise HTTPException(status_code=503, detail="This feature is disabled until durable support is implemented")
        call = db.get_call(payload.call_id)
        if not call:
            raise HTTPException(status_code=404, detail="Call not found")
        ast = db.get_assistant(call["assistant_id"])
        if not ast:
            raise HTTPException(status_code=404, detail="Assistant not found")

        conv_history = build_conversation_history(db.get_call_transcripts(payload.call_id))
        db.add_transcript_message(payload.call_id, "human", payload.user_message)
        dynamic_vars = {"business_name": settings.RECEPTIONIST_BUSINESS_NAME, **(call.get("dynamic_vars_applied") or {})}
        rendered_system_prompt = VoiceEngine.render_prompt(ast["system_prompt"], dynamic_vars)

        ai_result = voice_engine.generate_chat_response(
            system_prompt=rendered_system_prompt,
            conversation_history=conv_history,
            new_human_input=payload.user_message,
            temperature=ast.get("temperature", 0.4),
            tools=ast.get("tools", [])
        )

        assistant_reply = ai_result["text"]
        latency_ms = ai_result["latency_ms"]
        detected_tool = ai_result.get("tool_call")

        db.add_transcript_message(payload.call_id, "assistant", assistant_reply, latency_ms=latency_ms)

        if detected_tool:
            extracted = call.get("extracted_data", {})
            extracted[detected_tool.get("tool", "unnamed_tool")] = detected_tool.get("parameters", {})
            db.update_call(payload.call_id, {"extracted_data": extracted, "outcome_status": "recorded_for_followup"})
            db.add_transcript_message(
                payload.call_id,
                "tool",
                f"Details captured: {detected_tool.get('tool')} with {json.dumps(detected_tool.get('parameters', {}))}"
            )

        new_duration = min(call.get("duration_seconds", 0) + 15, settings.MAX_CALL_DURATION_SECONDS)
        cost_info = VoiceEngine.calculate_call_cost(new_duration, provider=call["provider"])
        db.update_call(payload.call_id, {
            "duration_seconds": new_duration,
            "cost_telephony": cost_info["cost_telephony"],
            "cost_llm": cost_info["cost_llm"],
            "cost_tts": cost_info["cost_tts"],
            "cost_total": cost_info["cost_total"]
        })
        if is_closing_request(payload.user_message):
            remember_caller_message(payload.call_id)

        return {
            "assistant_message": assistant_reply,
            "latency_ms": latency_ms,
            "tool_call": detected_tool,
            "current_cost": cost_info
        }

    @app.get("/api/tts/clip/{clip_id}.mp3")
    def serve_opaque_tts_clip(clip_id: str):
        """
        Serves ElevenLabs audio using a short-lived opaque clip_id backed by temporary storage.
        Zero conversation text is ever exposed in URLs.
        """
        if os.getenv("VERCEL"):
            try:
                if db._upstash_cmd(["EXISTS", db.CALL_PAUSE_KEY]):
                    raise HTTPException(status_code=503, detail="Call handling is paused")
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail="Call state unavailable") from exc
        clip = db.get_tts_clip(clip_id)
        if not clip:
            raise HTTPException(status_code=404, detail="Audio clip expired or not found")
        # Redis caches the synthesized MP3 for carrier retries across serverless instances.
        # A short-lived synthesis lock prevents duplicate paid requests. Never persist audio locally on Vercel.
        lock_key = f"apex:tts_generating:{clip_id}"
        audio_bytes = db.read_cached_tts_audio(clip_id)
        if audio_bytes is None and os.getenv("VERCEL"):
            if db._upstash_cmd(["SET", lock_key, "1", "NX", "EX", "20"]) != "OK":
                # Carrier can retry the same URL. Return a temporary failure, not a permanent 410.
                raise HTTPException(status_code=503, detail="Audio generation in progress; retry shortly", headers={"Retry-After": "2"})
        if audio_bytes is None:
            try:
                audio_bytes = voice_engine.synthesize_speech_elevenlabs(clip["text"], voice_id=clip["voice_id"])
                if not audio_bytes:
                    db.note_ops_error("tts_playback_failed")
                    raise HTTPException(status_code=503, detail="ElevenLabs synthesis unavailable")
                # A failed cache write must not hide the bytes already synthesized for this request.
                db.cache_tts_audio(clip_id, audio_bytes)
            finally:
                if os.getenv("VERCEL"):
                    db._upstash_cmd(["DEL", lock_key])
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"Cache-Control": "private, no-store, max-age=0"}
        )

    @app.post("/webhooks/signalwire/voice")
    async def signalwire_voice_webhook(request: Request):
        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        params = {k: v[0] for k, v in urllib.parse.parse_qs(raw_body).items()}
        pub_url = reconstruct_public_webhook_url(str(request.url), dict(request.headers))
        if not telephony.verify_signalwire_webhook(pub_url, params, raw_body, dict(request.headers)):
            raise HTTPException(status_code=403, detail="Invalid SignalWire webhook signature")

        query_params = dict(request.query_params)
        try:
            cxml = await run_in_threadpool(handle_signalwire_inbound_or_connect, params, query_params)
        except (RuntimeError, OSError):
            cxml = telephony.build_signalwire_cxml_hangup("This line is temporarily unavailable. Please try again later.")
        return Response(content=cxml, media_type="application/xml")

    @app.post("/webhooks/signalwire/gather")
    async def signalwire_gather_webhook(request: Request):
        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        params = {k: v[0] for k, v in urllib.parse.parse_qs(raw_body).items()}
        pub_url = reconstruct_public_webhook_url(str(request.url), dict(request.headers))
        if not telephony.verify_signalwire_webhook(pub_url, params, raw_body, dict(request.headers)):
            raise HTTPException(status_code=403, detail="Invalid SignalWire webhook signature")

        query_params = dict(request.query_params)
        try:
            cxml = await run_in_threadpool(handle_signalwire_gather_turn, params, query_params)
        except (RuntimeError, OSError):
            cxml = telephony.build_signalwire_cxml_hangup(
                "This line is temporarily unavailable. Please try again later."
            )
        return Response(content=cxml, media_type="application/xml")

    @app.post("/webhooks/signalwire/status")
    async def signalwire_status_webhook(request: Request):
        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        params = {k: v[0] for k, v in urllib.parse.parse_qs(raw_body).items()}
        pub_url = reconstruct_public_webhook_url(str(request.url), dict(request.headers))
        if not telephony.verify_signalwire_webhook(pub_url, params, raw_body, dict(request.headers)):
            raise HTTPException(status_code=403, detail="Invalid SignalWire webhook signature")
        if settings.STAGING:
            db.staging_request_allowed()
            return {"status": "ok", "tracked": False, "staging": True}

        call_id = params.get("CallSid")
        call_status = params.get("CallStatus", "")
        if call_status not in ("completed", "busy", "no-answer", "failed", "canceled"):
            return {"status": "ok"}
        if not call_id:
            raise HTTPException(status_code=400, detail="Missing carrier call ID")
        try:
            raw_duration = params.get("CallDuration")
            if raw_duration is None and call_status != "completed":
                raw_duration = "0"
            if not raw_duration or not raw_duration.isascii() or not raw_duration.isdecimal() or len(raw_duration) > 9:
                raise ValueError("Invalid carrier duration")
            duration = int(raw_duration)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid carrier duration") from exc

        return await run_in_threadpool(settle_signalwire_call, call_id, call_status, duration)

    def settle_signalwire_call(call_id: str, call_status: str, duration: int):
        if settings.STAGING or settings.MONTHLY_BUDGET_LIMIT_USD <= 0:
            return {"status": "ok", "tracked": False, "staging": settings.STAGING}
        remember_caller_message(call_id)
        try:
            call = db.get_call(call_id)
            if not call and os.getenv("VERCEL"):
                if not db._upstash_cmd(["EXISTS", f"apex:acct:{call_id}"]):
                    return {"status": "ok", "tracked": False}
            outcome = apply_call_settlement(call_id, duration, "carrier", carrier_status=call_status)
        except (RuntimeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Call settlement unavailable") from exc
        return {"status": "ok", "budget_reconciled": True, "settlement": outcome}

    @app.post("/api/maintenance/enforce-call-duration")
    def enforce_call_duration(request: Request):
        secret = settings.CRON_SECRET
        authorization = request.headers.get("authorization", "")
        if not secret or not hmac.compare_digest(authorization.encode(), f"Bearer {secret}".encode()):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if not os.getenv("VERCEL") or settings.durable_storage_backend() != "upstash_redis":
            raise HTTPException(status_code=503, detail="Durable carrier enforcement unavailable")
        try:
            # Preserve any legacy leased slot before it expires while a call is active.
            call_id, paused = db._upstash_cmd([
                "EVAL",
                "local id = redis.call('GET', KEYS[1]); if id then redis.call('PERSIST', KEYS[1]) end; "
                "return {id or false, redis.call('EXISTS', KEYS[2])}",
                "2", db.ACTIVE_CALL_KEY, db.CALL_PAUSE_KEY
            ])
            requested = False
            if call_id:
                call = db.get_call(call_id)
                recoverable = ("in-progress", "ending", "stale_unsettled")
                if not call or call.get("status") not in recoverable:
                    # A terminal callback can be between recording state and settling the slot.
                    if db._upstash_cmd(["GET", db.ACTIVE_CALL_KEY]) == call_id:
                        raise HTTPException(status_code=503, detail="Active call settlement pending")
                else:
                    started = datetime.fromisoformat(call["started_at"].replace("Z", "+00:00"))
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    seconds = max(0, (datetime.now(timezone.utc) - started).total_seconds())
                    past_grace = seconds >= settings.MAX_CALL_DURATION_SECONDS + settings.STALE_SETTLEMENT_GRACE_SECONDS
                    still_holding = db._upstash_cmd(["GET", db.ACTIVE_CALL_KEY]) == call_id
                    # Past the grace window, accounting recovery does not depend on the carrier.
                    if still_holding and not past_grace and (paused or seconds >= settings.MAX_CALL_DURATION_SECONDS):
                        requested = telephony.terminate_signalwire_call(call_id)
                        if not requested:
                            raise HTTPException(status_code=502, detail="Carrier rejected termination")
            stale = sweep_stale_reservations()
            stale_settled = sum(1 for item in stale if item.get("outcome") == "released")
            if db._upstash_cmd(["SET", db.SCHEDULER_KEY, "1", "EX", "180"]) != "OK":
                raise RuntimeError("Could not verify scheduler heartbeat")
            return {
                "checked": True,
                "active": bool(call_id),
                "termination_requested": requested,
                "stale_settled": stale_settled,
            }
        except HTTPException:
            raise
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=502, detail="Unable to enforce call duration") from exc

    @app.get("/api/voices")
    def get_voices(admin=Depends(require_admin)):
        return {"voices": voice_engine.list_elevenlabs_voices()}

    @app.get("/api/cost/calculate")
    def calculate_cost(duration_seconds: int = 180, calls_count: int = 100, provider: str = "signalwire", admin=Depends(require_admin)):
        if not 1 <= duration_seconds <= 7200 or not 1 <= calls_count <= 10000 or provider not in ("signalwire", "twilio", "telnyx"):
            raise HTTPException(status_code=422, detail="Invalid cost estimation parameters")
        single_call = VoiceEngine.calculate_call_cost(duration_seconds, provider=provider)
        minutes_per_call = duration_seconds / 60.0
        total_ours = single_call["cost_total"] * calls_count
        total_bland = single_call["bland_equivalent"] * calls_count
        total_savings = total_bland - total_ours
        return {
            "duration_seconds": duration_seconds,
            "minutes_per_call": round(minutes_per_call, 2),
            "calls_count": calls_count,
            "single_call": single_call,
            "campaign_total_cost_ours": round(total_ours, 2),
            "campaign_total_cost_bland": round(total_bland, 2),
            "total_savings_dollars": round(total_savings, 2),
            "savings_percentage": single_call["savings_percentage"]
        }

    def read_operations_page() -> str:
        index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return f.read()
        return "<h1>ApexVoice AI Platform API is running.</h1>"

    @app.get("/", response_class=HTMLResponse)
    def serve_index():
        return read_operations_page()

    @app.get("/operations", response_class=HTMLResponse)
    def serve_operations():
        return read_operations_page()

except ImportError:
    app = None
