from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.production_acceptance.idp import (
    EnterpriseIdPConfig,
    EnterpriseIdPMetadataError,
    validate_provider_metadata,
)


pytestmark = pytest.mark.no_db


def config_payload() -> dict:
    return {
        "provider_code": "ENTERPRISE_OIDC",
        "issuer": "https://idp.example.test/tenant/v2.0",
        "metadata_url": "https://idp.example.test/tenant/v2.0/.well-known/openid-configuration",
        "client_id": "chatbi-client",
        "redirect_uri": "https://chatbi.example.test/oidc/callback",
        "allowed_issuers": ["https://idp.example.test/tenant/v2.0"],
        "scopes": ["openid", "profile", "email"],
        "claim_mapping": {
            "subject": "sub",
            "groups": "groups",
            "roles": "roles",
            "tenant": "tenant_id",
            "workspace": "workspace_id",
            "user_status": "account_status",
        },
        "disabled_user_values": ["disabled", "terminated"],
        "clock_skew_seconds": 30,
        "jwks_cache_ttl_seconds": 300,
        "require_pkce_s256": True,
        "require_session_revocation": True,
    }


def metadata_payload() -> dict:
    issuer = config_payload()["issuer"]
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "jwks_uri": f"{issuer}/keys",
        "end_session_endpoint": f"{issuer}/logout",
        "revocation_endpoint": f"{issuer}/revoke",
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


def test_enterprise_idp_template_contract_validates_without_external_call() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    template_path = repository_root / "deploy" / "production-acceptance" / "enterprise-idp.template.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert EnterpriseIdPConfig(**template).schema_version == "p5-enterprise-idp-v1"
    result = validate_provider_metadata(
        EnterpriseIdPConfig(**config_payload()),
        metadata_payload(),
    )
    assert result["status"] == "VALIDATED_CONFIGURATION"
    assert result["external_enterprise_idp"] == "CONDITIONAL"
    assert result["allowed_issuer_count"] == 1
    assert result["secret_value_exposed"] is False


@pytest.mark.parametrize("field", ["authorization_endpoint", "token_endpoint", "jwks_uri"])
def test_metadata_requires_https_and_rejects_embedded_credentials(field: str) -> None:
    metadata = metadata_payload()
    metadata[field] = "https://user:password@idp.example.test/unsafe"
    with pytest.raises(EnterpriseIdPMetadataError, match="HTTPS"):
        validate_provider_metadata(EnterpriseIdPConfig(**config_payload()), metadata)


def test_multi_issuer_and_wrong_issuer_fail_closed() -> None:
    config = config_payload()
    config["allowed_issuers"].append("https://second-issuer.example.test")
    with pytest.raises(ValidationError, match="at most 1 item"):
        EnterpriseIdPConfig(**config)

    metadata = metadata_payload()
    metadata["issuer"] = "https://attacker.example.test"
    with pytest.raises(EnterpriseIdPMetadataError) as exc:
        validate_provider_metadata(EnterpriseIdPConfig(**config_payload()), metadata)
    assert exc.value.code == "ENTERPRISE_IDP_ISSUER_MISMATCH"


def test_missing_pkce_revocation_and_canonical_claims_fail_closed() -> None:
    metadata = metadata_payload()
    metadata["code_challenge_methods_supported"] = ["plain"]
    with pytest.raises(EnterpriseIdPMetadataError) as exc:
        validate_provider_metadata(EnterpriseIdPConfig(**config_payload()), metadata)
    assert exc.value.code == "ENTERPRISE_IDP_PKCE_UNSUPPORTED"

    no_revocation = deepcopy(metadata_payload())
    no_revocation.pop("revocation_endpoint")
    with pytest.raises(EnterpriseIdPMetadataError, match="revocation_endpoint"):
        validate_provider_metadata(EnterpriseIdPConfig(**config_payload()), no_revocation)

    config = config_payload()
    config["claim_mapping"].pop("workspace")
    with pytest.raises(ValidationError, match="complete canonical claim set"):
        EnterpriseIdPConfig(**config)
