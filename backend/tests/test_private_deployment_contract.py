from __future__ import annotations

import importlib.util
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "private_deployment.py"


def load_private_deployment_module():
    spec = importlib.util.spec_from_file_location("private_deployment", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_restore_stream_remaps_schema_without_mutating_copy_data():
    module = load_private_deployment_module()
    source = BytesIO(
        b"CREATE TABLE public.sample (value text);\n"
        b"COPY public.sample (value) FROM stdin;\n"
        b"business value public.ev_order must remain unchanged\n"
        b"\\.\n"
        b"ALTER TABLE public.sample ADD PRIMARY KEY (value);\n"
    )
    destination = BytesIO()
    module.PrivateDeployment.transform_restore_stream(
        source,
        destination,
        "rc_restore_contract",
    )
    restored = destination.getvalue()
    assert b'CREATE TABLE "rc_restore_contract".sample' in restored
    assert b'COPY "rc_restore_contract".sample' in restored
    assert b"business value public.ev_order must remain unchanged" in restored
    assert b'ALTER TABLE "rc_restore_contract".sample' in restored


def test_private_compose_keeps_database_and_api_private():
    compose = (ROOT / "deploy" / "private" / "docker-compose.private.yml").read_text(
        encoding="utf-8"
    )
    db_section, rest = compose.split("\n  redis:", 1)
    redis_section, rest = rest.split("\n  api:", 1)
    api_section, web_section = rest.split("\n  web:", 1)
    assert "\n    ports:" not in db_section
    assert "\n    ports:" not in redis_section
    assert "\n    ports:" not in api_section
    assert 'APP_ENV: production' in api_section
    assert 'AUTO_BOOTSTRAP_DEMO_USERS: "false"' in api_section
    assert "\n    ports:" in web_section


def test_private_proxy_enforces_https_and_hides_metrics():
    nginx = (ROOT / "deploy" / "private" / "nginx.private.conf").read_text(
        encoding="utf-8"
    )
    assert "return 308 https://" in nginx
    assert "ssl_protocols TLSv1.2 TLSv1.3" in nginx
    assert "location = /api/v1/metrics" in nginx
    assert "return 404;" in nginx
    assert "X-Request-ID" in nginx
