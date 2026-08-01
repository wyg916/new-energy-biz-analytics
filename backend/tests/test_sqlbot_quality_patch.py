import json

import pytest

from app.platform.identity import IdentityContext
from app.platform.query_engine import QueryContext, QueryRequest
from app.query_engines.sqlbot.contracts import SQLBotSession, SQLBotSessionKey
from app.query_engines.sqlbot.error_mapper import SQLBotEngineError, SQLBotErrorCode
from app.query_engines.sqlbot.limit_policy import apply_limit_policy
from app.query_engines.sqlbot.request_mapper import map_question_request
from app.query_engines.sqlbot.response_parser import parse_response


pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("payload", "format_warning"),
    [
        ({"success": True, "data": {"sql": "SELECT order_id FROM sales_order LIMIT 1"}}, "standard_json"),
        ("```json\n{\"sql\": \"SELECT order_id FROM sales_order LIMIT 1\"}\n```", "json_code_block"),
        ("```sql\nSELECT order_id FROM sales_order LIMIT 1\n```", "sql_code_block"),
        ("SELECT order_id FROM sales_order LIMIT 1;", "single_select_text"),
        ({"record": {"id": 8, "sql": "SELECT order_id FROM sales_order LIMIT 1", "data": []}}, "sqlbot_record"),
    ],
)
def test_structured_response_formats_are_parsed_in_auditable_order(payload, format_warning):
    parsed = parse_response(payload, max_rows=500)
    assert parsed.sql.startswith("SELECT")
    assert parsed.warnings == (f"sqlbot_response_format:{format_warning}",)


def test_sqlbot_v18_fields_and_matrix_rows_are_normalized():
    parsed = parse_response(
        {
            "success": True,
            "record_id": 42,
            "sql": "SELECT order_id, net_revenue FROM sales_order LIMIT 2",
            "data": {"fields": ["order_id", "net_revenue"], "data": [["O1", 10], ["O2", 20]]},
        },
        max_rows=500,
    )
    assert parsed.rows == (
        {"order_id": "O1", "net_revenue": 10},
        {"order_id": "O2", "net_revenue": 20},
    )
    assert parsed.columns == ("order_id", "net_revenue")
    assert parsed.upstream_record_id == "42"


@pytest.mark.parametrize(
    "payload",
    [
        "我猜可以执行 SELECT order_id FROM sales_order LIMIT 1",
        "前言\n```sql\nSELECT order_id FROM sales_order LIMIT 1\n```",
        {"message": "请执行 SELECT order_id FROM sales_order LIMIT 1"},
        "UPDATE sales_order SET net_revenue = 0",
    ],
)
def test_natural_language_or_non_select_text_is_not_guessed_as_sql(payload):
    with pytest.raises(SQLBotEngineError) as error:
        parse_response(payload, max_rows=500)
    assert error.value.code == SQLBotErrorCode.RESPONSE_INVALID


def test_limit_policy_clamps_ast_and_adds_only_detail_default():
    clamped = apply_limit_policy("SELECT order_id FROM sales_order LIMIT 1000")
    assert "LIMIT 500" in clamped.sql
    assert clamped.warnings == ("limit_clamped:1000->500",)

    detail = apply_limit_policy("SELECT order_id FROM sales_order")
    assert "LIMIT 100" in detail.sql
    assert detail.warnings == ("default_detail_limit_added:100",)

    aggregate = apply_limit_policy("SELECT SUM(net_revenue) AS revenue FROM sales_order")
    assert "LIMIT" not in aggregate.sql.upper()
    assert aggregate.warnings == ()


def test_request_prompt_contains_only_current_authorized_scenario_contract():
    identity = IdentityContext(
        subject_id="user:1", tenant_id="tenant", org_id="org", workspace_id="workspace",
        roles=("analyst_admin",), groups=(), data_scopes=("workspace:all",),
        auth_strength="test", issued_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        request_id="request-1",
    )
    request = QueryRequest(question="销售收入", identity_context=identity, scenario_id="sales_ops")
    context = QueryContext(
        conversation_id="conversation-1", scenario_version="1", semantic_version="1",
        semantic_model_version_id="semantic-1", dataset_version="1", dataset_version_id="dataset-1",
        datasource_id="2", allowed_relations={"sales_order": ("order_date", "net_revenue")},
        prompt_context={
            "authorized_tables": [{"relation": "sales_order", "fields": ["order_date", "net_revenue"]}],
            "metrics": [{"code": "sales_revenue"}], "dimensions": [], "relationships": [],
            "time_dimensions": [{"field_ref": "sales_order.order_date"}],
            "sql_examples": [{"question": "收入", "sql": "SELECT SUM(net_revenue) FROM sales_order"}],
        },
    )
    key = SQLBotSessionKey("tenant", "workspace", "user:1", "conversation-1", "sales_ops", "1", "1", "1")
    mapped = map_question_request(request, context, SQLBotSession(key, "10", "secret"))
    prompt = mapped["question"]
    assert '"scenario_id":"sales_ops"' in prompt
    assert '"max_limit":500' in prompt
    assert "sales_order" in prompt
    assert "fact_charging_session" not in prompt
    assert mapped["datasource_id"] == "2"
    assert json.loads(prompt.split("\n", 2)[1])["constraints"]["default_detail_limit"] == 100
