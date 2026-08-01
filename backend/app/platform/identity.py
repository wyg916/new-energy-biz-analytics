from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.core.config import get_settings


@dataclass(frozen=True)
class IdentityContext:
    subject_id: str
    tenant_id: str
    org_id: str
    workspace_id: str
    roles: tuple[str, ...]
    groups: tuple[str, ...]
    data_scopes: tuple[str, ...]
    auth_strength: str
    issued_at: datetime
    request_id: str
    principal_id: str | None = None
    provider_code: str = "LOCAL"


class IdentityContextFactory:
    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def from_user(user, *, request_id: str | None = None) -> IdentityContext:
        settings = get_settings()
        scopes = (f"region:{user.region_code}",) if user.region_code else ("workspace:all",)
        return IdentityContext(
            subject_id=f"user:{user.id}",
            tenant_id=settings.platform_tenant_id,
            org_id=settings.platform_org_id,
            workspace_id=settings.platform_workspace_id,
            roles=(user.role,),
            groups=(),
            data_scopes=scopes,
            auth_strength="local-jwt",
            issued_at=datetime.now(UTC),
            request_id=request_id or f"REQ-{uuid4()}",
            principal_id=f"PRN-LOCAL-{user.id}",
            provider_code="LOCAL",
        )
