from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.memory.episodic import EpisodicMemoryService, EpisodicRun
from app.memory.models import P2B_MEMORY_TABLES
from app.memory.working import WorkingMemoryService, WorkingMemoryState
from app.models.auth import User
from app.platform.identity import IdentityContextFactory


pytestmark = pytest.mark.no_db


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key): return self.data.get(key)
    def set(self, key, value, *, ex): self.data[key] = value; return ex > 0
    def delete(self, key): return int(self.data.pop(key, None) is not None)
    def sadd(self, key, *values): self.data.setdefault(key, set()).update(values); return len(values)
    def srem(self, key, *values): self.data.get(key, set()).difference_update(values); return len(values)


@pytest.fixture
def evaluation_db():
    engine = create_engine("sqlite:///:memory:")
    for table in P2B_MEMORY_TABLES:
        table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(id=91, username="eval", password_hash="x", display_name="Eval", role="analyst", region_code=None, is_active=True)
        yield db, IdentityContextFactory.from_user(user)
    engine.dispose()


@pytest.mark.parametrize(
    ("turn", "update", "expected_key"),
    [
        ("region", {"filters": [{"field": "region", "value": "华东"}]}, "filters"),
        ("dimension", {"dimensions": ["station"]}, "dimensions"),
        ("comparison", {"comparison": {"type": "yoy"}}, "comparison"),
        ("report", {"current_intent": "operating_report_generation"}, "current_intent"),
        ("chart", {"chart_type": "line"}, "chart_type"),
    ],
)
def test_working_context_inheritance_evaluation(evaluation_db, turn, update, expected_key):
    db, identity = evaluation_db
    redis = FakeRedis()
    service = WorkingMemoryService(db, identity, redis_client=redis)
    session_id = f"EVAL-WORK-{turn}"
    initial = WorkingMemoryState(
        scenario_id="charging_ops", metrics=["charging_revenue"],
        time_range={"relative_days": 30}, dataset_version="1", semantic_version="0.1.0",
    )
    service.save(session_id=session_id, state=initial)
    inherited = service.load(scenario_id="charging_ops", session_id=session_id).state
    for key, value in update.items():
        setattr(inherited, key, value)
    inherited.state_version += 1
    service.save(session_id=session_id, state=inherited)
    final = service.load(scenario_id="charging_ops", session_id=session_id).state
    assert final.metrics == ["charging_revenue"]
    assert final.time_range == {"relative_days": 30}
    assert getattr(final, expected_key) == update[expected_key]


def _episode(index: int) -> EpisodicRun:
    return EpisodicRun(
        run_id=f"EVAL-EP-{index}", trace_id=f"TRACE-EP-{index}", session_id=f"CONV-EP-{index}",
        raw_question=f"查询第{index}个收入分析", normalized_question=f"收入分析{index}",
        scenario_id="charging_ops", dataset_version="1", semantic_version="0.1.0",
        engine="deterministic", query_plan={"metric": "charging_revenue"}, actual_sql="SELECT 1",
        result_summary={"metric": "charging_revenue", "value": index}, rag_evidence=[],
        final_answer=f"模拟数据结果{index}", skill_code=None,
        steps=[{"step_id": f"STEP-{index}", "status": "completed"}], errors=[], adopted=None,
        runtime_cost={"token_usage": 0}, latency_ms=index,
    )


@pytest.mark.parametrize("index", [2, 3, 4])
def test_episodic_replay_and_retrieval_evaluation(evaluation_db, index):
    db, identity = evaluation_db
    service = EpisodicMemoryService(db, identity)
    service.record_success(_episode(index))
    replay = service.replay(run_id=f"EVAL-EP-{index}", scenario_id="charging_ops")
    assert replay["result_summary"]["value"] == index
    assert len(replay["result_hash"]) == 64
    assert service.search(query=f"收入分析{index}", scenario_id="charging_ops")
