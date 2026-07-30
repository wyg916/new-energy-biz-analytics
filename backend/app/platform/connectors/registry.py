from collections.abc import Callable

from app.platform.connectors.base import Connector
from app.platform.connectors.contracts import ConnectorConfig
from app.platform.connectors.errors import ConnectorError, ConnectorErrorCode
from app.platform.connectors.security import CredentialProvider, EnvironmentCredentialProvider

ConnectorFactory = Callable[[ConnectorConfig, CredentialProvider], Connector]


class ConnectorRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}

    def register(self, connector_type: str, factory: ConnectorFactory, *, replace: bool = False) -> None:
        key = connector_type.strip().lower()
        if not key:
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "连接器类型不能为空")
        if key in self._factories and not replace:
            if self._factories[key] is factory:
                return
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "连接器类型已注册")
        self._factories[key] = factory

    def create(
        self,
        config: ConnectorConfig,
        credential_provider: CredentialProvider | None = None,
    ) -> Connector:
        factory = self._factories.get(config.connector_type.lower())
        if factory is None:
            raise ConnectorError(ConnectorErrorCode.UNSUPPORTED, "连接器类型未注册")
        return factory(config, credential_provider or EnvironmentCredentialProvider())

    def registered_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


connector_registry = ConnectorRegistry()

