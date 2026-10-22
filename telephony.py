"""
Telephony Gateway: SignalWire Compatibility API (cXML/LaML) for harbour-and-main.signalwire.com (+1 226-773-0802).
Implements SignalWire's documented webhook signature verification (X-SignalWire-Signature / X-SignalWire-Sha256-Signature).
Outbound calling is completely disabled.
"""
import hmac
import hashlib
import base64
import urllib.parse
import urllib.request
import urllib.error
import re
import xml.sax.saxutils as saxutils
from typing import Dict, Any, Optional
from config import settings

class TelephonyGateway:
    def __init__(
        self,
        signalwire_space: Optional[str] = None,
        signalwire_project_id: Optional[str] = None,
        signalwire_token: Optional[str] = None,
        signalwire_from_number: Optional[str] = None,
        public_url: Optional[str] = None
    ):
        self.signalwire_space = signalwire_space or settings.SIGNALWIRE_SPACE_URL
        self.signalwire_project_id = signalwire_project_id or settings.SIGNALWIRE_PROJECT_ID
        self.signalwire_token = signalwire_token or settings.SIGNALWIRE_API_TOKEN
        self.signalwire_from = signalwire_from_number or settings.SIGNALWIRE_PHONE_NUMBER
        self.public_url = public_url or settings.PUBLIC_URL


    def terminate_signalwire_call(self, call_sid: str) -> bool:
        """Ask SignalWire to complete an active call. A successful HTTP response
        means a request was accepted, not that billing has been reconciled.
        """
        if not (self.signalwire_project_id and self.signalwire_token and self.signalwire_space):
            raise RuntimeError("SignalWire credentials are not configured")
        if not re.fullmatch(r"[a-zA-Z0-9-]{10,80}", call_sid or ""):
            raise ValueError("Invalid call SID")
        space = self.signalwire_space.strip().lower()
        if not re.fullmatch(r"[a-z0-9-]+\.signalwire\.com", space):
            raise ValueError("SignalWire Space must be a signalwire.com hostname")
        project = urllib.parse.quote(self.signalwire_project_id, safe="")
        sid = urllib.parse.quote(call_sid, safe="")
        url = f"https://{space}/api/laml/2010-04-01/Accounts/{project}/Calls/{sid}"
        basic = base64.b64encode(f"{self.signalwire_project_id}:{self.signalwire_token}".encode()).decode()
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode({"Status": "completed"}).encode(),
            method="POST",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("SignalWire call termination failed") from exc

    @staticmethod
    def compute_signalwire_laml_signature(signing_key: str, url: str, params: Dict[str, str]) -> str:
        """
        Computes SignalWire Compatibility API (cXML/LaML) HMAC-SHA1 base64 signature:
        url + sorted(key + value) signed with signing_key.
        Reference: https://signalwire.com/docs/compatibility-api/guides/webhook-security
        """
        data = url
        for k in sorted(params.keys()):
            data += f"{k}{params[k]}"
        mac = hmac.new(signing_key.encode("utf-8"), data.encode("utf-8"), hashlib.sha1)
        return base64.b64encode(mac.digest()).decode("ascii")

    @staticmethod
    def compute_signalwire_sha256_signature(signing_key: str, url: str, raw_body: str) -> str:
        """
        Computes SignalWire HMAC-SHA256 webhook signature over (url + raw_body).
        """
        data = f"{url}{raw_body}".encode("utf-8")
        return hmac.new(signing_key.encode("utf-8"), data, hashlib.sha256).hexdigest()

    def verify_signalwire_webhook(
        self,
        url: str,
        params: Dict[str, str],
        raw_body: str,
        headers: Dict[str, str]
    ) -> bool:
        """
        Verifies incoming SignalWire webhook requests using X-SignalWire-Signature,
        X-SignalWire-Sha256-Signature, or X-Twilio-Signature.
        """
        if not settings.ENFORCE_WEBHOOK_SIGNATURE:
            return True

        signing_key = settings.get_webhook_signing_key()
        if not signing_key:
            # Cannot verify without configured signing key; fail closed when enforcement is enabled
            return False

        norm_headers = {k.lower(): v for k, v in (headers or {}).items()}
        sig_sha256 = norm_headers.get("x-signalwire-sha256-signature", "").strip()
        sig_main = (
            norm_headers.get("x-signalwire-signature")
            or norm_headers.get("x-twilio-signature")
            or ""
        ).strip()

        if not sig_sha256 and not sig_main:
            return False

        # Candidate keys: primary signing key and API token fallback
        candidate_keys = [signing_key]
        if settings.SIGNALWIRE_API_TOKEN and settings.SIGNALWIRE_API_TOKEN not in candidate_keys:
            candidate_keys.append(settings.SIGNALWIRE_API_TOKEN)

        for key in candidate_keys:
            if sig_sha256:
                expected_hex = self.compute_signalwire_sha256_signature(key, url, raw_body)
                expected_b64 = base64.b64encode(
                    hmac.new(key.encode("utf-8"), f"{url}{raw_body}".encode("utf-8"), hashlib.sha256).digest()
                ).decode("ascii")
                if hmac.compare_digest(sig_sha256, expected_hex) or hmac.compare_digest(sig_sha256, expected_b64):
                    return True

            if sig_main:
                expected_sha1 = self.compute_signalwire_laml_signature(key, url, params)
                if hmac.compare_digest(sig_main, expected_sha1):
                    return True
                expected_raw_sha256 = self.compute_signalwire_sha256_signature(key, url, raw_body)
                if hmac.compare_digest(sig_main, expected_raw_sha256):
                    return True

        return False

    def build_signalwire_cxml_gather(
        self,
        call_id: str,
        assistant_id: str,
        spoken_text: str,
        clip_id: Optional[str] = None
    ) -> str:
        """
        Generates SignalWire cXML (LaML) response for conversational turn-taking.
        Uses <Play> with opaque clip_id (/api/tts/clip/{clip_id}.mp3) when ElevenLabs is enabled.
        Zero conversation text is ever placed in URLs.
        """
        action_url = (
            f"{self.public_url.rstrip('/')}/webhooks/signalwire/gather?"
            f"call_id={urllib.parse.quote(call_id)}&amp;assistant_id={urllib.parse.quote(assistant_id)}"
        )
        if clip_id:
            clip_url = f"{self.public_url.rstrip('/')}/api/tts/clip/{urllib.parse.quote(clip_id)}.mp3"
            prompt_node = f"<Play>{saxutils.escape(clip_url)}</Play>"
        else:
            prompt_node = f'<Say language="en-US">{saxutils.escape(spoken_text)}</Say>'

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f'  <Gather input="speech dtmf" action="{action_url}" method="POST" speechTimeout="auto" timeout="6" language="en-US">\n'
            f"    {prompt_node}\n"
            "  </Gather>\n"
            '  <Say language="en-US">I did not catch a response. Please call back whenever you are ready. Goodbye!</Say>\n'
            "  <Hangup/>\n"
            "</Response>"
        )

    def build_signalwire_cxml_hangup(self, spoken_text: str, clip_id: Optional[str] = None) -> str:
        """Generates SignalWire cXML to speak a final message and hang up."""
        if clip_id:
            clip_url = f"{self.public_url.rstrip('/')}/api/tts/clip/{urllib.parse.quote(clip_id)}.mp3"
            prompt_node = f"<Play>{saxutils.escape(clip_url)}</Play>"
        else:
            prompt_node = f'<Say language="en-US">{saxutils.escape(spoken_text)}</Say>'
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f"  {prompt_node}\n"
            "  <Hangup/>\n"
            "</Response>"
        )
