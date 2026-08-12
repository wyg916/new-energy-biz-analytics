import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Callable, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.business import SessionState
from app.models.integration import ScenarioPackageRelease
from app.models.platform_data import DatasetVersion, PlatformDataset
from app.models.query_routing import ChatScenarioSessionBinding
from app.platform.identity import IdentityContext, IdentityContextFactory


class ScenarioChatService(Protocol):
    def ask(self, question: str) -> dict:
        ...


class ScenarioChatServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ScenarioChatRegistration:
    scenario_id: str
    display_name: str
    initial_question: str
    suggested_questions: tuple[str, ...]
    service_factory: Callable[[Session, User, str], ScenarioChatService]


class ScenarioChatServiceRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, ScenarioChatRegistration] = {}

    def register(self, registration: ScenarioChatRegistration) -> None:
        if registration.scenario_id in self._registrations:
            raise ValueError(
                f"scenario chat service already registered: "
                f"{registration.scenario_id}"
            )
        self._registrations[registration.scenario_id] = registration

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    def catalog(self, db: Session, user: User) -> list[dict]:
        identity = IdentityContextFactory.from_user(user)
        rows = []
        for registration in self._registrations.values():
            release = db.scalar(
                select(ScenarioPackageRelease)
                .where(
                    ScenarioPackageRelease.tenant_id == identity.tenant_id,
                    ScenarioPackageRelease.workspace_id
                    == identity.workspace_id,
                    ScenarioPackageRelease.scenario_id
                    == registration.scenario_id,
                    ScenarioPackageRelease.status == "ACTIVE",
                )
                .order_by(ScenarioPackageRelease.activated_at.desc())
            )
            dataset = db.scalar(
                select(PlatformDataset).where(
                    PlatformDataset.tenant_id == identity.tenant_id,
                    PlatformDataset.workspace_id == identity.workspace_id,
                    PlatformDataset.scenario_id == registration.scenario_id,
                )
            )
            active_version = (
                db.scalar(
                    select(DatasetVersion).where(
                        DatasetVersion.dataset_id == dataset.dataset_id,
                        DatasetVersion.status == "ACTIVE",
                    )
                )
                if dataset
                else None
            )
            period_start = active_version.period_start if active_version else None
            period_end_exclusive = (
                active_version.period_end_exclusive if active_version else None
            )
            rows.append({
                "scenario_id": registration.scenario_id,
                "display_name": (
                    release.display_name
                    if release
                    else registration.display_name
                ),
                "status": "ACTIVE" if release else "NOT_ACTIVE",
                "scenario_version": release.version if release else None,
                "data_classification": (
                    dataset.data_classification if dataset else "unavailable"
                ),
                "data_time_range": (
                    {
                        "start": period_start,
                        "end_exclusive": period_end_exclusive,
                    }
                    if period_start and period_end_exclusive
                    else None
                ),
                "initial_question": self._initial_question(
                    registration,
                    period_start,
                    period_end_exclusive,
                ),
                "suggested_questions": list(registration.suggested_questions),
            })
        return rows

    @staticmethod
    def _initial_question(
        registration: ScenarioChatRegistration,
        period_start: str | None,
        period_end_exclusive: str | None,
    ) -> str:
        """Build an executable starter question from the ACTIVE dataset window.

        Charging's parser converts the visible end date to an exclusive bound,
        while the sales engine accepts the second ISO date as already exclusive.
        Keeping that distinction here prevents the UI's automatic first request
        from querying outside the active version after a dataset switch.
        """
        if not period_start or not period_end_exclusive:
            return registration.initial_question
        try:
            available_start = date.fromisoformat(period_start[:10])
            available_end = date.fromisoformat(period_end_exclusive[:10])
        except ValueError:
            return registration.initial_question
        if available_end <= available_start:
            return registration.initial_question
        query_start = max(available_start, available_end - timedelta(days=7))
        query_end_inclusive = available_end - timedelta(days=1)
        if registration.scenario_id == "sales_ops":
            return (
                f"{query_start.isoformat()}至{available_end.isoformat()}"
                "销售收入、订单数和销售毛利率是多少？"
            )
        return (
            f"{query_start.isoformat()}至{query_end_inclusive.isoformat()}"
            "充电收入是多少？"
        )

    def execute(
        self,
        db: Session,
        user: User,
        *,
        scenario_id: str,
        conversation_id: str | None,
        question: str,
    ) -> dict:
        registration = self._registrations.get(scenario_id)
        if registration is None:
            raise ScenarioChatServiceError(
                "SCENARIO_NOT_SUPPORTED",
                "请求场景未注册 ChatBI 服务",
            )
        identity = IdentityContextFactory.from_user(user)
        bound_conversation = conversation_id or f"CONV-{uuid4()}"
        self._bind_conversation(
            db,
            identity,
            bound_conversation,
            scenario_id,
        )
        return registration.service_factory(
            db,
            user,
            bound_conversation,
        ).ask(question)

    def validate_conversation_owner(
        self,
        db: Session,
        user: User,
        conversation_id: str,
    ) -> ChatScenarioSessionBinding:
        identity = IdentityContextFactory.from_user(user)
        record = db.get(ChatScenarioSessionBinding, conversation_id)
        if record is None:
            legacy = db.get(SessionState, conversation_id)
            if legacy and legacy.user_id == user.id:
                entities = json.loads(legacy.active_entities_json or "{}")
                scenario_id = entities.get("scenario_id", "charging_ops")
                self._bind_conversation(
                    db,
                    identity,
                    conversation_id,
                    scenario_id,
                )
                record = db.get(ChatScenarioSessionBinding, conversation_id)
        if record is None or (
            record.tenant_id,
            record.workspace_id,
            record.subject_id,
        ) != (
            identity.tenant_id,
            identity.workspace_id,
            identity.subject_id,
        ):
            raise ScenarioChatServiceError(
                "CONVERSATION_SCOPE_DENIED",
                "会话不属于当前身份范围",
            )
        return record

    @staticmethod
    def _bind_conversation(
        db: Session,
        identity: IdentityContext,
        conversation_id: str,
        scenario_id: str,
    ) -> None:
        record = db.get(ChatScenarioSessionBinding, conversation_id)
        if record is None:
            legacy = db.get(SessionState, conversation_id)
            if legacy is not None:
                legacy_subject = f"user:{legacy.user_id}"
                entities = json.loads(legacy.active_entities_json or "{}")
                legacy_scenario = entities.get(
                    "scenario_id",
                    "charging_ops",
                )
                if (
                    legacy_subject != identity.subject_id
                    or legacy_scenario != scenario_id
                ):
                    raise ScenarioChatServiceError(
                        "CONVERSATION_SCENARIO_MISMATCH",
                        "历史会话已绑定其他身份或业务场景，请新建会话",
                    )
            db.add(ChatScenarioSessionBinding(
                conversation_id=conversation_id,
                tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id,
                subject_id=identity.subject_id,
                scenario_id=scenario_id,
            ))
            db.commit()
            return
        if (
            record.tenant_id,
            record.workspace_id,
            record.subject_id,
            record.scenario_id,
        ) != (
            identity.tenant_id,
            identity.workspace_id,
            identity.subject_id,
            scenario_id,
        ):
            raise ScenarioChatServiceError(
                "CONVERSATION_SCENARIO_MISMATCH",
                "会话已绑定其他身份或业务场景，请新建会话",
            )
        record.last_used_at = datetime.now(UTC)
        db.commit()


@lru_cache
def get_scenario_chat_registry() -> ScenarioChatServiceRegistry:
    from app.chatbi.service import ChatBIService
    from app.scenarios.sales_ops.chat_service import SalesOpsChatService

    registry = ScenarioChatServiceRegistry()
    registry.register(ScenarioChatRegistration(
        scenario_id="charging_ops",
        display_name="充电运营",
        initial_question="2026年6月充电收入环比变化的原因？",
        suggested_questions=(
            "毛利率变化的主要关联因素？",
            "场站利用率下降的场站有哪些？",
            "度电成本上升的主要贡献项？",
        ),
        service_factory=ChatBIService,
    ))
    registry.register(ScenarioChatRegistration(
        scenario_id="sales_ops",
        display_name="销售经营",
        initial_question="2026年6月销售收入、订单数和销售毛利率是多少？",
        suggested_questions=(
            "2026年6月退款率是多少？",
            "2026年6月新客户数和复购客户数是多少？",
            "2026年6月客单价是多少？",
        ),
        service_factory=SalesOpsChatService,
    ))
    return registry
