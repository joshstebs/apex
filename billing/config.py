"""Billing configuration for ApexVoice.

Test mode only. This module loads configuration from an env style dict,
refuses any live mode configuration, and never prints or logs secret values.
Keys are referenced by environment variable name. Values, when present, are
held in memory for the caller that owns them and are redacted from repr.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional


class BillingModeError(RuntimeError):
    """Raised when a non test billing configuration is attempted."""


MODE_ENV = "APEX_BILLING_MODE"
SECRET_KEY_ENV = "STRIPE_SECRET_KEY"
PUBLISHABLE_KEY_ENV = "STRIPE_PUBLISHABLE_KEY"
WEBHOOK_SECRET_ENV = "STRIPE_WEBHOOK_SECRET"

_LIVE_PREFIXES = ("sk_live_", "rk_live_", "pk_live_", "whsec_live_")


@dataclass
class BillingConfig:
    """Billing settings for one deployment.

    Secret values are excluded from repr. Only the names of the environment
    variables that supplied them, and whether they are set, are ever shown.
    """

    mode: str = "test"
    secret_key_env: str = SECRET_KEY_ENV
    publishable_key_env: str = PUBLISHABLE_KEY_ENV
    webhook_secret_env: str = WEBHOOK_SECRET_ENV
    _secret_key: Optional[str] = field(default=None, repr=False)
    _publishable_key: Optional[str] = field(default=None, repr=False)
    _webhook_secret: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.mode != "test":
            raise BillingModeError(
                "ApexVoice billing is test mode only. "
                f"Refusing mode {self.mode!r}. Live billing is not approved."
            )
        for label, value in (
            ("secret key", self._secret_key),
            ("publishable key", self._publishable_key),
            ("webhook secret", self._webhook_secret),
        ):
            if value and value.startswith(_LIVE_PREFIXES):
                raise BillingModeError(
                    f"A live Stripe {label} was supplied. "
                    "Test mode requires test keys only."
                )

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "BillingConfig":
        """Build a config from an env style mapping.

        Pass an explicit dict in tests and tooling. When env is None an empty
        mapping is used, so this module never reads the real process
        environment implicitly and never touches the network.
        """
        source: Mapping[str, str] = env if env is not None else {}
        mode = (source.get(MODE_ENV) or "test").strip().lower()
        if mode != "test":
            raise BillingModeError(
                "ApexVoice billing is test mode only. "
                f"{MODE_ENV}={mode!r} is not allowed. Live billing is not approved."
            )
        return cls(
            mode=mode,
            _secret_key=source.get(SECRET_KEY_ENV) or None,
            _publishable_key=source.get(PUBLISHABLE_KEY_ENV) or None,
            _webhook_secret=source.get(WEBHOOK_SECRET_ENV) or None,
        )

    @property
    def secret_key(self) -> Optional[str]:
        return self._secret_key

    @property
    def publishable_key(self) -> Optional[str]:
        return self._publishable_key

    @property
    def webhook_secret(self) -> Optional[str]:
        return self._webhook_secret

    @property
    def is_configured(self) -> bool:
        """True when the keys needed for test mode calls are present."""
        return bool(self._secret_key and self._webhook_secret)

    def __repr__(self) -> str:
        return (
            "BillingConfig(mode='test', "
            f"secret_key_env={self.secret_key_env!r}, secret_key_set={bool(self._secret_key)}, "
            f"publishable_key_env={self.publishable_key_env!r}, publishable_key_set={bool(self._publishable_key)}, "
            f"webhook_secret_env={self.webhook_secret_env!r}, webhook_secret_set={bool(self._webhook_secret)})"
        )

    __str__ = __repr__
