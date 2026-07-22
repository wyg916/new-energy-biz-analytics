import json
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.business import (
    ChargingSession, City, DataGenerationRun, DateDimension, Device,
    DeviceStatusEvent, EnergyCost, OperationExpense, Region, SimulatedUser, Station,
)


class DataQualityError(RuntimeError):
    pass


def validate_published_batch(db: Session) -> dict:
    rules: dict[str, bool] = {}
    counts = {
        "regions": db.scalar(select(func.count()).select_from(Region)),
        "cities": db.scalar(select(func.count()).select_from(City)),
        "stations": db.scalar(select(func.count()).select_from(Station)),
        "devices": db.scalar(select(func.count()).select_from(Device)),
        "users": db.scalar(select(func.count()).select_from(SimulatedUser)),
        "dates": db.scalar(select(func.count()).select_from(DateDimension)),
        "sessions": db.scalar(select(func.count()).select_from(ChargingSession)),
    }

    # PK constraints are authoritative; distinct counts provide an executed reconciliation.
    distinct_sessions = db.scalar(select(func.count(func.distinct(ChargingSession.session_id))))
    rules["DQ-001"] = counts["sessions"] == distinct_sessions
    invalid_completed = db.scalar(select(func.count()).select_from(ChargingSession).where(ChargingSession.session_status == "completed", (ChargingSession.energy_kwh <= 0) | ChargingSession.settlement_time.is_(None)))
    rules["DQ-002"] = invalid_completed == 0

    missing_session_fk = db.scalar(select(func.count()).select_from(ChargingSession).outerjoin(Station, ChargingSession.station_id == Station.station_id).outerjoin(Device, ChargingSession.device_id == Device.device_id).outerjoin(SimulatedUser, ChargingSession.user_id == SimulatedUser.user_id).where((Station.station_id.is_(None)) | (Device.device_id.is_(None)) | (SimulatedUser.user_id.is_(None))))
    rules["DQ-003"] = missing_session_fk == 0
    hierarchy_mismatch = db.scalar(select(func.count()).select_from(Station).join(City, Station.city_id == City.city_id).where(Station.region_id != City.region_id))
    device_mismatch = db.scalar(select(func.count()).select_from(Device).join(Station, Device.station_id == Station.station_id).where(Device.station_id != Station.station_id))
    rules["DQ-004"] = hierarchy_mismatch == 0 and device_mismatch == 0

    invalid_time = db.scalar(select(func.count()).select_from(ChargingSession).where((ChargingSession.end_time < ChargingSession.start_time) | (func.date(ChargingSession.start_time) < "2025-01-01") | (func.date(ChargingSession.start_time) > "2026-06-30")))
    rules["DQ-005"] = invalid_time == 0
    invalid_range = db.scalar(select(func.count()).select_from(ChargingSession).where((ChargingSession.energy_kwh < 0) | (ChargingSession.electricity_fee_net_amount < 0) | (ChargingSession.service_fee_net_amount < 0) | (ChargingSession.charging_duration_seconds < 0)))
    invalid_cost_range = db.scalar(select(func.count()).select_from(EnergyCost).where((EnergyCost.purchase_price_per_kwh < 0) | (EnergyCost.settled_energy_kwh < 0) | (EnergyCost.energy_cost < 0)))
    rules["DQ-006"] = invalid_range == 0 and invalid_cost_range == 0
    over_power = db.scalar(select(func.count()).select_from(ChargingSession).join(Device).where(ChargingSession.session_status == "completed", ChargingSession.energy_kwh > Device.rated_power_kw * ChargingSession.charging_duration_seconds / 3600 * Decimal("1.05")))
    rules["DQ-007"] = over_power == 0

    previous: dict[tuple[str, int], object] = {}
    overlap = False
    for device_id, connector_no, start_time, end_time in db.execute(select(ChargingSession.device_id, ChargingSession.connector_no, ChargingSession.start_time, ChargingSession.end_time).where(ChargingSession.session_status == "completed").order_by(ChargingSession.device_id, ChargingSession.connector_no, ChargingSession.start_time)):
        key = (device_id, connector_no)
        if key in previous and start_time < previous[key]:
            overlap = True; break
        previous[key] = end_time
    rules["DQ-008"] = not overlap

    previous_status: dict[str, object] = {}
    status_overlap = False
    for device_id, start_time, end_time in db.execute(select(DeviceStatusEvent.device_id, DeviceStatusEvent.start_time, DeviceStatusEvent.end_time).order_by(DeviceStatusEvent.device_id, DeviceStatusEvent.start_time)):
        if device_id in previous_status and start_time < previous_status[device_id]:
            status_overlap = True; break
        previous_status[device_id] = end_time
    rules["DQ-009"] = not status_overlap
    bad_status_session = db.scalar(select(func.count()).select_from(ChargingSession).join(DeviceStatusEvent, (ChargingSession.device_id == DeviceStatusEvent.device_id) & (ChargingSession.start_time >= DeviceStatusEvent.start_time) & (ChargingSession.start_time < DeviceStatusEvent.end_time)).where(ChargingSession.session_status == "completed", DeviceStatusEvent.status != "online"))
    rules["DQ-010"] = bad_status_session == 0
    rules["DQ-011"] = db.scalar(select(func.count()).select_from(ChargingSession).where((ChargingSession.electricity_fee_net_amount.is_(None)) | (ChargingSession.service_fee_net_amount.is_(None)))) == 0

    bad_costs = sum(1 for price, energy, cost in db.execute(select(EnergyCost.purchase_price_per_kwh, EnergyCost.settled_energy_kwh, EnergyCost.energy_cost)) if abs(Decimal(price) * Decimal(energy) - Decimal(cost)) > Decimal("0.011"))
    rules["DQ-012"] = bad_costs == 0
    connector_mismatch = db.execute(select(Station.station_id, Station.connector_count, func.sum(Device.connector_count)).join(Device).group_by(Station.station_id, Station.connector_count).having(Station.connector_count != func.sum(Device.connector_count))).all()
    rules["DQ-013"] = not connector_mismatch

    session_energy = {(station_id, str(day)): Decimal(str(value or 0)) for station_id, day, value in db.execute(select(ChargingSession.station_id, func.date(ChargingSession.settlement_time), func.sum(ChargingSession.energy_kwh)).where(ChargingSession.session_status == "completed").group_by(ChargingSession.station_id, func.date(ChargingSession.settlement_time)))}
    cost_energy = {(station_id, str(day)): Decimal(str(value or 0)) for station_id, day, value in db.execute(select(EnergyCost.station_id, EnergyCost.cost_date, func.sum(EnergyCost.settled_energy_kwh)).group_by(EnergyCost.station_id, EnergyCost.cost_date))}
    bad_energy_reconciliation = 0
    for key, source_energy in session_energy.items():
        ratio = (cost_energy.get(key, Decimal(0)) - source_energy) / source_energy if source_energy else Decimal(0)
        if ratio < 0 or ratio > Decimal("0.031"):
            bad_energy_reconciliation += 1
    rules["DQ-014"] = bad_energy_reconciliation == 0
    rules["DQ-015"] = counts["dates"] == 546 and db.scalar(select(func.min(DateDimension.date_key))) == date(2025, 1, 1) and db.scalar(select(func.max(DateDimension.date_key))) == date(2026, 6, 30)

    run = db.scalar(select(DataGenerationRun).where(DataGenerationRun.status == "completed").order_by(DataGenerationRun.finished_at.desc()))
    targets = json.loads(run.target_counts_json) if run else {}
    rules["DQ-016"] = bool(run) and all(abs(counts[key] - target) <= max(1, target * 0.05) for key, target in targets.items() if key in counts)
    flags = set(json.loads(run.scenario_flags_json)) if run else set()
    rules["DQ-017"] = {"seasonality", "weekend", "fault_variation"}.issubset(flags)

    source_failures = sum(db.scalar(select(func.count()).select_from(model).where(model.source_type != "simulated")) for model in (Region, City, Station, Device, SimulatedUser, ChargingSession, EnergyCost, OperationExpense, DeviceStatusEvent))
    batch_ids = set(db.scalars(select(ChargingSession.batch_id).distinct()).all())
    rules["DQ-018"] = source_failures == 0 and len(batch_ids) == 1 and bool(run) and run.batch_id in batch_ids
    forbidden_tokens = {"name", "phone", "mobile", "id_card", "license_plate", "payment_account", "longitude", "latitude"}
    user_columns = {column.name.lower() for column in SimulatedUser.__table__.columns}
    rules["DQ-019"] = not (forbidden_tokens & user_columns)
    rules["DQ-020"] = bool(run and run.quality_status == "passed")

    failures = [rule_id for rule_id, passed in rules.items() if not passed]
    if failures:
        raise DataQualityError("failed rules: " + ", ".join(failures))
    return {"status": "passed", "rules_checked": len(rules), "rule_results": rules, "counts": counts, "failures": []}
