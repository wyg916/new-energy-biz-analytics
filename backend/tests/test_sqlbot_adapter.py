import json
import subprocess
import sys
from datetime import UTC, datetime

import httpx
import pytest

from app.platform.identity import IdentityContext
from app.platform.query_engine import QueryContext, QueryRequest
from app.query_engines.sqlbot.client import SQLBotClient
from app.query_engines.sqlbot.credentials import derive_runtime_account_password
from app.query_engines.sqlbot.engine import SQLBotEngine
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)
from app.query_engines.sqlbot.health import CircuitBreaker
from app.query_engines.sqlbot.response_parser import parse_response
from deploy.sqlbot.sync_credential_reference_runtime import synchronize

pytestmark = pytest.mark.no_db


def test_sqlbot_engine_direct_import_and_health_check_are_order_independent():
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.query_engines.sqlbot.engine import SQLBotEngine; "
                "result = SQLBotEngine(enabled=False).health_check(); "
                "assert result['status'] == 'DISABLED'"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert process.returncode == 0, process.stderr


def _identity(
    subject_id: str = "user:1",
    *,
    workspace_id: str = "workspace-a",
) -> IdentityContext:
    return IdentityContext(
        subject_id=subject_id,
        tenant_id="tenant-a",
        org_id="org-a",
        workspace_id=workspace_id,
        roles=("analyst",),
        groups=(),
        data_scopes=("workspace:all",),
        auth_strength="test",
        issued_at=datetime.now(UTC),
        request_id=f"request-{subject_id}-{workspace_id}",
    )


def _context(
    *,
    scenario: str = "sales_ops",
    execution_mode: str = "upstream_readonly",
) -> QueryContext:
    return QueryContext(
        conversation_id=f"conversation-{scenario}",
        scenario_version="1.0.0",
        semantic_version="1.0.0",
        semantic_model_version_id=f"semantic-{scenario}-1",
        dataset_version="1",
        dataset_version_id=f"dataset-{scenario}-1",
        datasource_id="42",
        allowed_relations={
            f"semantic_{scenario}_orders": (
                "order_id",
                "sales_revenue",
                "region",
            ),
        },
        execution_mode=execution_mode,
        max_rows=100,
    )


def _client(monkeypatch, handler, *, threshold: int = 3) -> SQLBotClient:
    monkeypatch.setenv("TEST_SQLBOT_USER", "service-user")
    monkeypatch.setenv("TEST_SQLBOT_PASSWORD", "service-password")
    return SQLBotClient(
        "http://sqlbot.test/api/v1",
        username_env_key="TEST_SQLBOT_USER",
        password_env_key="TEST_SQLBOT_PASSWORD",
        timeout_seconds=1,
        breaker=CircuitBreaker(threshold, recovery_seconds=300),
        transport=httpx.MockTransport(handler),
    )


def _platform_rows(*rows: dict):
    def execute(sql, request, context):
        del sql, request, context
        columns = tuple(rows[0]) if rows else ()
        return columns, tuple(rows)

    return execute


def test_adapter_normalizes_result_and_never_exposes_session_secret(monkeypatch) -> None:
    requests: list[dict] = []
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        payload = json.loads(request.content)
        requests.append(payload)
        if request.url.path.endswith("/mcp_start"):
            return httpx.Response(
                200,
                json={"access_token": "runtime-only-token", "chat_id": 101},
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "record_id": 9001,
                    "sql": (
                        "SELECT region, sales_revenue "
                        "FROM semantic_sales_ops_orders LIMIT 10"
                    ),
                    "rows": [{"region": "north", "sales_revenue": 123.45}],
                    "chart": {"type": "bar"},
                    "token_usage": {"total_tokens": 37},
                },
            },
        )

    engine = SQLBotEngine(
        enabled=True,
        runtime_verified=True,
        client=_client(monkeypatch, handler),
        generated_sql_executor=_platform_rows(
            {"region": "north", "sales_revenue": 123.45},
        ),
    )
    result = engine.execute(
        QueryRequest(
            question="按区域查看销售额",
            identity_context=_identity(),
            scenario_id="sales_ops",
        ),
        _context(),
    )

    assert result.engine == "sqlbot"
    assert result.scenario == "sales_ops"
    assert result.rows == ({"region": "north", "sales_revenue": 123.45},)
    assert result.evidence["token_usage"] == 37
    serialized = json.dumps(result.as_dict(), ensure_ascii=False)
    assert "runtime-only-token" not in serialized
    assert requests[1]["token"] == "runtime-only-token"
    assert requests[1]["chat_id"] == 101
    assert requests[1]["return_img"] is False
    assert "oid" not in requests[1]
    assert paths == [
        "/api/v1/mcp/mcp_start",
        "/api/v1/mcp/mcp_generate_sql",
    ]


