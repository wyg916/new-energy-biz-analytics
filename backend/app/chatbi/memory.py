import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.chatbi.parser import parse_question, parse_with_context
from app.chatbi.plan import QueryPlan
from app.models.auth import User
from app.models.business import SessionState


class MemoryAccessDenied(PermissionError):
    pass


@dataclass
class WorkState:
    task_id: str
    run_id: str
    user_id: int
    conversation_id: str
    current_stage: str
    query_plan_digest: str
    started_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    state_version: int = 1


class WorkingMemoryStore:
    """Single-process Alpha work state; bounded to the active request and released on finish."""
    def __init__(self):
        self._states: dict[str, WorkState] = {}

    def start(self, run_id: str, user_id: int, conversation_id: str, query_plan_digest: str) -> WorkState:
        now = datetime.now(UTC)
        state = WorkState(f"TASK-{uuid4()}", run_id, user_id, conversation_id, "planning", query_plan_digest, now, now, now + timedelta(hours=2))
        self._states[state.task_id] = state
        return state

    def update(self, task_id: str, stage: str) -> WorkState:
        state = self._states[task_id]
        now = datetime.now(UTC)
        if state.expires_at <= now:
            del self._states[task_id]
            raise KeyError("work state expired")
        state.current_stage = stage
        state.last_activity_at = now
        state.expires_at = now + timedelta(hours=2)
        state.state_version += 1
        return state

    def finish(self, task_id: str) -> None:
        self._states.pop(task_id, None)

    def snapshot(self, task_id: str) -> dict | None:
        state = self._states.get(task_id)
        return asdict(state) if state else None

    def cleanup(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        expired = [task_id for task_id, state in self._states.items() if state.expires_at <= now]
        for task_id in expired:
            del self._states[task_id]
        return len(expired)


WORK_MEMORY = WorkingMemoryStore()


class SessionMemory:
    def __init__(self, db: Session, user: User, conversation_id: str | None):
        self.db = db
        self.user = user
        self.conversation_id = conversation_id or f"CONV-{uuid4()}"
        self.state = db.get(SessionState, self.conversation_id)
        if self.state and self.state.user_id != user.id:
            raise MemoryAccessDenied("conversation does not belong to current user")
        if self.state and self.state.status == "active":
            expires = self.state.expires_at.replace(tzinfo=UTC) if self.state.expires_at.tzinfo is None else self.state.expires_at
            if expires <= datetime.now(UTC):
                self.state.status = "expired"
                db.commit()

    def resolve(self, question: str) -> QueryPlan:
        if not self.state or self.state.status != "active":
            return parse_question(question)
        metrics = json.loads(self.state.active_metrics_json)
        filters = json.loads(self.state.active_filters_json)
        period = json.loads(self.state.active_time_range_json)
        comparison = json.loads(self.state.active_comparison_json)
        resolved = {
            "metric": metrics[0] if metrics else None,
            "period": period["start"][:7] if period else None,
            "comparison": comparison.get("type") if comparison else None,
        }
        for item in filters:
            if item["field"] in {"region", "station"}:
                resolved[item["field"]] = item["value"]
        return parse_with_context(question, [{"resolved_state": {key: value for key, value in resolved.items() if value}}])

    def save(self, plan: QueryPlan, run_id: str) -> int:
        if plan.status != "ready":
            return self.state.state_version if self.state else 0
        now = datetime.now(UTC)
        if self.state is None:
            self.state = SessionState(
                conversation_id=self.conversation_id, user_id=self.user.id,
                role_ids_json=json.dumps([self.user.role]), created_at=now, updated_at=now,
                expires_at=now + timedelta(days=7), state_version=1, status="active",
            )
            self.db.add(self.state)
        else:
            self.state.state_version += 1
            self.state.updated_at = now
            if self.state.status != "active":
                self.state.created_at = now
                self.state.expires_at = now + timedelta(days=7)
                self.state.status = "active"
        self.state.active_intent = plan.intent
        self.state.active_metrics_json = json.dumps(plan.metrics)
        self.state.active_dimensions_json = json.dumps(plan.dimensions)
        self.state.active_filters_json = json.dumps([item.model_dump(mode="json") for item in plan.filters], ensure_ascii=False)
        self.state.active_time_range_json = json.dumps(plan.time_range.model_dump(mode="json") if plan.time_range else None)
        self.state.active_comparison_json = json.dumps(plan.comparison)
        self.state.active_entities_json = json.dumps({})
        self.state.current_step = "answered"
        run_ids = json.loads(self.state.source_run_ids_json or "[]")
        self.state.source_run_ids_json = json.dumps((run_ids + [run_id])[-20:])
        self.db.commit()
        return self.state.state_version

    def clear(self) -> None:
        if self.state:
            self.state.status = "cleared"
            self.state.active_metrics_json = "[]"
            self.state.active_dimensions_json = "[]"
            self.state.active_filters_json = "[]"
            self.state.active_time_range_json = "null"
            self.state.active_comparison_json = "null"
            self.db.commit()
