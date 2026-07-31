class ModelGatewayError(RuntimeError):
    code = "MODEL_GATEWAY_ERROR"
    retryable = False

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider


class CredentialReferenceError(ModelGatewayError):
    code = "CREDENTIAL_REFERENCE_INVALID"


class CredentialUnavailableError(ModelGatewayError):
    code = "CREDENTIAL_UNAVAILABLE"


class ModelNotConfiguredError(ModelGatewayError):
    code = "MODEL_NOT_CONFIGURED"


class ModelPolicyDeniedError(ModelGatewayError):
    code = "MODEL_POLICY_DENIED"


class ModelTimeoutError(ModelGatewayError):
    code = "MODEL_TIMEOUT"
    retryable = True


class ModelTransportError(ModelGatewayError):
    code = "MODEL_TRANSPORT_ERROR"
    retryable = True


class ModelProviderError(ModelGatewayError):
    code = "MODEL_PROVIDER_ERROR"

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.retryable = retryable
        self.status_code = status_code


class ModelCircuitOpenError(ModelGatewayError):
    code = "MODEL_CIRCUIT_OPEN"
