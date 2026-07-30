import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.integration import ScenarioPackageRelease
from app.platform.identity import IdentityContext
from app.platform.versioning import version_satisfies

REQUIRED_FILES = (
    "manifest.yaml",
    "data_models.yaml",
    "metrics.yaml",
    "dimensions.yaml",
    "relationships.yaml",
    "terminology.yaml",
    "sql_examples.yaml",
    "diagnostics.yaml",
    "report_templates.yaml",
    "permissions.yaml",
    "response_profiles.yaml",
    "knowledge_manifest.yaml",
)
FORBIDDEN_SECRET_KEYS = {
    "password", "passwd", "pwd", "secret", "token", "api_key", "access_key",
}


class ScenarioPackageError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ScenarioPackage:
    root: Path
    scenario_id: str
    version: str
    manifest: dict
    documents: dict[str, dict | list]
    checksum: str


class ScenarioPackageLoader:
    def __init__(self, root: str | Path | None = None):
        if root is None:
            repository_root = Path(__file__).resolve().parents[3]
            root = repository_root / "scenarios"
            if not Path(root).is_dir():
                root = Path("/app/scenarios")
        self.root = Path(root).resolve()

    def load(self, scenario_id: str) -> ScenarioPackage:
        if not scenario_id or "/" in scenario_id or "\\" in scenario_id or ".." in scenario_id:
            raise ScenarioPackageError("INVALID_SCENARIO_ID", "场景标识不符合安全规则")
        package_root = (self.root / scenario_id).resolve()
        if self.root not in package_root.parents:
            raise ScenarioPackageError("PACKAGE_PATH_DENIED", "场景包路径超出受控根目录")
        missing = [name for name in REQUIRED_FILES if not (package_root / name).is_file()]
        if missing:
            raise ScenarioPackageError("PACKAGE_INCOMPLETE", "场景包缺少必需文件")
        documents: dict[str, dict | list] = {}
        digest = hashlib.sha256()
        for name in REQUIRED_FILES:
            raw = (package_root / name).read_bytes()
            digest.update(name.encode())
            digest.update(raw)
            try:
                documents[name] = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ScenarioPackageError(
                    "PACKAGE_PARSE_ERROR",
                    "场景 YAML 必须使用受控 JSON 兼容子集",
                ) from exc
        manifest = documents["manifest.yaml"]
        if not isinstance(manifest, dict):
            raise ScenarioPackageError("MANIFEST_INVALID", "场景 manifest 必须是对象")
        return ScenarioPackage(
            root=package_root,
            scenario_id=str(manifest.get("scenario_id", "")),
            version=str(manifest.get("version", "")),
            manifest=manifest,
            documents=documents,
            checksum=digest.hexdigest(),
        )


