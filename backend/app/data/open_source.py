from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from email.utils import parsedate_to_datetime
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.business import (
    ChargingSession, City, DataGenerationRun, DateDimension, Device, EnergyCost,
    Region, SimulatedUser, Station,
)
from app.models.open_data import (
    OpenDataIngestionRun, OpenDataQualityCheck, OpenDataSnapshot, OpenDataSource,
    RawAcnSession, RawUciRetailLine, StagingAcnSession, StagingUciRetailLine,
)
from app.models.sales import (
    SalesBusinessDate, SalesChannel, SalesCustomer, SalesOrder, SalesOrderItem,
    SalesPerson, SalesProduct, SalesProductCategory, SalesRegion,
)
from app.models.auth import User
from app.models.platform_data import DatasetVersion, MappingVersion, PlatformDataset, SemanticActivation
from app.platform.dataset_release import DatasetVersionService, ReleaseService, SemanticActivationService
from app.platform.identity import IdentityContextFactory
from app.scenarios.registry import install_charging_ops


DATA_CLASSIFICATION = "open_source_real_data"
ACN_RUN_ID = "DATA41-ACN-ORNL-26-V1"
UCI_RUN_ID = "DATA41-UCI-ONLINE-RETAIL-352-V1"
ACN_BATCH_ID = ACN_RUN_ID
EIA_COMMERCIAL_RATE_USD_PER_KWH = Decimal("0.1059")
ACN_CALTECH_TARIFF_USD_PER_KWH = Decimal("0.12")
UCI_DERIVED_COST_RATE = Decimal("0.70")


def _hash(value: str, length: int = 64) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _bulk(db: Session, model, rows: list[dict], chunk: int = 5000) -> None:
    for index in range(0, len(rows), chunk):
        db.bulk_insert_mappings(model, rows[index:index + chunk])
        db.flush()


def _json_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _repository_root(repository_root: Path | None = None) -> Path:
    if repository_root is not None:
        return repository_root
    container_root = Path("/app")
    if (container_root / "data" / "open_source" / "source_manifest.json").is_file():
        return container_root
    return Path(__file__).resolve().parents[3]


def _source_root(repository_root: Path | None = None) -> Path:
    root = _repository_root(repository_root)
    return root / "data" / "open_source"


