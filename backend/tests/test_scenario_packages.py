from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.database import SessionLocal
from app.platform.identity import IdentityContext
from app.platform.scenario_packages import (
    REQUIRED_FILES,
    ScenarioPackage,
    ScenarioPackageError,
    ScenarioPackageLoader,
    ScenarioRegistry,
    ScenarioValidator,
)
from app.scenarios.charging_ops.package_adapter import semantic_definition


def identity(subject: str = "owner", tenant: str = "tenant-a") -> IdentityContext:
    return IdentityContext(
        subject_id=subject,
        tenant_id=tenant,
        org_id="org-a",
        workspace_id="workspace-a",
        roles=("analyst_admin",),
        groups=(),
        data_scopes=("all",),
        auth_strength="test",
        issued_at=datetime.now(UTC),
        request_id=f"request-{subject}",
    )


def test_package_loads_all_required_files_and_15_metrics() -> None:
    package = ScenarioPackageLoader().load("charging_ops")
    assert package.scenario_id == "charging_ops"
    assert package.version == "1.0.0"
    assert set(package.documents) == set(REQUIRED_FILES)
    assert len(package.documents["metrics.yaml"]["metrics"]) == 15
    assert ScenarioValidator().validate(package)["status"] == "PASSED"
    definition = semantic_definition(package)
    assert len(definition["metrics"]) == 15
    assert definition["metadata"]["data_classification"] == "simulated"


def test_package_path_and_incomplete_package_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ScenarioPackageError) as exc:
        ScenarioPackageLoader(tmp_path).load("../outside")
    assert exc.value.code == "INVALID_SCENARIO_ID"

    (tmp_path / "empty").mkdir()
    with pytest.raises(ScenarioPackageError) as exc:
        ScenarioPackageLoader(tmp_path).load("empty")
    assert exc.value.code == "PACKAGE_INCOMPLETE"


def test_validator_rejects_secret_key_and_incompatible_platform() -> None:
    package = ScenarioPackageLoader().load("charging_ops")
    documents = dict(package.documents)
    documents["knowledge_manifest.yaml"] = {
        **documents["knowledge_manifest.yaml"],
        "secret": "must-not-be-accepted",
    }
    unsafe = ScenarioPackage(
        root=package.root,
        scenario_id=package.scenario_id,
        version=package.version,
        manifest=package.manifest,
        documents=documents,
        checksum=package.checksum,
    )
    with pytest.raises(ScenarioPackageError) as exc:
        ScenarioValidator().validate(unsafe)
    assert exc.value.code == "PACKAGE_VALIDATION_FAILED"
    assert "must-not-be-accepted" not in exc.value.message

    with pytest.raises(ScenarioPackageError) as exc:
        ScenarioValidator(platform_api_version="2.0.0").validate(package)
    assert exc.value.code == "PACKAGE_VALIDATION_FAILED"


def test_registry_lifecycle_activation_disable_and_scope() -> None:
    package = ScenarioPackageLoader().load("charging_ops")
    with SessionLocal() as db:
        ctx = identity()
        registry = ScenarioRegistry(db)
        installed = registry.install(ctx, package)
        assert installed.status == "INSTALLED"
        validated = registry.validate(ctx, package)
        assert validated.status == "VALIDATED"
        published = registry.publish(ctx, package.scenario_id, package.version)
        assert published.status == "PUBLISHED"
        active = registry.activate(ctx, package.scenario_id, package.version)
        assert active.status == "ACTIVE"
        assert registry.resolve(ctx, package.scenario_id).id == active.id

        outsider = identity("outsider", "tenant-b")
        with pytest.raises(ScenarioPackageError) as exc:
            registry.resolve(outsider, package.scenario_id)
        assert exc.value.code == "SCENARIO_NOT_ACTIVE"

        disabled = registry.disable(ctx, package.scenario_id, package.version)
        assert disabled.status == "DISABLED"
        with pytest.raises(ScenarioPackageError) as exc:
            registry.resolve(ctx, package.scenario_id)
        assert exc.value.code == "SCENARIO_NOT_ACTIVE"


def test_same_package_version_is_immutable() -> None:
    package = ScenarioPackageLoader().load("charging_ops")
    modified = ScenarioPackage(
        root=package.root,
        scenario_id=package.scenario_id,
        version=package.version,
        manifest=package.manifest,
        documents=package.documents,
        checksum="different-checksum",
    )
    with SessionLocal() as db:
        registry = ScenarioRegistry(db)
        registry.install(identity(), package)
        with pytest.raises(ScenarioPackageError) as exc:
            registry.install(identity(), modified)
        assert exc.value.code == "IMMUTABLE_PACKAGE_CONFLICT"