def test_adapter_fetches_record_usage_when_question_response_omits_it(
    monkeypatch,
) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/mcp_start"):
            return httpx.Response(
                200,
                json={"access_token": "runtime-only-token", "chat_id": 102},
            )
        if request.url.path.endswith("/mcp_generate_sql"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "record_id": 9002,
                        "sql": (
                            "SELECT region, sales_revenue "
                            "FROM semantic_sales_ops_orders LIMIT 10"
                        ),
                        "rows": [{"region": "north", "sales_revenue": 123.45}],
                    },
                },
            )
        assert request.headers["X-SQLBOT-TOKEN"] == "Bearer runtime-only-token"
        return httpx.Response(200, json={"data": {"total_tokens": 41}})

    engine = SQLBotEngine(
        enabled=True,
        runtime_verified=True,
        client=_client(monkeypatch, handler),
        generated_sql_executor=_platform_rows(
            {"region": "north", "sales_revenue": 123.45},
        ),
    )
    result = engine.execute(
        QueryRequest(
            question="按区域查看销售额",
            identity_context=_identity(),
            scenario_id="sales_ops",
        ),
        _context(),
    )

    assert result.evidence["token_usage"] == 41
    assert paths == [
        "/api/v1/mcp/mcp_start",
        "/api/v1/mcp/mcp_generate_sql",
        "/api/v1/chat/record/9002/usage",
    ]


def test_health_probe_uses_upstream_root_health_endpoint(monkeypatch) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, text="SQLBot")

    client = _client(monkeypatch, handler)

    assert client.health_check().status == "ok"
    assert paths == ["/"]


def test_structured_pre_sql_refusal_is_not_mapped_to_upstream_failure() -> None:
    for payload in (
        {"success": False, "refusal": "PRE_SQL_MODEL_REFUSAL"},
        {
            "code": 0,
            "data": {
                "success": False,
                "refusal": "PRE_SQL_MODEL_REFUSAL",
            },
        },
    ):
        with pytest.raises(SQLBotEngineError) as exc_info:
            parse_response(payload, max_rows=100)

        assert exc_info.value.code == SQLBotErrorCode.MODEL_REFUSAL
        assert exc_info.value.retryable is False


def test_sessions_are_isolated_by_user_workspace_scenario_and_versions(monkeypatch) -> None:
    starts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal starts
        if request.url.path.endswith("/mcp_start"):
            starts += 1
            return httpx.Response(
                200,
                json={"access_token": f"token-{starts}", "chat_id": starts},
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "sql": (
                        "SELECT sales_revenue "
                        "FROM semantic_sales_ops_orders LIMIT 1"
                    ),
                    "rows": [{"sales_revenue": 1}],
                },
            },
        )

    engine = SQLBotEngine(
        enabled=True,
        runtime_verified=True,
        client=_client(monkeypatch, handler),
        generated_sql_executor=_platform_rows({"sales_revenue": 1}),
    )
    context = _context()
    for identity in (_identity("user:1"), _identity("user:1"), _identity("user:2")):
        engine.execute(
            QueryRequest(
                question="销售额",
                identity_context=identity,
                scenario_id="sales_ops",
            ),
            context,
        )
    assert starts == 2


