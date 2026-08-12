import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.ai.model_gateway.errors import CredentialReferenceError, CredentialUnavailableError

_ENV_REF = re.compile(r"^env://(?P<name>[A-Z][A-Z0-9_]{2,127})$")
_FILE_REF = re.compile(
    r"^file:///run/provider-credentials/(?P<alias>kimi|mimo|deepseek)$"
)


@dataclass(frozen=True, repr=False)
class ResolvedCredential:
    value: str

    def __repr__(self) -> str:
        return "ResolvedCredential(value='[REDACTED]')"


class CredentialResolver:
    """Resolve allow-listed runtime references without persisting secret values."""

    def __init__(self, file_root: Path | None = None) -> None:
        self._file_root = file_root or Path("/run/provider-credentials")

    def resolve(self, reference: str | None) -> ResolvedCredential | None:
        if reference is None:
            return None
        match = _ENV_REF.fullmatch(reference)
        if match is not None:
            value = os.getenv(match.group("name"))
            if not value:
                raise CredentialUnavailableError(
                    "referenced runtime credential is unavailable"
                )
            return ResolvedCredential(value=value)
        file_match = _FILE_REF.fullmatch(reference)
        if file_match is None:
            raise CredentialReferenceError(
                "only allow-listed runtime credential references are allowed"
            )
        root = self._file_root.resolve()
        target = (root / file_match.group("alias")).resolve()
        if target.parent != root or not target.is_file():
            raise CredentialUnavailableError(
                "referenced runtime credential is unavailable"
            )
        value = target.read_text(encoding="utf-8").strip()
        if not value:
            raise CredentialUnavailableError("referenced runtime credential is unavailable")
        if "\n" in value or "\r" in value:
            raise CredentialUnavailableError("referenced runtime credential is unavailable")
        return ResolvedCredential(value=value)


def redact_sensitive(value: object) -> str:
    """Return a safe diagnostic string; model payloads and credentials are never logged."""

    if isinstance(value, BaseException):
        return f"{type(value).__name__}: provider request failed"
    return "[REDACTED]"
