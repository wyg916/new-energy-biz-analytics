"""Apply the clean-volume knowledge baseline through governed identity and secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.core.database import SessionLocal
from app.governance.identity import IdentityService
from app.governance.secrets import CredentialReferenceService
from scripts import apply_knowledge_baseline_v1


PRINCIPAL_ID = "PRN-INTEGRATION-KNOWLEDGE-BOOTSTRAP"
USERNAME = "integration.knowledge-bootstrap"
REFERENCE_NAME = "preprod-knowledge-bootstrap-password"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--oidc-login-base", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with SessionLocal() as db:
        identity = IdentityService(db).resolve_oidc_session(
            principal_id=PRINCIPAL_ID,
            groups=("analysts",),
            request_id="REQ-INTEGRATION-KNOWLEDGE-BOOTSTRAP",
        )
        credentials = CredentialReferenceService(db, identity)
        reference = credentials.active_by_name(REFERENCE_NAME)
        secret = credentials.resolve(
            reference.credential_ref_id,
            action="knowledge.bootstrap.authenticate",
            trace_id="TRACE-INTEGRATION-KNOWLEDGE-BOOTSTRAP",
        )

    previous = os.environ.get("P4_OIDC_PASSWORD")
    os.environ["P4_OIDC_PASSWORD"] = secret.value
    try:
        apply_knowledge_baseline_v1.main([
            "--api-base", args.api_base,
            "--oidc-login-base", args.oidc_login_base,
            "--username", USERNAME,
            "--output", str(args.output),
        ])
    finally:
        if previous is None:
            os.environ.pop("P4_OIDC_PASSWORD", None)
        else:
            os.environ["P4_OIDC_PASSWORD"] = previous
        secret = None

    evidence = json.loads(args.output.read_text(encoding="utf-8"))
    evidence["bootstrap_governance"] = {
        "principal": USERNAME,
        "principal_id": PRINCIPAL_ID,
        "role": "analyst_admin",
        "credential_reference_id": reference.credential_ref_id,
        "credential_provider": reference.provider,
        "credential_usage_audited": True,
        "secret_recorded": False,
        "direct_database_insert": False,
    }
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "PASS",
        "principal": USERNAME,
        "credential_provider": reference.provider,
        "documents": evidence["documents"]["published"],
        "published_chunks": evidence["runtime"]["published_chunk_count"],
        "indexed_chunks": evidence["runtime"]["indexed_chunk_count"],
        "secret_recorded": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
