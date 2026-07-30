import os
import re
from pathlib import Path
from typing import Protocol

from app.platform.connectors.contracts import ConnectorConfig
from app.platform.connectors.errors import ConnectorError, ConnectorErrorCode

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
CREDENTIAL_REF = re.compile(r"^env://([A-Z][A-Z0-9_]*)$")
PLAINTEXT_KEYS = {"password", "passwd", "pwd", "secret", "token", "api_key", "access_key"}


class CredentialProvider(Protocol):
    def resolve(self, credential_ref: str) -> str:
        ...


class EnvironmentCredentialProvider:
    def resolve(self, credential_ref: str) -> str:
        match = CREDENTIAL_REF.fullmatch(credential_ref)
        if not match:
            raise ConnectorError(ConnectorErrorCode.CREDENTIAL_ERROR, "凭据引用格式不受支持")
        value = os.getenv(match.group(1))
        if not value:
            raise ConnectorError(ConnectorErrorCode.CREDENTIAL_ERROR, "凭据引用尚未配置")
        return value


class StaticCredentialProvider:
    """Test-only provider. Values are never exposed through connector results."""

    def __init__(self, values: dict[str, str]):
        self._values = values

    def resolve(self, credential_ref: str) -> str:
        try:
            return self._values[credential_ref]
        except KeyError as exc:
            raise ConnectorError(ConnectorErrorCode.CREDENTIAL_ERROR, "凭据引用尚未配置") from exc


def validate_no_plaintext_credentials(config: ConnectorConfig) -> None:
    keys = {str(key).lower() for key in config.options}
    if keys & PLAINTEXT_KEYS:
        raise ConnectorError(ConnectorErrorCode.POLICY_DENIED, "配置中禁止包含明文凭据")
    if config.credential_ref and not CREDENTIAL_REF.fullmatch(config.credential_ref):
        raise ConnectorError(ConnectorErrorCode.CREDENTIAL_ERROR, "凭据必须使用受控引用")


def validate_identifier(value: str, kind: str = "标识符") -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ConnectorError(ConnectorErrorCode.POLICY_DENIED, f"{kind}不符合安全规则")
    return value


def resolve_controlled_path(root: str | Path, locator: str, suffixes: set[str]) -> Path:
    candidate = Path(locator)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ConnectorError(ConnectorErrorCode.POLICY_DENIED, "文件必须位于受控导入目录")
    root_path = Path(root).resolve()
    path = (root_path / candidate).resolve()
    if path != root_path and root_path not in path.parents:
        raise ConnectorError(ConnectorErrorCode.POLICY_DENIED, "文件路径超出受控导入目录")
    if path.suffix.lower() not in suffixes:
        raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "文件类型不受支持")
    if not path.is_file():
        raise ConnectorError(ConnectorErrorCode.SOURCE_UNAVAILABLE, "数据文件不存在")
    return path


def safe_config(config: ConnectorConfig) -> dict:
    return {
        "connector_id": config.connector_id,
        "connector_type": config.connector_type,
        "options": {key: value for key, value in config.options.items() if str(key).lower() not in PLAINTEXT_KEYS},
        "credential_configured": bool(config.credential_ref),
    }