def test_generate_only_uses_platform_executor_after_guard(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/mcp_start"):
            return httpx.Response(
                200,
                json={"access_token": "runtime-token", "chat_id": 1},
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "sql": (
                        "SELECT sales_revenue "
                        "FROM semantic_sales_ops_orders LIMIT 5"
                    ),
                    "rows": [{"sales_revenue": 999999}],
                },
            },
        )

    executed: list[str] = []

    def execute(sql, request, context):
        del request, context
        executed.append(sql)
        return ("sales_revenue",), ({"sales_revenue": 88},)

    engine = SQLBotEngine(
        enabled=True,
        runtime_verified=True,
        client=_client(monkeypatch, handler),
        generated_sql_executor=execute,
    )
    result = engine.execute(
        QueryRequest(
            question="销售额",
            identity_context=_identity(),
            scenario_id="sales_ops",
        ),
        _context(execution_mode="generate_only"),
    )
    assert executed == [
        "SELECT sales_revenue FROM semantic_sales_ops_orders LIMIT 5"
    ]
    assert result.rows == ({"sales_revenue": 88},)


def test_guard_rejection_allows_exactly_one_repair_then_revalidates(monkeypatch) -> None:
    generation_requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/mcp_start"):
            return httpx.Response(
                200,
                json={"access_token": "runtime-token", "chat_id": 1},
            )
        payload = json.loads(request.content)
        generation_requests.append(payload)
        sql = (
            "SELECT secret FROM forbidden_table LIMIT 5"
            if len(generation_requests) == 1
            else "SELECT sales_revenue FROM semantic_sales_ops_orders LIMIT 5"
        )
        return httpx.Response(
            200,
            json={"success": True, "data": {"sql": sql, "rows": []}},
        )

    engine = SQLBotEngine(
        enabled=True,
        runtime_verified=True,
        client=_client(monkeypatch, handler),
        generated_sql_executor=_platform_rows({"sales_revenue": 88}),
    )
    result = engine.execute(
        QueryRequest(
            question="sales revenue",
            identity_context=_identity(),
            scenario_id="sales_ops",
        ),
        _context(),
    )

    assert len(generation_requests) == 2
    assert "[CONTROLLED_SQL_REPAIR]" in generation_requests[1]["question"]
    assert result.evidence["repair_used"] is True
    assert [item["guard_result"] for item in result.evidence["generation_attempts"]] == [
        "REJECTED",
        "PASSED",
    ]
    assert result.evidence["latency_profile"]["retry_ms"] >= 0


def test_credential_reference_sync_rotates_once_and_verifies() -> None:
    state = {"rotated": False, "logins": 0, "updates": 0}
    derived_password = derive_runtime_account_password("reference-password")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if request.url.path.endswith("/mcp_start"):
            state["logins"] += 1
            accepted = payload["password"] == "bootstrap-password" or (
                state["rotated"] and payload["password"] == derived_password
            )
            if not accepted:
                return httpx.Response(400, json={"detail": "invalid"})
            return httpx.Response(200, json={"access_token": "runtime-token", "chat_id": 1})
        state["updates"] += 1
        assert request.headers["X-SQLBOT-TOKEN"] == "Bearer runtime-token"
        assert payload == {
            "pwd": "bootstrap-password",
            "new_pwd": derived_password,
        }
        state["rotated"] = True
        return httpx.Response(200, json={"success": True})

    with httpx.Client(
        base_url="http://sqlbot.test/api/v1/",
        transport=httpx.MockTransport(handler),
    ) as client:
        operation = synchronize(
            client,
            username="admin",
            target_password="reference-password",
            bootstrap_password="bootstrap-password",
        )

    assert operation == "existing_and_rotated"
    assert state == {"rotated": True, "logins": 3, "updates": 1}


