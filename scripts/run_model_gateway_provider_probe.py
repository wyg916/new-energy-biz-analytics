"""Exercise the project Provider Adapters against approved runtime credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai.model_gateway.client import (  # noqa: E402
    DeepSeekProvider,
    KimiProvider,
    MiMoProvider,
)
from app.ai.model_gateway.contracts import (  # noqa: E402
    DataClassification,
    GatewayMessage,
    GatewayRequest,
    ModelConfig,
    RetryPolicy,
    TaskType,
)


PROVIDERS = {
    "kimi": (KimiProvider, "https://api.moonshot.cn/v1", "kimi-k2.6"),
    "mimo": (MiMoProvider, "https://api.xiaomimimo.com/v1", "mimo-v2.5"),
    "deepseek": (DeepSeekProvider, "https://api.deepseek.com", "deepseek-v4-flash"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for alias, (provider_class, base_url, model_name) in PROVIDERS.items():
        credential = (args.credential_dir / alias).read_text(encoding="utf-8").strip()
        if not credential.startswith("sk-") or "\n" in credential or "\r" in credential:
            raise RuntimeError(f"{alias} runtime credential is invalid")
        env_name = f"MODEL_GATEWAY_PROBE_{alias.upper()}"
        os.environ[env_name] = credential
        config = ModelConfig(
            config_id=f"{alias}-rag-probe",
            provider=alias,
            base_url=base_url,
            model_name=model_name,
            credential_ref=f"env://{env_name}",
            task_type=TaskType.RAG_ANSWER_GENERATION,
            data_classification=frozenset({DataClassification.SIMULATED}),
            timeout_seconds=30,
            max_tokens=64,
            temperature=0,
            retry_policy=RetryPolicy(max_retries=0),
            enabled=True,
        )
        request = GatewayRequest(
            task_type=TaskType.RAG_ANSWER_GENERATION,
            messages=(GatewayMessage(
                role="user",
                content="Return a short answer confirming the adapter can respond.",
            ),),
            data_classification=DataClassification.SIMULATED,
            trace_id=f"integration41full-{alias}-adapter-probe",
            run_id="integration41full-provider-recovery",
        )
        started = perf_counter()
        try:
            response = provider_class().complete(config, request)
            response_valid = bool(response.content.strip())
            row = {
                "provider": alias,
                "model": model_name,
                "task_type": TaskType.RAG_ANSWER_GENERATION,
                "data_classification": DataClassification.SIMULATED,
                "credential_ref": f"runtime-file://provider-credentials/{alias}",
                "credential_fingerprint_sha256_12": hashlib.sha256(
                    credential.encode("utf-8")
                ).hexdigest()[:12],
                "response_valid": response_valid,
                "finish_reason_present": response.finish_reason is not None,
                "latency_ms": round((perf_counter() - started) * 1000),
                "status": "PASS" if response_valid else "FAIL",
            }
        except Exception as exc:
            row = {
                "provider": alias,
                "model": model_name,
                "task_type": TaskType.RAG_ANSWER_GENERATION,
                "data_classification": DataClassification.SIMULATED,
                "credential_ref": f"runtime-file://provider-credentials/{alias}",
                "credential_fingerprint_sha256_12": hashlib.sha256(
                    credential.encode("utf-8")
                ).hexdigest()[:12],
                "response_valid": False,
                "latency_ms": round((perf_counter() - started) * 1000),
                "error_type": type(exc).__name__,
                "status": "FAIL",
            }
        finally:
            os.environ.pop(env_name, None)
            credential = ""
        rows.append(row)
    report = {
        "evidence_type": "integration41full_model_gateway_provider_probe",
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        "providers": rows,
        "response_content_exposed": False,
        "secret_values_exposed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
