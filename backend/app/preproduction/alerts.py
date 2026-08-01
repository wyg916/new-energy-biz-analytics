from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.governance.audit import record_governance_event
from app.governance.authorization import AuthorizationService, request_context
from app.governance.models import SecurityAlert
from app.governance.secrets import CredentialReferenceService, SecretResolutionError
from app.platform.identity import IdentityContext
from app.preproduction.models import ExternalAlertDelivery


class ExternalAlertError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _Circuit:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.failures = 0
        self.open_until = 0.0

    def before(self) -> None:
        with self.lock:
            if self.open_until > time.monotonic():
                raise ExternalAlertError("EXTERNAL_ALERT_CIRCUIT_OPEN", "外部告警熔断器已打开")

    def success(self) -> None:
        with self.lock:
            self.failures = 0
            self.open_until = 0.0

    def failure(self, threshold: int, recovery_seconds: int) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= threshold:
                self.open_until = time.monotonic() + recovery_seconds

    def status(self) -> str:
        with self.lock:
            return "OPEN" if self.open_until > time.monotonic() else "CLOSED"


_CIRCUIT = _Circuit()


class SignedWebhookAlertAdapter:
    """Disabled-by-default signed webhook with redacted payload and durable idempotency."""

    def __init__(
        self,
        db: Session,
        identity: IdentityContext,
        *,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.db = db
        self.identity = identity
        self.settings = settings or get_settings()
        self.client = client or httpx.Client(timeout=self.settings.external_alert_timeout_seconds, follow_redirects=False)

    def health(self) -> dict:
        parsed = urlparse(self.settings.external_alert_webhook_url)
        configured = bool(self.settings.external_alert_enabled and parsed.scheme in {"http", "https"} and parsed.hostname)
        return {
            "configured": configured,
            "enabled": self.settings.external_alert_enabled,
            "status": "READY" if configured and _CIRCUIT.status() == "CLOSED" else ("DISABLED" if not self.settings.external_alert_enabled else "UNAVAILABLE"),
            "circuit": _CIRCUIT.status(),
            "circuit_state": _CIRCUIT.status(),
            "endpoint_hash": hashlib.sha256(self.settings.external_alert_webhook_url.encode()).hexdigest() if parsed.hostname else None,
        }

    def deliver(self, alert_id: str, *, idempotency_key: str | None = None) -> dict:
        self._authorize(alert_id)
        if not self.settings.external_alert_enabled:
            raise ExternalAlertError("EXTERNAL_ALERT_DISABLED", "外部告警适配器默认禁用")
        parsed = urlparse(self.settings.external_alert_webhook_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ExternalAlertError("EXTERNAL_ALERT_ENDPOINT_INVALID", "外部告警端点未安全配置")
        _CIRCUIT.before()
        alert = self.db.get(SecurityAlert, alert_id)
        if alert is None or alert.tenant_id != self.identity.tenant_id or alert.workspace_id != self.identity.workspace_id:
            raise ExternalAlertError("SECURITY_ALERT_NOT_FOUND", "站内告警不存在")
        key = idempotency_key or f"{alert.alert_id}:{alert.event_count}:{alert.status}"
        existing = self.db.scalar(select(ExternalAlertDelivery).where(ExternalAlertDelivery.idempotency_key == key))
        if existing is not None:
            return self._payload(existing, replay=True)
        payload = {
            "schema_version": "p4-alert-1",
            "alert_id": alert.alert_id,
            "rule_code": alert.rule_code,
            "severity": alert.severity,
            "status": alert.status,
            "environment": "preproduction",
            "data_classification": "simulated",
            "trace_hash": hashlib.sha256(alert.trace_id.encode()).hexdigest(),
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        endpoint_hash = hashlib.sha256(self.settings.external_alert_webhook_url.encode()).hexdigest()
        delivery = ExternalAlertDelivery(
            delivery_id=f"DELIVERY-{uuid4()}", alert_id=alert.alert_id, idempotency_key=key,
            status="PENDING", attempts=0, endpoint_hash=endpoint_hash,
            payload_hash=hashlib.sha256(encoded).hexdigest(), trace_id=self.identity.request_id,
        )
        self.db.add(delivery)
        self.db.flush()
        try:
            service = CredentialReferenceService(self.db, self.identity)
            reference = service.active_by_name(self.settings.external_alert_signing_reference_name)
            signing_key = service.resolve(
                reference.credential_ref_id,
                action="alert.sign",
                trace_id=self.identity.request_id,
            ).value.encode()
        except SecretResolutionError as exc:
            delivery.status = "FAILED"
            delivery.last_error_code = exc.code
            self._audit(delivery, "external_alert.delivery_failed", "FAILED", exc.code)
            self.db.commit()
            raise ExternalAlertError(exc.code, "外部告警签名凭据不可用") from exc
        signature = hmac.new(signing_key, encoded, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-P4-Signature": f"sha256={signature}",
            "X-P4-Idempotency-Key": key,
            "X-P4-Schema-Version": "p4-alert-1",
        }
        last_code = "EXTERNAL_ALERT_DELIVERY_FAILED"
        for attempt in range(1, self.settings.external_alert_max_attempts + 1):
            delivery.attempts = attempt
            try:
                response = self.client.post(self.settings.external_alert_webhook_url, content=encoded, headers=headers)
                delivery.last_http_status = response.status_code
                if 200 <= response.status_code < 300:
                    delivery.status = "DELIVERED"
                    delivery.delivered_at = datetime.now(UTC)
                    delivery.last_error_code = None
                    _CIRCUIT.success()
                    self._audit(delivery, "external_alert.delivered", "SUCCESS", None)
                    self.db.commit()
                    return self._payload(delivery, replay=False)
                last_code = f"EXTERNAL_ALERT_HTTP_{response.status_code}"
            except httpx.TimeoutException:
                last_code = "EXTERNAL_ALERT_TIMEOUT"
            except httpx.HTTPError:
                last_code = "EXTERNAL_ALERT_TRANSPORT_ERROR"
        delivery.status = "FAILED"
        delivery.last_error_code = last_code
        _CIRCUIT.failure(
            self.settings.external_alert_circuit_threshold,
            self.settings.external_alert_circuit_recovery_seconds,
        )
        self._audit(delivery, "external_alert.delivery_failed", "FAILED", last_code)
        self.db.commit()
        raise ExternalAlertError(last_code, "外部告警发送失败")

    def _authorize(self, alert_id: str) -> None:
        AuthorizationService(self.db, self.identity).require(request_context(
            self.identity, action="alert.manage", resource_type="security_alert",
            resource_id=alert_id, environment=self.settings.app_env,
            trace_id=self.identity.request_id,
        ))

    def _audit(self, delivery: ExternalAlertDelivery, action: str, result: str, error_code: str | None) -> None:
        record_governance_event(
            self.db, self.identity, action=action, resource_type="external_alert_delivery",
            resource_id=delivery.delivery_id, result=result,
            detail={"attempts": delivery.attempts, "error_code": error_code, "payload_redacted": True},
        )

    @staticmethod
    def _payload(delivery: ExternalAlertDelivery, *, replay: bool) -> dict:
        return {
            "delivery_id": delivery.delivery_id, "alert_id": delivery.alert_id,
            "status": delivery.status, "attempts": delivery.attempts,
            "idempotent_replay": replay, "payload_redacted": True,
            "last_error_code": delivery.last_error_code,
            "delivered_at": delivery.delivered_at.isoformat() if delivery.delivered_at else None,
        }
