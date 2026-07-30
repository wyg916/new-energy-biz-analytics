from dataclasses import dataclass
from datetime import datetime


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

