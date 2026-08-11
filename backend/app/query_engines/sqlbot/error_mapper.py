from enum import StrEnum

import httpx


class SQLBotErrorCode(StrEnum):
    DISABLED = "SQLBOT_DISABLED"
    RUNTIME_PENDING = "SQLBOT_RUNTIME_PENDING"
    NOT_CONFIGURED = "SQLBOT_NOT_CONFIGURED"
    AUTH_FAILED = "SQLBOT_AUTH_FAILED"
    SESSION_INVALID = "SQLBOT_SESSION_INVALID"
    TIMEOUT = "SQLBOT_TIMEOUT"
    CANCELLED = "SQLBOT_CANCELLED"
    CIRCUIT_OPEN = "SQLBOT_CIRCUIT_OPEN"
    UPSTREAM_UNAVAILABLE = "SQLBOT_UPSTREAM_UNAVAILABLE"
    MODEL_REFUSAL = "SQLBOT_MODEL_REFUSAL"
    NEEDS_CLARIFICATION = "SQLBOT_NEEDS_CLARIFICATION"
    RESPONSE_INVALID = "SQLBOT_RESPONSE_INVALID"
    POLICY_DENIED = "SQLBOT_POLICY_DENIED"


class SQLBotEngineError(RuntimeError):
    def __init__(
        self,
        code: SQLBotErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def map_http_error(exc: Exception) -> SQLBotEngineError:
    if isinstance(exc, httpx.TimeoutException):
        return SQLBotEngineError(
            SQLBotErrorCode.TIMEOUT,
            "SQLBot 请求超时",
            retryable=True,
        )
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            return SQLBotEngineError(
                SQLBotErrorCode.SESSION_INVALID,
                "SQLBot 会话认证失效",
                retryable=True,
            )
        if status in {408, 429, 502, 503, 504}:
            return SQLBotEngineError(
                SQLBotErrorCode.UPSTREAM_UNAVAILABLE,
                "SQLBot 暂时不可用",
                retryable=True,
            )
        return SQLBotEngineError(
            SQLBotErrorCode.UPSTREAM_UNAVAILABLE,
            "SQLBot 返回受控错误",
        )
    if isinstance(exc, httpx.HTTPError):
        return SQLBotEngineError(
            SQLBotErrorCode.UPSTREAM_UNAVAILABLE,
            "SQLBot 网络不可用",
            retryable=True,
        )
    return SQLBotEngineError(
        SQLBotErrorCode.UPSTREAM_UNAVAILABLE,
        "SQLBot 调用失败",
    )
