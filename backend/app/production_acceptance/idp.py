from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CANONICAL_CLAIMS = ("subject", "groups", "roles", "tenant", "workspace", "user_status")


class EnterpriseIdPConfig(BaseModel):
    """Secret-free enterprise OIDC acceptance configuration."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["p5-enterprise-idp-v1"] = "p5-enterprise-idp-v1"
    provider_code: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{2,63}$")
    issuer: str = Field(min_length=8, max_length=500)
    metadata_url: str = Field(min_length=8, max_length=500)
    client_id: str = Field(min_length=3, max_length=160)
    redirect_uri: str = Field(min_length=8, max_length=500)
    allowed_issuers: tuple[str, ...] = Field(min_length=1, max_length=1)
    scopes: tuple[str, ...] = Field(min_length=1, max_length=16)
    claim_mapping: dict[str, str]
    disabled_user_values: tuple[str, ...] = Field(min_length=1, max_length=16)
    clock_skew_seconds: int = Field(ge=0, le=120)
    jwks_cache_ttl_seconds: int = Field(ge=30, le=900)
    require_pkce_s256: bool = True
    require_session_revocation: bool = True

    @field_validator("issuer", "metadata_url", "redirect_uri")
    @classmethod
    def https_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("enterprise OIDC URLs must be absolute HTTPS URLs without credentials or fragments")
        return value.rstrip("/") if parsed.path in {"", "/"} else value

    @model_validator(mode="after")
    def validate_contract(self):
        if self.allowed_issuers != (self.issuer,):
            raise ValueError("exactly one allowed issuer matching issuer is required")
        if "openid" not in self.scopes:
            raise ValueError("openid scope is required")
        if set(self.claim_mapping) != set(CANONICAL_CLAIMS):
            raise ValueError("claim mapping must define the complete canonical claim set")
        mapped = list(self.claim_mapping.values())
        if any(not item or len(item) > 128 for item in mapped) or len(set(mapped)) != len(mapped):
            raise ValueError("mapped claims must be non-empty, bounded and unique")
        return self


class EnterpriseIdPMetadataError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_provider_metadata(config: EnterpriseIdPConfig, metadata: dict) -> dict:
    """Validate supplied discovery metadata without performing an external request."""

    if metadata.get("issuer") != config.issuer:
        raise EnterpriseIdPMetadataError("ENTERPRISE_IDP_ISSUER_MISMATCH", "Provider metadata issuer 不匹配")
    required_endpoints = ["authorization_endpoint", "token_endpoint", "jwks_uri"]
    if config.require_session_revocation:
        required_endpoints.extend(["end_session_endpoint", "revocation_endpoint"])
    endpoints: dict[str, str] = {}
    for name in required_endpoints:
        value = metadata.get(name)
        parsed = urlparse(str(value or ""))
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise EnterpriseIdPMetadataError("ENTERPRISE_IDP_METADATA_INVALID", f"{name} 必须是无凭据 HTTPS URL")
        endpoints[name] = str(value)
    if "code" not in metadata.get("response_types_supported", []):
        raise EnterpriseIdPMetadataError("ENTERPRISE_IDP_CODE_FLOW_UNSUPPORTED", "Provider 不支持 Authorization Code")
    if config.require_pkce_s256 and "S256" not in metadata.get("code_challenge_methods_supported", []):
        raise EnterpriseIdPMetadataError("ENTERPRISE_IDP_PKCE_UNSUPPORTED", "Provider 不支持 PKCE S256")
    algorithms = set(metadata.get("id_token_signing_alg_values_supported", []))
    if "RS256" not in algorithms:
        raise EnterpriseIdPMetadataError("ENTERPRISE_IDP_SIGNING_ALGORITHM_UNSUPPORTED", "Provider 未声明 RS256")
    return {
        "status": "VALIDATED_CONFIGURATION",
        "provider_code": config.provider_code,
        "issuer": config.issuer,
        "allowed_issuer_count": 1,
        "endpoints_validated": sorted(endpoints),
        "claims_mapped": sorted(config.claim_mapping),
        "pkce_method": "S256",
        "clock_skew_seconds": config.clock_skew_seconds,
        "jwks_rotation": "refresh_on_unknown_kid_with_bounded_cache",
        "session_revocation_required": config.require_session_revocation,
        "external_enterprise_idp": "CONDITIONAL",
        "secret_value_exposed": False,
    }
