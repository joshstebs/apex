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
import glob
import json
import uuid
import hmac
import urllib.parse
import base64
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

from config import settings
from database import Database
from voice_engine import VoiceEngine
from telephony import TelephonyGateway

db = Database(settings.DB_PATH)
voice_engine = VoiceEngine()
telephony = TelephonyGateway()

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

def handle_signalwire_inbound_or_connect(
    params: Dict[str, str],
    query_params: Dict[str, str]
) -> str:
    """
    Handles authenticated POST /webhooks/signalwire/voice for incoming calls to +1 226-773-0802.
    Acquires atomic concurrency & budget lock, stores greeting under an opaque short-lived clip_id,
    and returns SignalWire cXML.
    """
    call_id = params.get("CallSid") or f"call_{uuid.uuid4().hex[:12]}"
    assistant_id = query_params.get("assistant_id")
    from_number = params.get("From", "Unknown")

    ast = db.get_assistant(assistant_id) if assistant_id else None
    if not ast:
        assistants = db.list_assistants()
        ast = assistants[0] if assistants else {
            "id": "default_inbound",
            "name": "Inbound Receptionist",
            "first_message": "Hello! You have reached Josh Stebs' AI assistant. How can I help you today?",
            "system_prompt": "You are a polite, concise voice assistant answering calls for Josh Stebs.",
            "voice_id": settings.ELEVENLABS_DEFAULT_VOICE_ID,
            "temperature": 0.4,
            "tools": []
        }

    greeting = (
        "Hello! You've reached Josh Stebs' automated assistant. "
        "How can I help you today?"
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

    # Atomic concurrency (1 call) and budget ($5.00) lock across simultaneous Vercel instances
    acquired, err_msg = db.try_acquire_call_slot(call_record)
    if not acquired:
        return telephony.build_signalwire_cxml_hangup(
            "Sorry, this line is currently busy or has reached its usage limit. Please try again later."
        )

    db.add_transcript_message(call_id, "assistant", greeting, latency_ms=95)
    # Create short-lived opaque TTS clip ID (zero conversation text in URL)
    clip_id = None
    if voice_engine.elevenlabs_key and voice_engine.elevenlabs_key.strip():
        clip_id = db.create_tts_clip(greeting, voice_id=ast.get("voice_id") or settings.ELEVENLABS_DEFAULT_VOICE_ID)

    return telephony.build_signalwire_cxml_gather(
        call_id=call_id,
        assistant_id=ast["id"],
        spoken_text=greeting,
        clip_id=clip_id
    )

def handle_signalwire_gather_turn(
    params: Dict[str, str],
    query_params: Dict[str, str]
) -> str:
    """
    Handles authenticated POST /webhooks/signalwire/gather when caller speaks or presses digits.
    """
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
        holder = db._upstash_cmd(["GET", "apex:active_call_lock"])
        if holder != call_id or call.get("status") != "in-progress":
            return telephony.build_signalwire_cxml_hangup("This call session has ended. Goodbye.")

    # Enforce configured duration at the next webhook turn (not carrier-side termination)
    from datetime import timezone
    try:
        started = datetime.fromisoformat(call["started_at"].replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        new_duration = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    except (ValueError, KeyError, TypeError):
        return telephony.build_signalwire_cxml_hangup("Unable to verify call duration. Goodbye.")
    if new_duration >= settings.MAX_CALL_DURATION_SECONDS:
        cost_info = VoiceEngine.calculate_call_cost(settings.MAX_CALL_DURATION_SECONDS, provider="signalwire")
        prev_cost = float(call.get("cost_total", 0.0) or 0.0)
        db.update_call(call_id, {
            "status": "completed",
            "duration_seconds": settings.MAX_CALL_DURATION_SECONDS,
            "ended_at": datetime.utcnow().isoformat(),
            "cost_total": cost_info["cost_total"]
        })
        db.release_call_slot(call_id, cost_delta=max(0.0, cost_info["cost_total"] - prev_cost))
        return telephony.build_signalwire_cxml_hangup(
            f"We have reached our {settings.MAX_CALL_DURATION_SECONDS // 60} minute call time limit. Thank you and goodbye!"
        )

    if not user_input:
        db.update_call(call_id, {"status": "completed", "ended_at": datetime.utcnow().isoformat()})
        db.release_call_slot(call_id, cost_delta=0.0)
        return telephony.build_signalwire_cxml_hangup("I didn't hear anything. Goodbye!")

    ast = db.get_assistant(call.get("assistant_id") or assistant_id)
    if not ast:
        ast = db.list_assistants()[0]

    # Redis state is authoritative across Vercel instances.
    db.add_transcript_message(call_id, "human", user_input)

    dynamic_vars = call.get("dynamic_vars_applied", {"user_name": "Josh Stebs"})
    rendered_prompt = VoiceEngine.render_prompt(ast["system_prompt"], dynamic_vars)

    all_transcripts = db.get_call_transcripts(call_id)
    conv_history = [
        {"role": "assistant" if t["speaker"] == "assistant" else "user", "content": t["message"]}
        for t in all_transcripts[:-1]
    ]

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
        db.update_call(call_id, {"extracted_data": extracted, "outcome_status": "success"})
        db.add_transcript_message(
            call_id, "tool", f"Action Triggered: {detected_tool.get('tool')} {json.dumps(detected_tool.get('parameters', {}))}"
        )

    cost_info = VoiceEngine.calculate_call_cost(new_duration, provider="signalwire")
    db.update_call(call_id, {
        "duration_seconds": new_duration,
        "cost_telephony": cost_info["cost_telephony"],
        "cost_llm": cost_info["cost_llm"],
        "cost_tts": cost_info["cost_tts"],
        "cost_total": cost_info["cost_total"]
    })

    # Create short-lived opaque TTS clip ID (zero conversation text in URL)
    clip_id = None
    if voice_engine.elevenlabs_key and voice_engine.elevenlabs_key.strip():
        clip_id = db.create_tts_clip(reply_text, voice_id=ast.get("voice_id") or settings.ELEVENLABS_DEFAULT_VOICE_ID)

    if any(p in user_input.lower() for p in ["goodbye", "bye", "that's all", "hang up"]):
        db.update_call(call_id, {"status": "completed", "ended_at": datetime.utcnow().isoformat()})
        db.release_call_slot(call_id, cost_delta=cost_info["cost_total"])
        return telephony.build_signalwire_cxml_hangup(reply_text, clip_id=clip_id)

    return telephony.build_signalwire_cxml_gather(
        call_id=call_id,
        assistant_id=ast["id"],
        spoken_text=reply_text,
        clip_id=clip_id
    )

def get_sanitized_health_and_settings() -> Dict[str, Any]:
    """Returns strictly non-sensitive readiness flags and operational limits. Never exposes secrets."""
    return {
        "status": "ok",
        "default_provider": settings.DEFAULT_TELEPHONY_PROVIDER,
        "signalwire_space_configured": bool(settings.SIGNALWIRE_SPACE_URL),
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
        "outbound_calling_enabled": False
    }

# =========================================================================
# FASTAPI APPLICATION (VERCEL ASGI RUNTIME)
# =========================================================================
try:
    from fastapi import FastAPI, Request, HTTPException
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
        # Outbound PSTN calling is completely disabled
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

    @app.post("/api/calls/{call_id}/terminate")
    def terminate_call(call_id: str, admin=Depends(require_admin)):
        if os.getenv("VERCEL"):
            raise HTTPException(status_code=503, detail="Carrier-side termination not implemented; cannot claim a hard cutoff")
        c = db.get_call(call_id)
        if not c:
            raise HTTPException(status_code=404, detail="Call not found")
        cost_info = VoiceEngine.calculate_call_cost(c["duration_seconds"], provider=c["provider"])
        db.update_call(call_id, {
            "status": "completed",
            "ended_at": datetime.utcnow().isoformat(),
            "cost_telephony": cost_info["cost_telephony"],
            "cost_llm": cost_info["cost_llm"],
            "cost_tts": cost_info["cost_tts"],
            "cost_total": cost_info["cost_total"]
        })
        db.release_call_slot(call_id, cost_delta=cost_info["cost_total"])
        return {"success": True, "call_id": call_id, "cost_breakdown": cost_info}

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

        db.add_transcript_message(payload.call_id, "human", payload.user_message)
        dynamic_vars = call.get("dynamic_vars_applied", {})
        rendered_system_prompt = VoiceEngine.render_prompt(ast["system_prompt"], dynamic_vars)

        all_transcripts = db.get_call_transcripts(payload.call_id)
        conv_history = [
            {"role": "assistant" if t["speaker"] == "assistant" else "user", "content": t["message"]}
            for t in all_transcripts[:-1]
        ]

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
            db.update_call(payload.call_id, {"extracted_data": extracted, "outcome_status": "success"})
            db.add_transcript_message(
                payload.call_id,
                "tool",
                f"Action Triggered: {detected_tool.get('tool')} with {json.dumps(detected_tool.get('parameters', {}))}"
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
        clip = db.get_tts_clip(clip_id)
        if not clip:
            raise HTTPException(status_code=404, detail="Audio clip expired or not found")
        # Redis caches the synthesized MP3 for carrier retries across serverless instances.
        # A short-lived synthesis lock prevents duplicate paid requests. Never persist audio locally on Vercel.
        cache_key = f"apex:tts_audio:{clip_id}"
        lock_key = f"apex:tts_generating:{clip_id}"
        audio_bytes = None
        if os.getenv("VERCEL"):
            encoded = db._upstash_cmd(["GET", cache_key])
            if encoded:
                audio_bytes = base64.b64decode(encoded)
            else:
                if db._upstash_cmd(["SET", lock_key, "1", "NX", "EX", "20"]) != "OK":
                    # Carrier can retry the same URL. Return a temporary failure, not a permanent 410.
                    raise HTTPException(status_code=503, detail="Audio generation in progress; retry shortly", headers={"Retry-After": "2"})
        if audio_bytes is None:
            try:
                audio_bytes = voice_engine.synthesize_speech_elevenlabs(clip["text"], voice_id=clip["voice_id"])
                if not audio_bytes:
                    raise HTTPException(status_code=503, detail="ElevenLabs synthesis unavailable")
                if os.getenv("VERCEL"):
                    # Redis string limits and storage quota apply. 120 seconds is intentional.
                    db._upstash_cmd(["SET", cache_key, base64.b64encode(audio_bytes).decode("ascii"), "EX", "120"])
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
            cxml = handle_signalwire_inbound_or_connect(params, query_params)
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
            cxml = handle_signalwire_gather_turn(params, query_params)
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

        call_id = params.get("CallSid") or request.query_params.get("call_id")
        call_status = params.get("CallStatus", "completed")
        try:
            duration = max(0, int(params.get("CallDuration", "0") or 0))
        except (TypeError, ValueError):
            duration = 0
        if call_id and call_status in ("completed", "busy", "no-answer", "failed", "canceled"):
            cost_info = VoiceEngine.calculate_call_cost(duration, provider="signalwire")
            db.update_call(call_id, {
                "status": "completed" if call_status == "completed" else call_status,
                "duration_seconds": duration,
                "ended_at": datetime.utcnow().isoformat(),
                "cost_telephony": cost_info["cost_telephony"],
                "cost_llm": cost_info["cost_llm"],
                "cost_tts": cost_info["cost_tts"],
                "cost_total": cost_info["cost_total"]
            })
            db.release_call_slot(call_id, cost_delta=cost_info["cost_total"])
        return {"status": "ok"}

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

    @app.get("/", response_class=HTMLResponse)
    def serve_index():
        index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return f.read()
        return "<h1>ApexVoice AI Platform API is running.</h1>"

except ImportError:
    app = None
