"""CredentialReference adapters for SQLBot's constrained local account policy."""

from __future__ import annotations

import base64
import hashlib
import hmac


_DOMAIN = b"renewable-platform/sqlbot-runtime-account/v1"


def derive_runtime_account_password(reference_value: str) -> str:
    """Return a stable 20-character SQLBot-compliant account password.

    SQLBot v1.10 requires mixed-case, digit and punctuation and limits passwords
    to 20 characters. Governed CredentialReference values are opaque and may not
    satisfy that local policy. A domain-separated one-way derivation keeps the
    CredentialReference authoritative, supports rotation, and avoids persisting
    either the source or derived secret in repository/runtime configuration.
    """

    if not reference_value:
        raise ValueError("CredentialReference password is empty")
    digest = hmac.new(_DOMAIN, reference_value.encode("utf-8"), hashlib.sha256).digest()
    suffix = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:16]
    return f"Sb1!{suffix}"