class ScenarioValidator:
    def __init__(self, platform_api_version: str = "0.1.0"):
        self.platform_api_version = platform_api_version

    def validate(self, package: ScenarioPackage) -> dict:
        errors: list[str] = []
        if package.scenario_id != package.root.name:
            errors.append("scenario_id_mismatch")
        if not package.version:
            errors.append("missing_version")
        api_range = str(package.manifest.get("platform_api_range", ""))
        try:
            if not version_satisfies(self.platform_api_version, api_range):
                errors.append("platform_api_incompatible")
        except ValueError:
            errors.append("platform_api_range_invalid")
        if package.manifest.get("data_classification") != "simulated":
            errors.append("data_classification_must_be_simulated")
        declared = set(package.manifest.get("files", []))
        if declared != set(REQUIRED_FILES) - {"manifest.yaml"}:
            errors.append("file_manifest_mismatch")
        if self._contains_secret_key(package.documents):
            errors.append("forbidden_secret_key")
        metrics = package.documents["metrics.yaml"]
        if not isinstance(metrics, dict) or not isinstance(metrics.get("metrics"), list):
            errors.append("metrics_invalid")
        else:
            codes = [item.get("code") for item in metrics["metrics"] if isinstance(item, dict)]
            if not codes or len(codes) != len(set(codes)):
                errors.append("metric_codes_invalid")
        result = {
            "status": "PASSED" if not errors else "FAILED",
            "errors": errors,
            "checksum": package.checksum,
            "validated_files": len(REQUIRED_FILES),
        }
        if errors:
            raise ScenarioPackageError("PACKAGE_VALIDATION_FAILED", json.dumps(result, sort_keys=True))
        return result

    def _contains_secret_key(self, value: object) -> bool:
        if isinstance(value, dict):
            return any(
                str(key).lower() in FORBIDDEN_SECRET_KEYS
                or self._contains_secret_key(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(self._contains_secret_key(item) for item in value)
        return False


class ScenarioRegistry:
    def __init__(self, db: Session):
        self.db = db

    def install(
        self,
        identity: IdentityContext,
        package: ScenarioPackage,
    ) -> ScenarioPackageRelease:
        existing = self.db.scalar(select(ScenarioPackageRelease).where(
            ScenarioPackageRelease.scenario_id == package.scenario_id,
            ScenarioPackageRelease.version == package.version,
        ))
        if existing:
            if existing.manifest_checksum != package.checksum:
                raise ScenarioPackageError(
                    "IMMUTABLE_PACKAGE_CONFLICT",
                    "同版本场景包校验和发生冲突",
                )
            return existing
        release = ScenarioPackageRelease(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            scenario_id=package.scenario_id,
            version=package.version,
            display_name=str(package.manifest["display_name"]),
            manifest_json=json.dumps(package.manifest, ensure_ascii=False, sort_keys=True),
            manifest_checksum=package.checksum,
            status="INSTALLED",
            package_root=str(package.root),
            platform_api_range=str(package.manifest["platform_api_range"]),
            validation_json="{}",
            installed_at=datetime.now(UTC),
        )
        self.db.add(release)
        self.db.commit()
        return release

    def validate(
        self,
        identity: IdentityContext,
        package: ScenarioPackage,
        validator: ScenarioValidator | None = None,
    ) -> ScenarioPackageRelease:
        release = self.install(identity, package)
        self._scope(identity, release)
        result = (validator or ScenarioValidator()).validate(package)
        release.status = "VALIDATED"
        release.validation_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
        release.validated_at = datetime.now(UTC)
        self.db.commit()
        return release

    def publish(
        self,
        identity: IdentityContext,
        scenario_id: str,
        version: str,
    ) -> ScenarioPackageRelease:
        release = self._release(identity, scenario_id, version)
        if release.status not in {"VALIDATED", "PUBLISHED"}:
            raise ScenarioPackageError("INVALID_STATE", "只有校验通过的场景包可以发布")
        release.status = "PUBLISHED"
        release.published_at = release.published_at or datetime.now(UTC)
        self.db.commit()
        return release

    def activate(
        self,
        identity: IdentityContext,
        scenario_id: str,
        version: str,
    ) -> ScenarioPackageRelease:
        release = self._release(identity, scenario_id, version, lock=True)
        if release.status not in {"PUBLISHED", "ACTIVE"}:
            raise ScenarioPackageError("INVALID_STATE", "只有已发布场景包可以激活")
        current = list(self.db.scalars(
            select(ScenarioPackageRelease)
            .where(
                ScenarioPackageRelease.tenant_id == identity.tenant_id,
                ScenarioPackageRelease.workspace_id == identity.workspace_id,
                ScenarioPackageRelease.scenario_id == scenario_id,
                ScenarioPackageRelease.status == "ACTIVE",
            )
            .with_for_update()
        ))
        for item in current:
            if item.id != release.id:
                item.status = "DISABLED"
                item.disabled_at = datetime.now(UTC)
        release.status = "ACTIVE"
        release.activated_at = datetime.now(UTC)
        release.disabled_at = None
        self.db.commit()
        return release

    def disable(
        self,
        identity: IdentityContext,
        scenario_id: str,
        version: str,
    ) -> ScenarioPackageRelease:
        release = self._release(identity, scenario_id, version, lock=True)
        release.status = "DISABLED"
        release.disabled_at = datetime.now(UTC)
        self.db.commit()
        return release

    def resolve(
        self,
        identity: IdentityContext,
        scenario_id: str,
    ) -> ScenarioPackageRelease:
        release = self.db.scalar(select(ScenarioPackageRelease).where(
            ScenarioPackageRelease.tenant_id == identity.tenant_id,
            ScenarioPackageRelease.workspace_id == identity.workspace_id,
            ScenarioPackageRelease.scenario_id == scenario_id,
            ScenarioPackageRelease.status == "ACTIVE",
        ).order_by(ScenarioPackageRelease.activated_at.desc()))
        if release is None:
            raise ScenarioPackageError("SCENARIO_NOT_ACTIVE", "场景未激活或不在当前身份范围")
        return release

    def _release(
        self,
        identity: IdentityContext,
        scenario_id: str,
        version: str,
        *,
        lock: bool = False,
    ) -> ScenarioPackageRelease:
        query = select(ScenarioPackageRelease).where(
            ScenarioPackageRelease.scenario_id == scenario_id,
            ScenarioPackageRelease.version == version,
        )
        if lock:
            query = query.with_for_update()
        release = self.db.scalar(query)
        if release is None:
            raise ScenarioPackageError("PACKAGE_NOT_FOUND", "场景包版本不存在")
        self._scope(identity, release)
        return release

    @staticmethod
    def _scope(identity: IdentityContext, release: ScenarioPackageRelease) -> None:
        if (
            release.tenant_id != identity.tenant_id
            or release.workspace_id != identity.workspace_id
        ):
            raise ScenarioPackageError("PACKAGE_NOT_FOUND", "场景包版本不存在")

