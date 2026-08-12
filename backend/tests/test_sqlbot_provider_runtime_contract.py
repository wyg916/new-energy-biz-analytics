import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_db


def _load(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_three_sqlbot_provider_candidates_use_frozen_protocols() -> None:
    module = _load(
        "provision_model_runtime_api",
        "deploy/sqlbot/provision_model_runtime_api.py",
    )
    expected = {
        "deepseek": ("deepseek-v4-flash", "https://api.deepseek.com", 0),
        "kimi": ("kimi-k2.6", "https://api.moonshot.cn/v1", 0.6),
        "mimo": ("mimo-v2.5", "https://api.xiaomimimo.com/v1", 1.0),
    }
    for provider, (model, endpoint, temperature) in expected.items():
        item = module.ProviderInput(provider, "test-key", endpoint, model, "fingerprint")
        candidate = module._candidate(item)
        config = {row["key"]: row["val"] for row in candidate["config_list"]}
        assert candidate["base_model"] == model
        assert candidate["api_domain"] == endpoint
        assert candidate["protocol"] == 1
        assert config["temperature"] == temperature
        assert config["max_retries"] == 0
        assert config["timeout"] == 12
        assert config["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "max_completion_tokens" in {
        row["key"] for row in module._candidate(module.ProviderInput(
            "mimo", "test-key", expected["mimo"][1], expected["mimo"][0], "fingerprint"
        ))["config_list"]
    }


def test_sqlbot_wrapper_has_narrow_mimo_api_key_adapter() -> None:
    source = (ROOT / "deploy/sqlbot/sqlbot41_runtime.py").read_text(encoding="utf-8")
    assert 'MIMO_API_DOMAIN = "https://api.xiaomimimo.com/v1"' in source
    assert 'default_headers={"api-key": self.config.api_key or ""}' in source
    assert 'api_key="mimo-runtime-api-key-header"' in source
