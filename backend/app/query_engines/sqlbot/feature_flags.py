from dataclasses import dataclass

from app.core.config import get_settings
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)


@dataclass(frozen=True)
class SQLBotFeatureFlags:
    enabled: bool
    runtime_verified: bool

    @classmethod
    def from_settings(cls) -> "SQLBotFeatureFlags":
        settings = get_settings()
        return cls(
            enabled=settings.sqlbot_engine_enabled,
            runtime_verified=settings.sqlbot_runtime_verified,
        )

    def require_runtime(self) -> None:
        if not self.enabled:
            raise SQLBotEngineError(
                SQLBotErrorCode.DISABLED,
                "SQLBot 引擎未启用",
            )
        if not self.runtime_verified:
            raise SQLBotEngineError(
                SQLBotErrorCode.RUNTIME_PENDING,
                "SQLBot 真实运行时尚未验收",
            )
