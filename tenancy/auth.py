"""Customer authentication for the ApexVoice tenancy layer.

Passwords are hashed with hashlib.pbkdf2_hmac (SHA-256) and a per-user
random salt. Plaintext passwords are never stored. Sessions are opaque
tokens generated with secrets; only the SHA-256 hash of a token is stored,
so a database leak does not leak usable session tokens. Sessions are bound
to exactly one tenant and one user, expire after at most 12 hours per the
contract, and can be revoked on logout or password change.
"""

import hashlib
import hmac
import secrets
import time

from .errors import AuthenticationFailed, ValidationFailed
from .ids import generate_prefixed_id
from .models import Session, User, now_iso

PBKDF2_ITERATIONS = 210_000
SESSION_TTL_SECONDS = 12 * 60 * 60
_MIN_PASSWORD_LENGTH = 10


def hash_password(password, iterations=PBKDF2_ITERATIONS):
    if not isinstance(password, str) or len(password) < _MIN_PASSWORD_LENGTH:
        raise ValidationFailed(
            f"password must be at least {_MIN_PASSWORD_LENGTH} characters",
            fields={"password": "too_short"})
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return salt.hex(), digest.hex(), iterations


def verify_password(password, user):
    if not user.password_salt or not user.password_hash:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"),
        bytes.fromhex(user.password_salt), user.password_iterations)
    return hmac.compare_digest(digest.hex(), user.password_hash)


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, store, clock=time.time, session_ttl=SESSION_TTL_SECONDS):
        self.store = store
        self.clock = clock
        self.session_ttl = session_ttl

    def create_user(self, tenant_id, email, password, role):
        salt, digest, iterations = hash_password(password)
        user = User(
            id=generate_prefixed_id("user_"), tenant_id=tenant_id,
            email=email, role=role, password_salt=salt,
            password_hash=digest, password_iterations=iterations)
        return self.store.create_user(user)

    def login(self, email, password):
        """Authenticate by email and password.

        The failure message is identical for an unknown email and a wrong
        password, per the contract. The returned session is bound to the
        user's own tenant only; there is no way to log in "into" another
        tenant, because tenant scope comes from the user record itself.
        Returns (session_token, session, user).
        """
        user = self.store.find_user_by_email(email or "")
        if user is None or user.status != "active" or not verify_password(password or "", user):
            raise AuthenticationFailed("email or password is not correct")
        tenant = self.store.get_tenant(user.tenant_id)
        if tenant is None or tenant.status == "deleted":
            raise AuthenticationFailed("email or password is not correct")
        token = "sess_" + secrets.token_urlsafe(32)
        now = self.clock()
        session = Session(
            id=generate_prefixed_id("sessrec_"), tenant_id=user.tenant_id,
            user_id=user.id, token_hash=_token_hash(token),
            created_at_epoch=now, expires_at_epoch=now + self.session_ttl)
        self.store.put_session(session)
        user.last_login_at = now_iso()
        self.store.update_user(user)
        return token, session, user

    def authenticate(self, token):
        """Resolve a session token to (session, user) or raise 401.

        Expired and revoked sessions fail. The session's tenant is the
        only tenant scope the caller may act in.
        """
        if not token:
            raise AuthenticationFailed("no session token supplied")
        session = self.store.get_session_by_token_hash(_token_hash(token))
        if session is None or session.revoked:
            raise AuthenticationFailed("session is not valid")
        if self.clock() >= session.expires_at_epoch:
            raise AuthenticationFailed("session has expired")
        user = self.store.get_user(session.tenant_id, session.user_id)
        if user is None or user.status != "active":
            raise AuthenticationFailed("session is not valid")
        return session, user

    def logout(self, token):
        if not token:
            return False
        session = self.store.get_session_by_token_hash(_token_hash(token))
        if session is None:
            return False
        session.revoked = True
        self.store.update_session(session)
        return True

    def change_password(self, tenant_id, user_id, current_password, new_password):
        user = self.store.get_user(tenant_id, user_id)
        if user is None:
            raise AuthenticationFailed("user is not valid")
        if not verify_password(current_password or "", user):
            raise AuthenticationFailed("current password is not correct")
        salt, digest, iterations = hash_password(new_password)
        user.password_salt = salt
        user.password_hash = digest
        user.password_iterations = iterations
        self.store.update_user(user)
        self.store.delete_sessions_for_user(tenant_id, user_id)
        return user
