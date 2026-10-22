"""
AI Voice Engine: Orchestrates Hugging Face Inference Providers Router (router.huggingface.co/v1/chat/completions)
and ElevenLabs TTS (eleven_turbo_v2_5).
Zero conversation text is ever placed in URLs.
"""
import re
import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Tuple
from config import settings

class VoiceEngine:
    def __init__(self, hf_token: str = None, elevenlabs_key: str = None):
        self.hf_token = hf_token or settings.HUGGINGFACE_API_KEY
        self.elevenlabs_key = elevenlabs_key or settings.ELEVENLABS_API_KEY
        self.hf_router_url = settings.HUGGINGFACE_ROUTER_URL
        self.hf_model = settings.HUGGINGFACE_LLM_MODEL

    @staticmethod
    def render_prompt(template_str: str, variables: Dict[str, Any]) -> str:
        """Interpolates dynamic {{variable}} tags safely."""
        result = template_str
        for key, val in (variables or {}).items():
            pattern = re.compile(r"\{\{\s*" + re.escape(key) + r"\s*\}\}")
            result = pattern.sub(str(val), result)
        return result

    def generate_chat_response(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        new_human_input: str,
        temperature: float = 0.4,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Generates assistant response using Hugging Face's current supported
        OpenAI-compatible router endpoint: https://router.huggingface.co/v1/chat/completions
        with model meta-llama/Llama-3.1-8B-Instruct.
        """
        start_time = time.time()
        
        messages = [{"role": "system", "content": system_prompt}]
        for turn in conversation_history:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": new_human_input})

        if tools:
            tool_guide = "\n\nAVAILABLE TOOLS:\n"
            for t in tools:
                tool_guide += f"- {t.get('name')}: {t.get('description')}\n"
            tool_guide += "If you have accomplished a milestone or acquired finalized details, emit a JSON block on a new line: ```json {\"tool\": \"tool_name\", \"parameters\": {...}} ```"
            messages[0]["content"] += tool_guide

        response_text = ""
        detected_tool = None

        if self.hf_token and self.hf_token.strip():
            payload = json.dumps({
                "model": self.hf_model,
                "messages": messages,
                "max_tokens": 120,
                "temperature": temperature,
                "stream": False
            }).encode("utf-8")
            req = urllib.request.Request(
                self.hf_router_url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.hf_token}",
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=settings.HTTP_UPSTREAM_TIMEOUT_SECONDS) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        choices = data.get("choices", [])
                        if choices and isinstance(choices, list):
                            response_text = choices[0].get("message", {}).get("content", "")
            except Exception as e:
                print(f"[VoiceEngine] HF Router notice: {e}")

        if not response_text:
            response_text, detected_tool = self._heuristic_fallback_response(
                system_prompt, messages, new_human_input, tools
            )

        latency_ms = int((time.time() - start_time) * 1000)

        if not detected_tool:
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
            if json_match:
                try:
                    detected_tool = json.loads(json_match.group(1))
                    response_text = re.sub(r"```json\s*\{.*?\}\s*```", "", response_text, flags=re.DOTALL).strip()
                except Exception:
                    pass

        return {
            "text": response_text.strip(),
            "latency_ms": latency_ms,
            "tool_call": detected_tool
        }

    def _heuristic_fallback_response(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        human_input: str,
        tools: Optional[List[Dict[str, Any]]]
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Fail safely without inventing bookings, order numbers or negotiated terms.

        When the AI provider is unavailable, no transactional details may be
        asserted and no extraction tool should be fired.
        """
        return (
            "I'm sorry, my automated assistant service is temporarily unavailable. "
            "I can't confirm any appointments, orders or account changes. "
            "Please try again later or contact the business directly.",
            None,
        )

    def synthesize_speech_elevenlabs(
        self,
        text: str,
        voice_id: Optional[str] = None,
        stability: float = 0.5,
        similarity_boost: float = 0.75
    ) -> Optional[bytes]:
        if not self.elevenlabs_key or not self.elevenlabs_key.strip():
            return None

        voice = voice_id or settings.ELEVENLABS_DEFAULT_VOICE_ID
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
        payload = json.dumps({
            "text": text,
            "model_id": settings.ELEVENLABS_MODEL_ID,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "use_speaker_boost": True
            }
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "xi-api-key": self.elevenlabs_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=settings.HTTP_UPSTREAM_TIMEOUT_SECONDS) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception as e:
            print(f"[ElevenLabs TTS Exception] {e}")
        return None

    def list_elevenlabs_voices(self) -> List[Dict[str, Any]]:
        if not self.elevenlabs_key or not self.elevenlabs_key.strip():
            return [
                {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel (Calm & Professional)", "category": "premade"},
                {"voice_id": "pNInz6obpgDQGcFmaJgB", "name": "Adam (Deep & Confident)", "category": "premade"},
                {"voice_id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh (Warm & Articulate)", "category": "premade"},
                {"voice_id": "ErXwobaYiN019PkySvjV", "name": "Antoni (Engaging & Friendly)", "category": "premade"},
                {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella (Youthful & Clear)", "category": "premade"}
            ]

        url = "https://api.elevenlabs.io/v1/voices"
        req = urllib.request.Request(url, headers={"xi-api-key": self.elevenlabs_key})
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    voices = json.loads(resp.read().decode("utf-8")).get("voices", [])
                    return [
                        {
                            "voice_id": v["voice_id"],
                            "name": v["name"],
                            "category": v.get("category", "custom"),
                            "preview_url": v.get("preview_url")
                        }
                        for v in voices
                    ]
        except Exception as e:
            print(f"[ElevenLabs Voice List Exception] {e}")
            
        return [
            {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel (Default)", "category": "premade"},
            {"voice_id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh (Default)", "category": "premade"}
        ]

    @staticmethod
    def calculate_call_cost(duration_seconds: int, provider: str = "signalwire", tts_provider: str = "elevenlabs") -> Dict[str, float]:
        minutes = max(duration_seconds / 60.0, 0.1)
        telephony_rate = 0.0055 if provider == "signalwire" else 0.003
        stt_rate = 0.0043
        llm_rate = 0.002
        tts_rate = 0.015 if tts_provider == "elevenlabs" else 0.001
        
        total_per_min = telephony_rate + stt_rate + llm_rate + tts_rate
        bland_rate_per_min = 0.12
        
        cost_telephony = round(minutes * telephony_rate, 4)
        cost_stt = round(minutes * stt_rate, 4)
        cost_llm = round(minutes * llm_rate, 4)
        cost_tts = round(minutes * tts_rate, 4)
        cost_total = round(minutes * total_per_min, 4)
        bland_equivalent = round(minutes * bland_rate_per_min, 4)
        savings = round(bland_equivalent - cost_total, 4)
        savings_percentage = round((savings / bland_equivalent) * 100, 1) if bland_equivalent > 0 else 0

        return {
            "minutes": round(minutes, 2),
            "cost_telephony": cost_telephony,
            "cost_stt": cost_stt,
            "cost_llm": cost_llm,
            "cost_tts": cost_tts,
            "cost_total": cost_total,
            "bland_equivalent": bland_equivalent,
            "savings": savings,
            "savings_percentage": savings_percentage
        }
