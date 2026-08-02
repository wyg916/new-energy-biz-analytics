"""Generate P4 runtime-only credentials and TLS material in a named volume.

No value is printed and no generated material is written to the repository.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _write_once(path: Path, value: str) -> bool:
    if path.exists():
        return False
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)
    return True


def _certificate(root: Path, *, hostname: str, label: str) -> bool:
    key_path = root / "tls_key.pem"
    cert_path = root / "tls_cert.pem"
    if key_path.exists() and cert_path.exists():
        return False
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, f"ChatBI {label} Isolated Acceptance"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(hostname), x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    key_path.write_bytes(private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(key_path, 0o600)
    os.chmod(cert_path, 0o644)
    return True


def _realm(root: Path, *, public_base_url: str, label: str) -> bool:
    realm_path = root / "keycloak_realm.json"
    if realm_path.exists():
        return False
    user_password = (root / "keycloak_user_password").read_text(encoding="utf-8").strip()
    realm = {
        "realm": "chatbi",
        "enabled": True,
        "displayName": f"ChatBI {label} Acceptance",
        "sslRequired": "external",
        "registrationAllowed": False,
        "resetPasswordAllowed": False,
        "loginWithEmailAllowed": True,
        "bruteForceProtected": True,
        "groups": [{"name": "analysts"}],
        "clients": [{
            "clientId": "chatbi-web",
            "name": "ChatBI Web",
            "enabled": True,
            "publicClient": True,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "redirectUris": [f"{public_base_url}/oidc/callback"],
            "webOrigins": [public_base_url],
            "attributes": {"pkce.code.challenge.method": "S256"},
            "protocolMappers": [
                {"name": "audience", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
                 "config": {"included.client.audience": "chatbi-web", "id.token.claim": "true", "access.token.claim": "true"}},
                {"name": "tenant", "protocol": "openid-connect", "protocolMapper": "oidc-hardcoded-claim-mapper", "consentRequired": False,
                 "config": {"claim.name": "tenant_id", "claim.value": "tenant-alpha", "jsonType.label": "String", "id.token.claim": "true"}},
                {"name": "workspace", "protocol": "openid-connect", "protocolMapper": "oidc-hardcoded-claim-mapper", "consentRequired": False,
                 "config": {"claim.name": "workspace_id", "claim.value": "workspace-alpha", "jsonType.label": "String", "id.token.claim": "true"}},
                {"name": "groups", "protocol": "openid-connect", "protocolMapper": "oidc-group-membership-mapper", "consentRequired": False,
                 "config": {"claim.name": "groups", "full.path": "false", "id.token.claim": "true", "access.token.claim": "true"}},
            ],
        }],
        "users": [
            {
                "id": "11111111-1111-4111-8111-111111111111", "username": "p4.analyst", "enabled": True,
                "emailVerified": True, "email": "p4.analyst@example.invalid", "firstName": "P4", "lastName": "Analyst",
                "groups": ["/analysts"], "credentials": [{"type": "password", "value": user_password, "temporary": False}],
            },
            {
                "id": "22222222-2222-4222-8222-222222222222", "username": "p4.disabled", "enabled": False,
                "emailVerified": True, "email": "p4.disabled@example.invalid", "firstName": "P4", "lastName": "Disabled",
                "credentials": [{"type": "password", "value": user_password, "temporary": False}],
            },
            {
                "id": "33333333-3333-4333-8333-333333333333", "username": "p4.unmapped", "enabled": True,
                "emailVerified": True, "email": "p4.unmapped@example.invalid", "firstName": "P4", "lastName": "Unmapped",
                "credentials": [{"type": "password", "value": user_password, "temporary": False}],
            },
        ],
    }
    realm_path.write_text(json.dumps(realm, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(realm_path, 0o600)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, default=Path("/run/p4-runtime"))
    parser.add_argument("--keycloak-dir", type=Path, default=Path("/run/p4-keycloak"))
    parser.add_argument(
        "--public-base-url",
        default=os.getenv("ACCEPTANCE_PUBLIC_BASE_URL", "https://p4.localhost:8444"),
    )
    parser.add_argument("--label", default=os.getenv("ACCEPTANCE_LABEL", "P4 Preproduction"))
    args = parser.parse_args()
    parsed_base_url = urlparse(args.public_base_url)
    if parsed_base_url.scheme != "https" or not parsed_base_url.hostname or parsed_base_url.path.rstrip("/"):
        parser.error("public base URL must be an HTTPS origin without a path")
    public_base_url = args.public_base_url.rstrip("/")
    args.runtime_dir.mkdir(parents=True, exist_ok=True)
    # Service-specific files remain 0600; the directory must be traversable by
    # the Redis runtime before it can read its dedicated configuration file.
    os.chmod(args.runtime_dir, 0o755)
    args.keycloak_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(args.keycloak_dir, 0o755)
    created = {
        "postgres_password": _write_once(args.runtime_dir / "postgres_password", secrets.token_urlsafe(36)),
        "redis_password": _write_once(args.runtime_dir / "redis_password", secrets.token_urlsafe(36)),
        "application_signing_key": _write_once(args.runtime_dir / "application_signing_key", secrets.token_urlsafe(64)),
        "keycloak_admin_password": _write_once(args.keycloak_dir / "keycloak_admin_password", secrets.token_urlsafe(36)),
        "keycloak_user_password": _write_once(args.keycloak_dir / "keycloak_user_password", secrets.token_urlsafe(24)),
        "tls_material": _certificate(
            args.runtime_dir, hostname=parsed_base_url.hostname, label=args.label,
        ),
    }
    redis_configuration = args.runtime_dir / "redis.conf"
    if not redis_configuration.exists():
        redis_configuration.write_text(
            "appendonly yes\nappendfsync everysec\nrequirepass "
            + (args.runtime_dir / "redis_password").read_text(encoding="utf-8").strip()
            + "\n",
            encoding="utf-8",
        )
        os.chmod(redis_configuration, 0o644)
        created["redis_configuration"] = True
    else:
        created["redis_configuration"] = False
        os.chmod(redis_configuration, 0o644)
    database_password = (args.runtime_dir / "postgres_password").read_text(encoding="utf-8").strip()
    created["keycloak_database_password"] = _write_once(args.keycloak_dir / "postgres_password", database_password)
    for name in ("keycloak_admin_password", "keycloak_user_password", "postgres_password"):
        os.chmod(args.keycloak_dir / name, 0o640)
    created["keycloak_realm"] = _realm(
        args.keycloak_dir, public_base_url=public_base_url, label=args.label,
    )
    os.chmod(args.keycloak_dir / "keycloak_realm.json", 0o640)
    print(json.dumps({
        "status": "READY", "runtime_only": True, "repository_files_written": False,
        "secret_values_printed": False, "created": created,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
