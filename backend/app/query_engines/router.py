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
    SCOPED_STABLE = "SCOPED_STABLE"
    DISABLED = "DISABLED"


class RolloutStage(StrEnum):
    SHADOW = "SHADOW"
    CANARY_5 = "CANARY_5"
    CANARY_20 = "CANARY_20"
    SCOPED_STABLE = "SCOPED_STABLE"


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
        fallback_enabled: bool = False,
    ):
        self.deterministic = deterministic
        self.sqlbot = sqlbot
        self.mode = mode
        self.canary = canary or CanaryPolicy(percentage=0)
        if self.mode == EngineMode.SCOPED_STABLE:
            scoped = any((
                self.canary.tenants,
                self.canary.workspaces,
                self.canary.users,
                self.canary.scenarios,
            ))
            if not scoped:
                raise ValueError("SCOPED_STABLE requires an explicit allowlist scope")
            self.canary = replace(self.canary, percentage=100.0)
        self.evidence = evidence
        self.feature_flag_version = feature_flag_version
        self.fallback_enabled = fallback_enabled

    @classmethod
    def for_rollout_stage(
        cls,
        deterministic: QueryEngine,
        sqlbot: QueryEngine,
        *,
        stage: RolloutStage,
        scope: CanaryPolicy | None = None,
        evidence: RoutingEvidenceRepository | None = None,
        feature_flag_version: str = "sqlbot-4.1",
    ) -> "EngineRouter":
        base = scope or CanaryPolicy(percentage=100)
        percentages = {
            RolloutStage.SHADOW: base.percentage,
            RolloutStage.CANARY_5: 5.0,
            RolloutStage.CANARY_20: 20.0,
            RolloutStage.SCOPED_STABLE: 100.0,
        }
        mode = {
            RolloutStage.SHADOW: EngineMode.SHADOW,
            RolloutStage.CANARY_5: EngineMode.CANARY,
            RolloutStage.CANARY_20: EngineMode.CANARY,
            RolloutStage.SCOPED_STABLE: EngineMode.SCOPED_STABLE,
        }[stage]
        return cls(
            deterministic,
            sqlbot,
            mode=mode,
            canary=replace(base, percentage=percentages[stage]),
            evidence=evidence,
            feature_flag_version=feature_flag_version,
            fallback_enabled=True,
        )

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
            fallback_enabled=settings.query_engine_auto_fallback_enabled,
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
        if self.mode in {EngineMode.CANARY, EngineMode.SCOPED_STABLE} and not self.canary.eligible(request):
            if self.fallback_enabled:
                return self._fallback(
                    request,
                    context,
                    "canary_control_group"
                    if self.mode == EngineMode.CANARY
                    else "outside_scoped_stable_allowlist",
                )
            raise QueryRoutingError(
                "CANARY_NOT_SELECTED",
                "长尾查询未命中 SQLBot Canary，需澄清或稍后重试",
            )
        return self._sqlbot(
            request,
            context,
            "SQLBOT_CANARY"
            if self.mode == EngineMode.CANARY
            else "SQLBOT_SCOPED_STABLE"
            if self.mode == EngineMode.SCOPED_STABLE
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
            if self.fallback_enabled:
                return self._fallback(request, context, str(exc.code))
            raise QueryRoutingError(str(exc.code), exc.message) from exc
        except ValueError as exc:
            if self.fallback_enabled:
                return self._fallback(request, context, "SQLBOT_POLICY_DENIED")
            raise QueryRoutingError("SQLBOT_POLICY_DENIED", str(exc)) from exc
        except Exception as exc:
            if self.fallback_enabled:
                return self._fallback(request, context, "SQLBOT_UNEXPECTED_FAILURE")
            raise QueryRoutingError(
                "SQLBOT_UNEXPECTED_FAILURE", "SQLBot query failed"
            ) from exc
        self._record_route(
            request,
            context,
            decision,
            reason,
            result,
        )
        return RoutedQueryResult(result, decision, reason)

    def _fallback(
        self,
        request: QueryRequest,
        context: QueryContext,
        reason: str,
    ) -> RoutedQueryResult:
        result = self.deterministic.execute(request, context)
        result = replace(result, warnings=(*result.warnings, f"SQLBOT_FALLBACK:{reason}"))
        self._record_route(
            request,
            context,
            "DETERMINISTIC_FALLBACK",
            reason,
            result,
        )
        return RoutedQueryResult(
            result,
            "DETERMINISTIC_FALLBACK",
            reason,
        )

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