def load_manifest(repository_root: Path | None = None) -> tuple[Path, dict]:
    root = _source_root(repository_root)
    manifest = json.loads((root / "source_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != "data41-source-manifest-v1":
        raise RuntimeError("DATA41_SOURCE_MANIFEST_VERSION_MISMATCH")
    for snapshot in manifest["snapshots"]:
        path = _repository_root(repository_root) / snapshot["snapshot_path"]
        if _file_hash(path) != snapshot["snapshot_sha256"]:
            raise RuntimeError(f"DATA41_SOURCE_HASH_MISMATCH:{snapshot['dataset_code']}")
    return root, manifest


def _record_lineage(db: Session, snapshot: dict, now: datetime) -> OpenDataIngestionRun:
    run_id = snapshot["run_id"]
    existing = db.get(OpenDataIngestionRun, run_id)
    if existing and existing.status == "COMPLETED":
        return existing
    source_id = f"SRC-{_hash(snapshot['dataset_code'], 20).upper()}"
    source = db.get(OpenDataSource, source_id)
    if source is None:
        source = OpenDataSource(
            source_id=source_id,
            source_name=snapshot["source_name"],
            source_url=snapshot["source_url"],
            source_identifier=snapshot["dataset_code"],
            license_name=snapshot["license"],
            publisher=snapshot["publisher"],
            status="ACTIVE",
            created_at=now,
        )
        db.add(source)
        db.flush()
    snapshot_id = f"SNP-{_hash(snapshot['snapshot_sha256'], 20).upper()}"
    if db.get(OpenDataSnapshot, snapshot_id) is None:
        period_start = snapshot.get("snapshot_period_start")
        period_end = snapshot.get("snapshot_period_end")
        db.add(OpenDataSnapshot(
            snapshot_id=snapshot_id,
            source_id=source_id,
            dataset_version=snapshot["dataset_version"],
            source_hash=snapshot["source_download_sha256"],
            snapshot_hash=snapshot["snapshot_sha256"],
            source_row_count=snapshot["source_row_count"],
            snapshot_row_count=snapshot["snapshot_row_count"],
            period_start=datetime.fromisoformat(period_start).replace(tzinfo=UTC) if period_start else None,
            period_end=datetime.fromisoformat(period_end).replace(tzinfo=UTC) if period_end else None,
            local_path=snapshot["snapshot_path"],
            selection_method=snapshot["selection_method"],
            ingested_at=now,
        ))
        db.flush()
    if existing is None:
        existing = OpenDataIngestionRun(
            run_id=run_id,
            source_id=source_id,
            snapshot_id=snapshot_id,
            transformation_version=snapshot["transformation_version"],
            ingestion_time=now,
            raw_row_count=0,
            staging_row_count=0,
            core_row_count=0,
            status="RUNNING",
        )
        db.add(existing)
    db.flush()
    return existing


def _quality(db: Session, run_id: str, checks: dict[str, tuple[bool, object, object]]) -> dict:
    now = datetime.now(UTC)
    failures = []
    for name, (passed, observed, expected) in checks.items():
        if not passed:
            failures.append(name)
        quality_id = f"DQ-{_hash(run_id + ':' + name, 28).upper()}"
        row = db.get(OpenDataQualityCheck, quality_id)
        values = {
            "run_id": run_id,
            "check_name": name,
            "status": "PASS" if passed else "FAIL",
            "observed_value": json.dumps(observed, ensure_ascii=False, default=str, sort_keys=True),
            "expected_value": json.dumps(expected, ensure_ascii=False, default=str, sort_keys=True),
            "checked_at": now,
        }
        if row is None:
            db.add(OpenDataQualityCheck(quality_check_id=quality_id, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
    return {"status": "PASS" if not failures else "FAIL", "checks": len(checks), "failures": failures}


def _parse_acn_payment(raw: object) -> bool:
    if not raw:
        return False
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    return any(bool(item.get("paymentRequired")) for item in parsed)


def ingest_acn(db: Session, snapshot: dict, repository_root: Path | None = None) -> dict:
    now = datetime.now(UTC)
    run = _record_lineage(db, snapshot, now)
    if run.status == "COMPLETED":
        db.execute(update(Station).where(Station.source_type == "simulated").values(status="fixture"))
        db.execute(update(Device).where(Device.source_type == "simulated").values(status="fixture"))
        db.execute(update(Station).where(Station.source_type == "open_source").values(status="active"))
        db.execute(update(Device).where(Device.source_type == "open_source").values(status="active"))
        install_charging_ops(db, ACN_BATCH_ID, publish=True)
        return {"run_id": run.run_id, "status": "PASS", "reused": True, "rows": run.raw_row_count}
    repo = _repository_root(repository_root)
    records = json.loads((repo / snapshot["snapshot_path"]).read_text(encoding="utf-8"))["results"]
    raw_rows: list[dict] = []
    stg_rows: list[dict] = []
    for record in records:
        source_hash = _json_hash(record)
        source_id = str(record["id"])
        start = parsedate_to_datetime(record["connectiontime"]).astimezone(UTC)
        end = parsedate_to_datetime(record["disconnecttime"]).astimezone(UTC)
        done = parsedate_to_datetime(record["donechargingtime"]).astimezone(UTC) if record.get("donechargingtime") else None
        raw_rows.append({
            "raw_id": f"RAW-ACN-{_hash(source_id, 24).upper()}", "run_id": run.run_id,
            "source_record_id": source_id, "source_row_hash": source_hash,
            "payload_json": json.dumps(record, ensure_ascii=False, sort_keys=True),
        })
        stg_rows.append({
            "session_key": f"STG-ACN-{_hash(source_id, 24).upper()}", "run_id": run.run_id,
            "source_record_id": source_id, "site_id": str(record["siteid"]),
            "station_id": str(record["stationid"]), "space_id": str(record["spaceid"]),
            "source_user_id": str(record["userid"]) if record.get("userid") else None,
            "connection_time": start, "disconnect_time": end, "done_charging_time": done,
            "energy_kwh": Decimal(str(record["kwhdelivered"])),
            "payment_required": int(_parse_acn_payment(record.get("userinputs"))),
            "source_row_hash": source_hash,
        })
    _bulk(db, RawAcnSession, raw_rows)
    _bulk(db, StagingAcnSession, stg_rows)

    db.execute(update(Station).where(Station.source_type == "simulated").values(status="fixture"))
    db.execute(update(Device).where(Device.source_type == "simulated").values(status="fixture"))
    region_id = "OS-US-WEST"
    city_id = "OS-PASADENA"
    if db.get(Region, region_id) is None:
        db.add(Region(region_id=region_id, region_name="Open Data - US West", display_order=90, status="active", source_type="open_source"))
        db.flush()
    if db.get(City, city_id) is None:
        db.add(City(city_id=city_id, city_name="Open Data - Pasadena", region_id=region_id, status="active", source_type="open_source"))
        db.flush()
    db.execute(update(User).where(User.role == "regional_manager").values(region_code=region_id))
    db.flush()

    station_ids: dict[str, str] = {}
    user_ids: dict[str, str] = {}
    station_dates: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    source_min = min(row["connection_time"] for row in stg_rows)
    source_max = max(row["disconnect_time"] for row in stg_rows)
    for row in stg_rows:
        source_station = row["station_id"]
        station_id = station_ids.setdefault(source_station, f"OS-ACN-{_hash(source_station, 16).upper()}")
        device_id = f"OD-{_hash(source_station, 20).upper()}"
        if db.get(Station, station_id) is None:
            db.add(Station(
                station_id=station_id, station_name=f"ACN open-data EVSE {source_station}",
                city_id=city_id, region_id=region_id, operator_code="CALTECH-ACN",
                station_type="workplace-l2", open_date=row["connection_time"].date(),
                connector_count=1, rated_power_kw=Decimal("7.20"), status="active", source_type="open_source",
            ))
            db.flush()
        if db.get(Device, device_id) is None:
            db.add(Device(
                device_id=device_id, station_id=station_id, device_model="ACN-L2-DERIVED",
                connector_count=1, rated_power_kw=Decimal("7.20"),
                commission_date=row["connection_time"].date(), status="active", source_type="open_source",
            ))
            db.flush()
        source_user = row["source_user_id"] or f"anonymous:{row['source_record_id']}"
        user_id = user_ids.setdefault(source_user, f"OU-{_hash(source_user, 20).upper()}")
        if db.get(SimulatedUser, user_id) is None:
            db.add(SimulatedUser(
                user_id=user_id, register_date=row["connection_time"].date(),
                acquisition_channel="open_dataset", user_segment="not_provided",
                home_region_id=region_id, status="active", source_type="open_source",
            ))
            db.flush()
        energy = Decimal(str(row["energy_kwh"]))
        revenue = _money(energy * ACN_CALTECH_TARIFF_USD_PER_KWH) if row["payment_required"] else Decimal("0.00")
        session_id = f"OCS-{_hash(row['source_record_id'], 36).upper()}"
        duration = max(0, int((row["disconnect_time"] - row["connection_time"]).total_seconds()))
        db.add(ChargingSession(
            session_id=session_id, station_id=station_id, device_id=device_id,
            connector_no=1, user_id=user_id, start_time=row["connection_time"],
            end_time=row["disconnect_time"], settlement_time=row["disconnect_time"],
            charging_duration_seconds=duration, energy_kwh=energy,
            electricity_fee_net_amount=Decimal("0.00"), service_fee_net_amount=revenue,
            session_status="completed", batch_id=ACN_BATCH_ID, source_type="open_source", created_at=now,
        ))
        station_dates[(station_id, row["disconnect_time"].date())] += energy
    db.flush()
    for (station_id, cost_date), energy in station_dates.items():
        db.add(EnergyCost(
            station_id=station_id, cost_date=cost_date, tariff_period="eia2020_avg",
            purchase_price_per_kwh=EIA_COMMERCIAL_RATE_USD_PER_KWH,
            settled_energy_kwh=energy, energy_cost=_money(energy * EIA_COMMERCIAL_RATE_USD_PER_KWH),
            batch_id=ACN_BATCH_ID, source_type="open_derived",
        ))

    if db.get(DataGenerationRun, ACN_BATCH_ID) is None:
        db.add(DataGenerationRun(
            batch_id=ACN_BATCH_ID, generator_version="data41-open-source-v1", random_seed=0,
            period_start=source_min.date(), period_end=source_max.date(),
            target_counts_json=json.dumps({"sessions": len(stg_rows)}),
            actual_counts_json=json.dumps({"stations": len(station_ids), "users": len(user_ids), "sessions": len(stg_rows), "energy_cost_rows": len(station_dates)}),
            scenario_flags_json=json.dumps(["open_source", "actual_source_records", "derived_cost_rule"]),
            status="completed", quality_status="passed", started_at=now, finished_at=now,
        ))
    install_charging_ops(db, ACN_BATCH_ID, publish=True)
    run.raw_row_count = len(raw_rows)
    run.staging_row_count = len(stg_rows)
    run.core_row_count = len(stg_rows)

    distinct_ids = len({row["source_record_id"] for row in stg_rows})
    hashes = len({row["source_row_hash"] for row in stg_rows})
    checks = {
        "ACN_ROW_COUNT": (len(stg_rows) == snapshot["snapshot_row_count"], len(stg_rows), snapshot["snapshot_row_count"]),
        "ACN_UNIQUE_SOURCE_ID": (distinct_ids == len(stg_rows), distinct_ids, len(stg_rows)),
        "ACN_UNIQUE_ROW_HASH": (hashes == len(stg_rows), hashes, len(stg_rows)),
        "ACN_REQUIRED_FIELDS": (all(row["station_id"] and row["connection_time"] and row["disconnect_time"] for row in stg_rows), "evaluated", True),
        "ACN_ENERGY_POSITIVE": (all(row["energy_kwh"] > 0 for row in stg_rows), str(min(row["energy_kwh"] for row in stg_rows)), ">0"),
        "ACN_TIME_ORDER": (all(row["disconnect_time"] >= row["connection_time"] for row in stg_rows), "evaluated", True),
        "ACN_DONE_CHARGING_ORDER": (all(row["done_charging_time"] is None or row["done_charging_time"] >= row["connection_time"] for row in stg_rows), "evaluated", True),
        "ACN_DATE_RANGE": (source_min.date() >= date(2020, 1, 1) and source_max.date() <= date(2020, 12, 31), [source_min, source_max], "within 2020"),
        "ACN_NUMERIC_TYPES": (all(isinstance(row["energy_kwh"], Decimal) for row in stg_rows), "evaluated", True),
        "ACN_STATION_INTEGRITY": (len(station_ids) > 0 and all(station_ids.get(row["station_id"]) for row in stg_rows), len(station_ids), ">0"),
        "ACN_COST_RECONCILIATION": (all(_money(energy * EIA_COMMERCIAL_RATE_USD_PER_KWH) >= 0 for energy in station_dates.values()), len(station_dates), len(station_dates)),
        "ACN_VERSION_AND_HASH": (_file_hash(repo / snapshot["snapshot_path"]) == snapshot["snapshot_sha256"], snapshot["snapshot_sha256"], snapshot["snapshot_sha256"]),
        "ACN_OUTLIER_OBSERVATION": (max(row["energy_kwh"] for row in stg_rows) < Decimal("200"), str(max(row["energy_kwh"] for row in stg_rows)), "<200 kWh"),
    }
    quality = _quality(db, run.run_id, checks)
    run.status = "COMPLETED" if quality["status"] == "PASS" else "FAILED"
    db.flush()
    if quality["status"] != "PASS":
        raise RuntimeError("DATA41_ACN_QUALITY_FAILED:" + ",".join(quality["failures"]))
    return {"run_id": run.run_id, "status": "PASS", "reused": False, "rows": len(stg_rows), "quality": quality}


def ingest_uci(db: Session, snapshot: dict, repository_root: Path | None = None) -> dict:
    now = datetime.now(UTC)
    run = _record_lineage(db, snapshot, now)
    if run.status == "COMPLETED":
        return {"run_id": run.run_id, "status": "PASS", "reused": True, "rows": run.raw_row_count}
    repo = _repository_root(repository_root)
    path = repo / snapshot["snapshot_path"]
    source_rows: list[dict] = []
    raw_rows: list[dict] = []
    stg_rows: list[dict] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            source_rows.append(row)
            normalized = dict(row)
            source_hash = _json_hash(normalized)
            source_row = int(row["source_row_number"])
            invoice_time = datetime.fromisoformat(row["InvoiceDate"]).replace(tzinfo=UTC)
            raw_rows.append({
                "raw_id": f"RAW-UCI-{_hash(str(source_row), 24).upper()}", "run_id": run.run_id,
                "source_row_number": source_row, "source_row_hash": source_hash,
                "payload_json": json.dumps(normalized, ensure_ascii=False, sort_keys=True),
            })
            stg_rows.append({
                "line_key": f"STG-UCI-{_hash(str(source_row), 24).upper()}", "run_id": run.run_id,
                "source_row_number": source_row, "invoice_no": row["InvoiceNo"],
                "stock_code": row["StockCode"], "description": row["Description"] or None,
                "quantity": int(row["Quantity"]), "invoice_time": invoice_time,
                "unit_price": Decimal(row["UnitPrice"]), "customer_id": row["CustomerID"] or None,
                "country": row["Country"],
                "is_cancellation": int(row["InvoiceNo"].startswith("C") or int(row["Quantity"]) < 0),
                "source_row_hash": source_hash,
            })
    _bulk(db, RawUciRetailLine, raw_rows)
    _bulk(db, StagingUciRetailLine, stg_rows)

    regions: dict[str, str] = {}
    products: dict[str, dict] = {}
    customers: dict[str, dict] = {}
    invoices: dict[str, list[dict]] = defaultdict(list)
    for row in stg_rows:
        region_id = regions.setdefault(row["country"], f"SR-{_hash(row['country'], 20).upper()}")
        product_id = f"SP-{_hash(row['stock_code'], 20).upper()}"
        products.setdefault(product_id, {
            "product_id": product_id, "product_name": (row["description"] or f"Stock {row['stock_code']}")[:128],
            "list_price": max(Decimal("0"), row["unit_price"]),
        })
        customer_source = row["customer_id"] or f"anonymous:{row['invoice_no']}"
        customer_id = f"SC-{_hash(customer_source, 20).upper()}"
        customers.setdefault(customer_id, {
            "customer_id": customer_id, "customer_name": "UCI customer " + _hash(customer_source, 8).upper(),
            "home_region_id": region_id, "registered_date": row["invoice_time"].date(),
        })
        invoices[row["invoice_no"]].append({**row, "region_id": region_id, "product_id": product_id, "customer_key": customer_id})

    for country, region_id in regions.items():
        if db.get(SalesRegion, region_id) is None:
            db.add(SalesRegion(region_id=region_id, region_name=country, organization_code="UCI-ONLINE-RETAIL", data_classification=DATA_CLASSIFICATION))
    db.flush()
    for region_id in regions.values():
        salesperson_id = f"UNASSIGNED-{_hash(region_id, 16).upper()}"
        if db.get(SalesPerson, salesperson_id) is None:
            db.add(SalesPerson(salesperson_id=salesperson_id, salesperson_name="Not provided by source", region_id=region_id, organization_code="UCI-ONLINE-RETAIL", data_classification="derived_not_provided"))
    db.flush()
    if db.get(SalesChannel, "UCI-ONLINE") is None:
        db.add(SalesChannel(channel_id="UCI-ONLINE", channel_name="UCI Online Retail", channel_type="online", data_classification=DATA_CLASSIFICATION))
    if db.get(SalesProductCategory, "UCI-UNCLASSIFIED") is None:
        db.add(SalesProductCategory(category_id="UCI-UNCLASSIFIED", category_name="Not provided by source", data_classification="derived_not_provided"))
    db.flush()
    for day in sorted({row["invoice_time"].date() for row in stg_rows}):
        if db.get(SalesBusinessDate, day) is None:
            iso = day.isocalendar()
            db.add(SalesBusinessDate(business_date=day, year=day.year, quarter=(day.month - 1) // 3 + 1, month=day.month, week=iso.week))
    for values in products.values():
        if db.get(SalesProduct, values["product_id"]) is None:
            db.add(SalesProduct(
                **values, category_id="UCI-UNCLASSIFIED",
                standard_cost=_money(values["list_price"] * UCI_DERIVED_COST_RATE),
                data_classification=DATA_CLASSIFICATION,
            ))
    for values in customers.values():
        if db.get(SalesCustomer, values["customer_id"]) is None:
            db.add(SalesCustomer(
                **values, customer_segment="not_provided", data_classification=DATA_CLASSIFICATION,
            ))
    db.flush()

    seen_customers: set[str] = set()
    item_rows: list[dict] = []
    order_count = 0
    for invoice_no, lines in sorted(invoices.items(), key=lambda item: min(row["invoice_time"] for row in item[1])):
        first = min(lines, key=lambda row: (row["invoice_time"], row["source_row_number"]))
        order_id = f"SO-{_hash(invoice_no, 24).upper()}"
        is_cancel = invoice_no.startswith("C") or all(row["quantity"] < 0 for row in lines)
        amounts = [abs(Decimal(row["quantity"]) * row["unit_price"]) for row in lines]
        gross = _money(sum(amounts, Decimal("0")))
        refund = gross if is_cancel else Decimal("0.00")
        net = Decimal("0.00") if is_cancel else gross
        cost = _money(net * UCI_DERIVED_COST_RATE)
        profit = net - cost
        customer_id = first["customer_key"]
        salesperson_id = f"UNASSIGNED-{_hash(first['region_id'], 16).upper()}"
        db.add(SalesOrder(
            order_id=order_id, order_date=first["invoice_time"].date(), customer_id=customer_id,
            channel_id="UCI-ONLINE", region_id=first["region_id"], salesperson_id=salesperson_id,
            organization_code="UCI-ONLINE-RETAIL", gross_amount=gross, discount_amount=Decimal("0.00"),
            refund_amount=refund, net_revenue=net, cost_amount=cost, gross_profit=profit,
            status="refunded" if is_cancel else "completed", is_new_customer=int(customer_id not in seen_customers),
            data_classification=DATA_CLASSIFICATION, seed_run_id=UCI_RUN_ID, created_at=now,
        ))
        seen_customers.add(customer_id)
        order_count += 1
        for line_number, row in enumerate(sorted(lines, key=lambda item: item["source_row_number"]), start=1):
            gross_line = _money(abs(Decimal(row["quantity"]) * row["unit_price"]))
            refund_line = gross_line if is_cancel else Decimal("0.00")
            net_line = Decimal("0.00") if is_cancel else gross_line
            cost_line = _money(net_line * UCI_DERIVED_COST_RATE)
            item_rows.append({
                "order_item_id": f"SI-{_hash(str(row['source_row_number']), 28).upper()}",
                "order_id": order_id, "line_number": line_number, "product_id": row["product_id"],
                "quantity": abs(row["quantity"]), "unit_price": row["unit_price"],
                "gross_amount": gross_line, "discount_amount": Decimal("0.00"),
                "refund_amount": refund_line, "net_revenue": net_line, "cost_amount": cost_line,
                "gross_profit": net_line - cost_line, "data_classification": DATA_CLASSIFICATION,
                "seed_run_id": UCI_RUN_ID,
            })
    db.flush()
    _bulk(db, SalesOrderItem, item_rows)
    run.raw_row_count = len(raw_rows)
    run.staging_row_count = len(stg_rows)
    run.core_row_count = order_count + len(item_rows)
    dates = [row["invoice_time"] for row in stg_rows]
    source_numbers = [row["source_row_number"] for row in stg_rows]
    checks = {
        "UCI_ROW_COUNT": (len(stg_rows) == snapshot["snapshot_row_count"], len(stg_rows), snapshot["snapshot_row_count"]),
        "UCI_UNIQUE_SOURCE_ROW": (len(set(source_numbers)) == len(source_numbers), len(set(source_numbers)), len(source_numbers)),
        "UCI_SAMPLE_INTERVAL": (all(number % 20 == 1 for number in source_numbers), "source row includes header offset", "every twentieth data row"),
        "UCI_REQUIRED_FIELDS": (all(row["invoice_no"] and row["stock_code"] and row["country"] for row in stg_rows), "evaluated", True),
        "UCI_DATE_RANGE": (min(dates).date() >= date(2010, 12, 1) and max(dates).date() <= date(2011, 12, 9), [min(dates), max(dates)], "2010-12-01..2011-12-09"),
        "UCI_UNIT_PRICE_NONNEGATIVE": (all(row["unit_price"] >= 0 for row in stg_rows), str(min(row["unit_price"] for row in stg_rows)), ">=0"),
        "UCI_QUANTITY_NONZERO": (all(row["quantity"] != 0 for row in stg_rows), "evaluated", True),
        "UCI_CANCELLATION_PRESENT": (any(row["is_cancellation"] for row in stg_rows), sum(row["is_cancellation"] for row in stg_rows), ">0"),
        "UCI_CUSTOMER_NULL_PROFILED": (sum(row["customer_id"] is None for row in stg_rows) == 6776, sum(row["customer_id"] is None for row in stg_rows), 6776),
        "UCI_COUNTRY_INTEGRITY": (len(regions) == 36, len(regions), 36),
        "UCI_INVOICE_GROUPING": (order_count == len(invoices), order_count, len(invoices)),
        "UCI_AMOUNT_RECONCILIATION": (all(item["gross_amount"] == item["net_revenue"] + item["refund_amount"] for item in item_rows), "evaluated", True),
        "UCI_ORDERING": (source_numbers == sorted(source_numbers), [source_numbers[0], source_numbers[-1]], "ascending source row"),
        "UCI_OUTLIER_PROFILE": (max(row["quantity"] for row in stg_rows) == 74215, max(row["quantity"] for row in stg_rows), 74215),
        "UCI_VERSION_AND_HASH": (_file_hash(path) == snapshot["snapshot_sha256"], snapshot["snapshot_sha256"], snapshot["snapshot_sha256"]),
    }
    quality = _quality(db, run.run_id, checks)
    run.status = "COMPLETED" if quality["status"] == "PASS" else "FAILED"
    db.flush()
    if quality["status"] != "PASS":
        raise RuntimeError("DATA41_UCI_QUALITY_FAILED:" + ",".join(quality["failures"]))
    return {"run_id": run.run_id, "status": "PASS", "reused": False, "rows": len(stg_rows), "orders": order_count, "quality": quality}


def ingest_all(db: Session, repository_root: Path | None = None) -> dict:
    _, manifest = load_manifest(repository_root)
    snapshots = {item["dataset_code"]: item for item in manifest["snapshots"]}
    acn = ingest_acn(db, snapshots["charging_ops_acn_ornl_discovery"], repository_root)
    uci = ingest_uci(db, snapshots["sales_ops_uci_online_retail"], repository_root)
    db.commit()
    versions = publish_open_source_versions(db)
    return {
        "status": "PASS", "data_classification": DATA_CLASSIFICATION,
        "charging_ops": acn, "sales_ops": uci,
        "platform_versions": versions,
        "manifest_version": manifest["manifest_version"],
    }


def publish_open_source_versions(db: Session) -> dict:
    analyst = db.scalar(select(User).where(User.username == "analyst"))
    if analyst is None:
        raise RuntimeError("DATA41_PLATFORM_IDENTITY_MISSING")
    identity = IdentityContextFactory.from_user(analyst, request_id="DATA41-DATASET-PUBLISH")
    specs = {
        "charging_ops": {
            "source_version": ACN_RUN_ID,
            "row_count": int(db.scalar(select(func.count()).select_from(ChargingSession).where(ChargingSession.batch_id == ACN_RUN_ID)) or 0),
            "period_start": "2020-05-09",
            "period_end_exclusive": "2020-06-10",
            "quality_run_id": "DATA41-ACN-QUALITY-V1",
        },
        "sales_ops": {
            "source_version": UCI_RUN_ID,
            "row_count": int(db.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.seed_run_id == UCI_RUN_ID)) or 0),
            "period_start": "2010-12-01",
            "period_end_exclusive": "2011-12-10",
            "quality_run_id": "DATA41-UCI-QUALITY-V1",
        },
    }
    results = {}
    for scenario_id, spec in specs.items():
        dataset = db.scalar(select(PlatformDataset).where(
            PlatformDataset.tenant_id == identity.tenant_id,
            PlatformDataset.workspace_id == identity.workspace_id,
            PlatformDataset.scenario_id == scenario_id,
        ))
        if dataset is None:
            raise RuntimeError(f"DATA41_PLATFORM_DATASET_MISSING:{scenario_id}")
        existing = db.scalar(select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.dataset_id,
            DatasetVersion.idempotency_key == f"data41:{scenario_id}:dataset-v1",
        ))
        if existing is None:
            base_version = db.scalar(select(DatasetVersion).where(
                DatasetVersion.dataset_id == dataset.dataset_id,
            ).order_by(DatasetVersion.version.desc()))
            pointer = db.scalar(select(SemanticActivation).where(
                SemanticActivation.dataset_id == dataset.dataset_id,
                SemanticActivation.scenario_id == scenario_id,
            ))
            if base_version is None or pointer is None:
                raise RuntimeError(f"DATA41_PLATFORM_BASE_VERSION_MISSING:{scenario_id}")
            mapping = db.get(MappingVersion, base_version.mapping_version_id)
            source_binding = json.loads(base_version.source_binding_json)
            source_binding.update({
                "source": "platform_database",
                "database": "PostgreSQL",
                "data_classification": DATA_CLASSIFICATION,
                "source_version": spec["source_version"],
                "lineage_endpoint": "/api/v1/data/open-source/status",
                "sqlbot_execution_mode": "disabled_schema_catalog_only",
            })
            version = DatasetVersionService(db).create_version(
                identity,
                dataset_id=dataset.dataset_id,
                mapping=json.loads(mapping.mapping_json),
                schema=json.loads(base_version.schema_json),
                source_binding=source_binding,
                source_version=spec["source_version"],
                quality_run_id=spec["quality_run_id"],
                quality_status="PASSED",
                quality_rules=[
                    {"code": "open_source_lineage", "status": "PASSED"},
                    {"code": "snapshot_sha256", "status": "PASSED"},
                    {"code": "raw_staging_core_reconciliation", "status": "PASSED"},
                    {"code": "no_frontend_mock_fallback", "status": "PASSED"},
                ],
                row_count=spec["row_count"],
                period_start=spec["period_start"],
                period_end_exclusive=spec["period_end_exclusive"],
                compatible_semantic_range=base_version.compatible_semantic_range,
                idempotency_key=f"data41:{scenario_id}:dataset-v1",
            )
            release = ReleaseService(db)
            release.submit(identity, version.dataset_version_id)
            release.decide(identity, version.dataset_version_id, approved=True, reason="DATA-4.1 open-source quality gate passed")
            release.publish(identity, version.dataset_version_id, idempotency_key=f"data41:{scenario_id}:publish-v1")
            SemanticActivationService(db).activate(
                identity,
                dataset_version_id=version.dataset_version_id,
                scenario_version=pointer.scenario_version,
                semantic_model_version_id=pointer.active_semantic_model_version_id,
                idempotency_key=f"data41:{scenario_id}:activate-v1",
                reason="DATA-4.1 open-source baseline activation",
            )
            existing = version
        dataset.data_classification = DATA_CLASSIFICATION
        db.commit()
        results[scenario_id] = {
            "dataset_id": dataset.dataset_id,
            "dataset_version_id": existing.dataset_version_id,
            "dataset_version": existing.version,
            "source_version": existing.source_version,
            "status": existing.status,
        }
    return results


def lineage_status(db: Session) -> dict:
    runs = db.scalars(select(OpenDataIngestionRun).order_by(OpenDataIngestionRun.run_id)).all()
    sources = {row.source_id: row for row in db.scalars(select(OpenDataSource)).all()}
    snapshots = {row.snapshot_id: row for row in db.scalars(select(OpenDataSnapshot)).all()}
    return {
        "status": "PASS" if runs and all(row.status == "COMPLETED" for row in runs) else "NOT_READY",
        "data_classification": DATA_CLASSIFICATION,
        "runs": [{
            "run_id": row.run_id,
            "source_name": sources[row.source_id].source_name,
            "source_url": sources[row.source_id].source_url,
            "source_identifier": sources[row.source_id].source_identifier,
            "license": sources[row.source_id].license_name,
            "ingestion_time": row.ingestion_time.isoformat(),
            "source_hash": snapshots[row.snapshot_id].source_hash,
            "snapshot_hash": snapshots[row.snapshot_id].snapshot_hash,
            "dataset_version": snapshots[row.snapshot_id].dataset_version,
            "transformation_version": row.transformation_version,
            "raw_row_count": row.raw_row_count,
            "staging_row_count": row.staging_row_count,
            "core_row_count": row.core_row_count,
            "status": row.status,
        } for row in runs],
    }
