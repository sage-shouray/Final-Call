"""Encryption for credentials held on behalf of customers.

Mailbox passwords and OAuth client secrets belong to the customer, not to us,
and this table holds one set per tenant. A database dump, a backup on a laptop,
or a support engineer with read access should not hand over every customer's
mail credentials at once — so they are encrypted at rest rather than stored the
way SAP_PASSWORD currently sits in .env.

Fernet (AES-128-CBC with an HMAC) is used because it is authenticated: tampering
with the ciphertext fails loudly instead of decrypting to rubbish.
"""
from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken

from src.config import settings

log = structlog.get_logger(__name__)


class SecretUnavailable(RuntimeError):
    """Raised when a secret cannot be decrypted with the configured key."""


@lru_cache(maxsize=1)
def _cipher() -> Fernet:
    """Build the cipher from SECRET_ENCRYPTION_KEY, or fall back to SECRET_KEY.

    Fernet needs 32 url-safe base64 bytes. A dedicated key is preferred; the
    fallback derives one from SECRET_KEY so the feature works out of the box in
    development without silently accepting a blank key in production.
    """
    configured = (settings.SECRET_ENCRYPTION_KEY.get_secret_value() or "").strip()
    if configured:
        try:
            Fernet(configured.encode())
            return Fernet(configured.encode())
        except Exception:
            # Not a valid Fernet key — treat it as key material and derive one.
            derived = base64.urlsafe_b64encode(hashlib.sha256(configured.encode()).digest())
            return Fernet(derived)

    base = settings.SECRET_KEY.get_secret_value()
    if settings.is_production and base == "change-me-in-production":
        raise SecretUnavailable(
            "Refusing to encrypt customer credentials with the default SECRET_KEY. "
            "Set SECRET_ENCRYPTION_KEY."
        )
    log.warning("SECRET_ENCRYPTION_KEY not set — deriving a key from SECRET_KEY")
    derived = base64.urlsafe_b64encode(hashlib.sha256(base.encode()).digest())
    return Fernet(derived)


def encrypt_dict(payload: dict[str, Any]) -> str:
    """Encrypt a credential mapping into an opaque string for storage."""
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return _cipher().encrypt(raw).decode()


def decrypt_dict(blob: str) -> dict[str, Any]:
    """Reverse of encrypt_dict.

    A failure here almost always means the encryption key changed after the
    credentials were written, so the message says so rather than leaving someone
    hunting a corrupt-data theory.
    """
    if not blob:
        return {}
    try:
        return json.loads(_cipher().decrypt(blob.encode()).decode())
    except InvalidToken as exc:
        raise SecretUnavailable(
            "Stored credentials could not be decrypted — the encryption key has "
            "changed since they were saved. Re-enter them."
        ) from exc


def generate_key() -> str:
    """A fresh Fernet key, for putting in SECRET_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode()
