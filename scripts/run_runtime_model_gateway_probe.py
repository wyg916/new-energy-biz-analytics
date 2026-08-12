"""Call every Full Integration ModelGateway registration with runtime references."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from app.ai.model_gateway.contracts import (
    DataClassification,
    GatewayMessage,
    GatewayRequest,
    TaskType,
)
from app.ai.model_gateway.runtime import get_runtime_model_gateway, runtime_model_status


CONFIGS = {
    "kimi": "kimi-rag-primary",
    "mimo": "mimo-rag-standby",
    "deepseek": "deepseek-rag-fallback",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    gateway = get_runtime_model_gateway()
    registration = runtime_model_status()
    rows = []
    for alias, config_id in CONFIGS.items():
        request = GatewayRequest(
            task_type=TaskType.RAG_ANSWER_GENERATION,
            messages=(GatewayMessage(
                role="user",
                content="Return a short answer confirming this registered route responds.",
            ),),
            data_classification=DataClassification.PUBLIC,
            trace_id=f"integration41full-runtime-{alias}-probe",
            run_id="integration41full-safe-degraded-closeout",
        )
        started = perf_counter()
        try:
            response = gateway.complete_with_config(config_id, request)
            valid = bool(response.content.strip()) and response.provider == alias
            rows.append({
                "provider": alias,
                "config_id": config_id,
                "model": response.model_name,
                "response_valid": valid,
                "latency_ms": round((perf_counter() - started) * 1000),
                "status": "PASS" if valid else "FAIL",
            })
        except Exception as exc:
            rows.append({
                "provider": alias,
                "config_id": config_id,
                "response_valid": False,
                "latency_ms": round((perf_counter() - started) * 1000),
                "error_type": type(exc).__name__,
                "status": "FAIL",
            })
    passed = (
        registration["status"] == "READY"
        and len(registration["providers"]) == 3
        and all(row["status"] == "PASS" for row in rows)
    )
    payload = {
        "schema_version": "1.0",
        "evidence_type": "integration41full_runtime_model_gateway_probe",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if passed else "FAIL",
        "registration": registration,
        "providers": rows,
        "task_type": TaskType.RAG_ANSWER_GENERATION,
        "response_content_exposed": False,
        "secret_values_exposed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
