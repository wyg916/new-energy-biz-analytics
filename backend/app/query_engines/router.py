import hashlib
from dataclasses import dataclass, replace
from enum import StrEnum

from app.core.config import get_settings
from app.platform.query_engine import QueryContext, QueryEngine, QueryRequest, QueryResult
from app.query_engines.shadow import (
    RoutingEvidenceRepository,
    ShadowComparison,
    compare_results,
)
from app.query_engines.sqlbot.error_mapper import SQLBotEngineError


class EngineMode(StrEnum):
    DETERMINISTIC_ONLY = "DETERMINISTIC_ONLY"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    SQLBOT_ENABLED = "SQLBOT_ENABLED"
    DISABLED = "DISABLED"


class QueryRoutingError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CanaryPolicy:
    percentage: float
    tenants: frozenset[str] = frozenset()
    workspaces: frozenset[str] = frozenset()
    users: frozenset[str] = frozenset()
    scenarios: frozenset[str] = frozenset()

    def eligible(self, request: QueryRequest) -> bool:
        identity = request.identity_context
        if self.percentage <= 0:
            return False
        if self.tenants and identity.tenant_id not in self.tenants:
            return False
        if self.workspaces and identity.workspace_id not in self.workspaces:
            return False
        if self.users and identity.subject_id not in self.users:
            return False
        if self.scenarios and request.scenario_id not in self.scenarios:
            return False
        raw = "|".join((
            identity.tenant_id,
            identity.workspace_id,
            identity.subject_id,
            request.scenario_id,
            identity.request_id,
        ))
        bucket = int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16) % 10_000
        return bucket < min(self.percentage, 100.0) * 100


@dataclass(frozen=True)
class RoutedQueryResult:
    result: QueryResult
    route_decision: str
    route_reason: str
    shadow_comparison: ShadowComparison | None = None


class EngineRouter:
    def __init__(
        self,
        deterministic: QueryEngine,
        sqlbot: QueryEngine,
        *,
        mode: EngineMode,
        canary: CanaryPolicy | None = None,
        evidence: RoutingEvidenceRepository | None = None,
        feature_flag_version: str = "p1b-1",
    ):
        self.deterministic = deterministic
        self.sqlbot = sqlbot
        self.mode = mode
        self.canary = canary or CanaryPolicy(percentage=0)
        self.evidence = evidence
        self.feature_flag_version = feature_flag_version

    @classmethod
    def from_settings(
        cls,
        deterministic: QueryEngine,
        sqlbot: QueryEngine,
        *,
        evidence: RoutingEvidenceRepository | None = None,
    ) -> "EngineRouter":
        settings = get_settings()
        scope = settings.query_engine_canary_scope
        return cls(
            deterministic,
            sqlbot,
            mode=EngineMode(settings.effective_query_engine_mode),
            canary=CanaryPolicy(
                percentage=settings.query_engine_canary_percentage,
                tenants=scope["tenants"],
                workspaces=scope["workspaces"],
                users=scope["users"],
                scenarios=scope["scenarios"],
            ),
            evidence=evidence,
            feature_flag_version=settings.query_engine_feature_flag_version,
        )

    def execute(
        self,
        request: QueryRequest,
        context: QueryContext,
        *,
        deterministic_supported: bool,
    ) -> RoutedQueryResult:
        if self.mode == EngineMode.DISABLED:
            raise QueryRoutingError(
                "QUERY_ENGINE_DISABLED",
                "查询引擎已禁用",
            )
        if self.mode == EngineMode.DETERMINISTIC_ONLY:
            return self._deterministic(
                request,
                context,
                "DETERMINISTIC_ONLY",
                "stable_path",
            )
        if self.mode == EngineMode.SHADOW:
            return self._shadow(request, context)
        if deterministic_supported:
            return self._deterministic(
                request,
                context,
                "CORE_DETERMINISTIC",
                "core_query_pinned",
            )
        if self.mode == EngineMode.CANARY and not self.canary.eligible(request):
            raise QueryRoutingError(
                "CANARY_NOT_SELECTED",
                "长尾查询未命中 SQLBot Canary，需澄清或稍后重试",
            )
        return self._sqlbot(
            request,
            context,
            "SQLBOT_CANARY"
            if self.mode == EngineMode.CANARY
            else "SQLBOT_ENABLED",
            "eligible_long_tail_query",
        )

    def _deterministic(
        self,
        request: QueryRequest,
        context: QueryContext,
        decision: str,
        reason: str,
    ) -> RoutedQueryResult:
        result = self.deterministic.execute(request, context)
        self._record_route(
            request,
            context,
            decision,
            reason,
            result,
        )
        return RoutedQueryResult(result, decision, reason)

    def _shadow(
        self,
        request: QueryRequest,
        context: QueryContext,
    ) -> RoutedQueryResult:
        deterministic = self.deterministic.execute(request, context)
        sqlbot = None
        error_code = None
        error = None
        comparison = None
        try:
            sqlbot = self.sqlbot.execute(request, context)
            comparison = compare_results(deterministic, sqlbot)
        except SQLBotEngineError as exc:
            error_code = str(exc.code)
            error = exc.message
        except Exception:
            error_code = "SQLBOT_SHADOW_FAILED"
            error = "SQLBot Shadow 调用失败"
        if self.evidence:
            self.evidence.record_shadow(
                request,
                context,
                deterministic,
                sqlbot,
                route_mode=self.mode.value,
                error_code=error_code,
                error=error,
            )
        warnings = deterministic.warnings
        if error_code:
            warnings = (*warnings, error_code)
        deterministic = replace(deterministic, warnings=warnings)
        self._record_route(
            request,
            context,
            "DETERMINISTIC_WITH_SHADOW",
            error_code or "shadow_completed",
            deterministic,
        )
        return RoutedQueryResult(
            deterministic,
            "DETERMINISTIC_WITH_SHADOW",
            error_code or "shadow_completed",
            comparison,
        )

    def _sqlbot(
        self,
        request: QueryRequest,
        context: QueryContext,
        decision: str,
        reason: str,
    ) -> RoutedQueryResult:
        try:
            result = self.sqlbot.execute(request, context)
        except SQLBotEngineError as exc:
            raise QueryRoutingError(str(exc.code), exc.message) from exc
        self._record_route(
            request,
            context,
            decision,
            reason,
            result,
        )
        return RoutedQueryResult(result, decision, reason)

    def _record_route(
        self,
        request: QueryRequest,
        context: QueryContext,
        decision: str,
        reason: str,
        result: QueryResult,
    ) -> None:
        if self.evidence:
            self.evidence.record_route(
                request,
                context,
                route_decision=decision,
                route_reason=reason,
                mode=self.mode.value,
                engine=result.engine,
                feature_flag_version=self.feature_flag_version,
                run_id=result.run_id,
            )
