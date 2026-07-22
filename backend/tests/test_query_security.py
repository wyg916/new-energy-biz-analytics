from datetime import date

import pytest

from app.chatbi.compiler import CompiledQuery, ScopeDenied, compile_query
from app.chatbi.executor import execute_readonly
from app.chatbi.guard import QueryRejected, guard_compiled_query, reject_arbitrary_sql
from app.chatbi.parser import parse_question
from app.bootstrap import bootstrap_demo_users
from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data
from app.models.auth import User
from app.services.dashboard import allowed_station_ids


ATTACKS = [
    "DROP TABLE fact_charging_session", "DELETE FROM fact_charging_session", "SELECT 1; DROP TABLE dim_user",
    "UPDATE app_user SET role='admin'", "INSERT INTO audit_log VALUES (1)", "TRUNCATE fact_energy_cost",
    "SELECT pg_read_file('/etc/passwd')", "SELECT * FROM pg_catalog.pg_user", "SELECT pg_sleep(10)",
    "SELECT * FROM fact_charging_session -- bypass", "/*x*/ SELECT * FROM dim_user", "COPY app_user TO PROGRAM 'x'",
]


@pytest.mark.parametrize("attack", ATTACKS)
def test_arbitrary_and_dangerous_sql_is_always_rejected(attack):
    with pytest.raises(QueryRejected):
        reject_arbitrary_sql(attack)


def test_plan_compiler_guard_and_readonly_execution():
    bootstrap_demo_users()
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
        user = db.query(User).filter_by(username="analyst").one()
        plan = parse_question("区域A在2026年6月充电收入和毛利率是多少？")
        assert plan.status == "ready"
        compiled = compile_query(db, plan, allowed_station_ids(db, user))
        guard_compiled_query(compiled)
        result = execute_readonly(db, compiled)
        assert set(result) == {"charging_revenue", "gross_margin"}
        assert result["charging_revenue"] >= 0
        assert "区域A" not in compiled.sql
        assert "R01" not in compiled.sql


def test_scope_intersection_fails_closed():
    bootstrap_demo_users()
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=100)
        user = db.query(User).filter_by(username="regional").one()
        plan = parse_question("区域B在2026年6月充电收入是多少？")
        with pytest.raises(ScopeDenied):
            compile_query(db, plan, allowed_station_ids(db, user))


def test_compiled_query_tamper_is_rejected():
    bad = CompiledQuery(sql="SELECT * FROM app_user", parameters={"start_ts": 1, "end_ts": 2, "start_date": date.today(), "end_date": date.today(), "period_seconds": 1, "limit": 1}, metric_ids=[], station_ids=["S001"])
    with pytest.raises(QueryRejected):
        guard_compiled_query(bad)
