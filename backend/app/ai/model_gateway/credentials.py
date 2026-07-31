import os
import re
from dataclasses import dataclass

from app.ai.model_gateway.errors import CredentialReferenceError, CredentialUnavailableError

_ENV_REF = re.compile(r"^env://(?P<name>[A-Z][A-Z0-9_]{2,127})$")


@dataclass(frozen=True, repr=False)
class ResolvedCredential:
    value: str

    def __repr__(self) -> str:
        return "ResolvedCredential(value='[REDACTED]')"


class CredentialResolver:
    """Resolve allow-listed runtime references without persisting secret values."""

    def resolve(self, reference: str | None) -> ResolvedCredential | None:
        if reference is None:
            return None
        match = _ENV_REF.fullmatch(reference)
        if match is None:
            raise CredentialReferenceError("only env:// credential references are allowed")
        value = os.getenv(match.group("name"))
        if not value:
            raise CredentialUnavailableError("referenced runtime credential is unavailable")
        return ResolvedCredential(value=value)


def redact_sensitive(value: object) -> str:
    """Return a safe diagnostic string; model payloads and credentials are never logged."""

    if isinstance(value, BaseException):
        return f"{type(value).__name__}: provider request failed"
    return "[REDACTED]"