def test_credential_reference_sync_provisions_service_account() -> None:
    state = {"created": False, "rotated": False}
    derived_password = derive_runtime_account_password("reference-password")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else {}
        if request.url.path.endswith("/mcp_start"):
            account = payload["username"]
            password = payload["password"]
            accepted = (
                (account == "admin" and password == "bootstrap-password")
                or (
                    account == "runtime-service"
                    and state["created"]
                    and (
                        password == "bootstrap-password"
                        or (state["rotated"] and password == derived_password)
                    )
                )
            )
            if not accepted:
                return httpx.Response(400, json={"detail": "invalid"})
            return httpx.Response(200, json={"access_token": f"token-{account}"})
        if request.url.path.endswith("/user/pager/1/100"):
            return httpx.Response(200, json={"data": {"items": []}})
        if request.url.path.endswith("/user/info"):
            return httpx.Response(200, json={"data": {"oid": 7}})
        if request.url.path.endswith("/user"):
            assert payload["account"] == "runtime-service"
            assert payload["oid_list"] == [7]
            state["created"] = True
            return httpx.Response(200, json={"success": True})
        if request.url.path.endswith("/user/pwd"):
            assert request.headers["X-SQLBOT-TOKEN"] == "Bearer token-runtime-service"
            state["rotated"] = True
            return httpx.Response(200, json={"success": True})
        raise AssertionError(request.url.path)

    with httpx.Client(
        base_url="http://sqlbot.test/api/v1/",
        transport=httpx.MockTransport(handler),
    ) as client:
        operation = synchronize(
            client,
            username="runtime-service",
            target_password="reference-password",
            bootstrap_password="bootstrap-password",
        )

    assert operation == "created_and_rotated"
    assert state == {"created": True, "rotated": True}


def test_timeout_opens_circuit_without_unbounded_retry(monkeypatch) -> None:
    question_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal question_calls
        if request.url.path.endswith("/mcp_start"):
            return httpx.Response(
                200,
                json={"access_token": "runtime-token", "chat_id": 1},
            )
        question_calls += 1
        raise httpx.ReadTimeout("simulated timeout", request=request)

    engine = SQLBotEngine(
        enabled=True,
        runtime_verified=True,
        client=_client(monkeypatch, handler, threshold=2),
    )
    request = QueryRequest(
        question="销售额",
        identity_context=_identity(),
        scenario_id="sales_ops",
    )
    with pytest.raises(SQLBotEngineError) as first:
        engine.execute(request, _context())
    with pytest.raises(SQLBotEngineError) as second:
        engine.execute(request, _context())
    with pytest.raises(SQLBotEngineError) as third:
        engine.execute(request, _context())
    assert first.value.code == SQLBotErrorCode.TIMEOUT
    assert second.value.code == SQLBotErrorCode.TIMEOUT
    assert third.value.code == SQLBotErrorCode.CIRCUIT_OPEN
    assert question_calls == 2


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO semantic_sales_ops_orders(order_id) VALUES (1)",
        "UPDATE semantic_sales_ops_orders SET sales_revenue = 0",
        "DELETE FROM semantic_sales_ops_orders",
        "DROP TABLE semantic_sales_ops_orders",
        "ALTER TABLE semantic_sales_ops_orders ADD COLUMN secret text",
        "SELECT order_id FROM semantic_sales_ops_orders LIMIT 1; SELECT 1",
        "SELECT relname FROM pg_catalog.pg_class LIMIT 1",
        "SELECT order_id FROM another_scenario LIMIT 1",
        "SELECT secret_field FROM semantic_sales_ops_orders LIMIT 1",
        "SELECT * FROM semantic_sales_ops_orders LIMIT 1",
        "SELECT pg_sleep(1) FROM semantic_sales_ops_orders LIMIT 1",
        "WITH x AS (SELECT order_id FROM semantic_sales_ops_orders) "
        "SELECT order_id FROM x LIMIT 1",
    ],
)
def test_sqlbot_security_policy_rejects_dangerous_or_unscoped_sql(
    monkeypatch,
    sql,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/mcp_start"):
            return httpx.Response(
                200,
                json={"access_token": "runtime-token", "chat_id": 1},
            )
        return httpx.Response(
            200,
            json={"success": True, "data": {"sql": sql, "rows": []}},
        )

    engine = SQLBotEngine(
        enabled=True,
        runtime_verified=True,
        client=_client(monkeypatch, handler),
    )
    with pytest.raises((ValueError, SQLBotEngineError)):
        engine.execute(
            QueryRequest(
                question="攻击或越权请求",
                identity_context=_identity(),
                scenario_id="sales_ops",
            ),
            _context(),
        )
