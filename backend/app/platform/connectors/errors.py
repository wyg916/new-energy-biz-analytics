from enum import StrEnum


class ConnectorErrorCode(StrEnum):
    CONFIG_ERROR = "CONFIG_ERROR"
    CREDENTIAL_ERROR = "CREDENTIAL_ERROR"
    POLICY_DENIED = "POLICY_DENIED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    DATA_ERROR = "DATA_ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class ConnectorError(RuntimeError):
    """Stable connector error that never carries a secret or raw driver payload."""

    def __init__(self, code: ConnectorErrorCode, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_dict(self) -> dict:
        return {"code": self.code.value, "message": self.message, "retryable": self.retryable}


def map_driver_error(exc: Exception) -> ConnectorError:
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return ConnectorError(ConnectorErrorCode.TIMEOUT, "数据源操作超时", retryable=True)
    if any(marker in text for marker in ("password", "authentication", "access denied")):
        return ConnectorError(ConnectorErrorCode.CREDENTIAL_ERROR, "数据源认证失败")
    if any(marker in text for marker in ("connection", "unavailable", "refused", "network")):
        return ConnectorError(ConnectorErrorCode.SOURCE_UNAVAILABLE, "数据源当前不可用", retryable=True)
    return ConnectorError(ConnectorErrorCode.DATA_ERROR, "数据源返回无法处理的结果")

