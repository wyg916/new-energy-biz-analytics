import argparse
import json
import random
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.business import (
    ChargingSession, City, DataGenerationRun, DateDimension, Device,
    DeviceStatusEvent, EnergyCost, MetricDefinition, OperationExpense,
    Region, SimulatedUser, Station,
)
from app.services.metric_catalog import ALLOWED_DIMENSIONS, METRICS

SEED = 20260722
VERSION = "0.1.0"
START = date(2025, 1, 1)
END = date(2026, 6, 30)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _days() -> list[date]:
    return [START + timedelta(days=i) for i in range((END - START).days + 1)]


def _money(value: Decimal | float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _bulk(db: Session, model, rows: list[dict], chunk: int = 5000) -> None:
    for index in range(0, len(rows), chunk):
        db.bulk_insert_mappings(model, rows[index:index + chunk])
        db.flush()


def generate_simulated_data(db: Session, session_count: int = 300_000, seed: int = SEED) -> dict:
    if session_count < 1 or session_count > 350_000:
        raise ValueError("session_count must be between 1 and 350000")
    batch_id = f"SIM-{seed}-v010-n{session_count}"
    existing = db.get(DataGenerationRun, batch_id)
    if existing and existing.status == "completed":
        from app.scenarios.registry import install_charging_ops
        install_charging_ops(db, batch_id, publish=existing.quality_status == "passed")
        db.commit()
        return json.loads(existing.actual_counts_json)
    if db.scalar(select(func.count()).select_from(Region)):
        raise RuntimeError("database is not empty; refusing to mix simulated batches")

    started = datetime.now(UTC)
    run = DataGenerationRun(
        batch_id=batch_id, generator_version=VERSION, random_seed=seed,
        period_start=START, period_end=END,
        target_counts_json=json.dumps({"regions": 3, "cities": 6, "stations": 30, "devices": 120, "users": 10_000, "sessions": session_count}),
        actual_counts_json="{}", scenario_flags_json=json.dumps(["normal", "seasonality", "weekend", "fault_variation"]),
        status="running", quality_status="pending", started_at=started,
    )
    db.add(run)
    db.flush()
    rng = random.Random(seed)
    days = _days()

    regions = [{"region_id": f"R{i:02d}", "region_name": f"模拟区域{chr(64+i)}", "display_order": i, "status": "active", "source_type": "simulated"} for i in range(1, 4)]
    cities = []
    for i in range(1, 7):
        regions_id = f"R{((i - 1) // 2) + 1:02d}"
        cities.append({"city_id": f"C{i:02d}", "city_name": f"模拟城市{i}", "region_id": regions_id, "status": "active", "source_type": "simulated"})
    station_types = ["urban", "highway", "community", "destination"]
    stations = []
    devices = []
    for i in range(1, 31):
        city_index = ((i - 1) % 6) + 1
        region_index = ((city_index - 1) // 2) + 1
        station_id = f"S{i:03d}"
        stations.append({
            "station_id": station_id, "station_name": f"模拟充电站{i:02d}", "city_id": f"C{city_index:02d}",
            "region_id": f"R{region_index:02d}", "operator_code": f"OP{((i - 1) % 3) + 1:02d}",
            "station_type": station_types[(i - 1) % 4], "open_date": START - timedelta(days=180 + i),
            "connector_count": 8, "rated_power_kw": Decimal("480.00"), "status": "active", "source_type": "simulated",
        })
        for j in range(1, 5):
            devices.append({
                "device_id": f"D{i:03d}-{j:02d}", "station_id": station_id, "device_model": f"SIM-DC-{60 + (j % 2) * 60}",
                "connector_count": 2, "rated_power_kw": Decimal("120.00" if j % 2 == 0 else "60.00"),
                "commission_date": START - timedelta(days=120 + i), "status": "active", "source_type": "simulated",
            })
    users = []
    segments = ["new", "regular", "regular", "high_value", "dormant"]
    channels = ["app", "partner", "offline_campaign", "fleet"]
    for i in range(1, 10_001):
        users.append({
            "user_id": f"U{i:05d}", "register_date": START - timedelta(days=rng.randint(1, 730)),
            "acquisition_channel": channels[i % len(channels)], "user_segment": segments[i % len(segments)],
            "home_region_id": f"R{(i % 3) + 1:02d}", "status": "active", "source_type": "simulated",
        })
    date_rows = []
    for day in days:
        iso = day.isocalendar()
        holiday = (day.month, day.day) in {(1, 1), (5, 1), (10, 1)}
        date_rows.append({"date_key": day, "year": day.year, "quarter": (day.month - 1) // 3 + 1, "month": day.month, "iso_week": iso.week, "day_of_week": iso.weekday, "is_weekend": iso.weekday >= 6, "is_holiday": holiday, "holiday_name": "模拟节假日" if holiday else None})

    _bulk(db, Region, regions); _bulk(db, City, cities); _bulk(db, Station, stations); _bulk(db, Device, devices); _bulk(db, SimulatedUser, users); _bulk(db, DateDimension, date_rows)

    status_rows = []
    online_slots: list[tuple[dict, date, int]] = []
    for device_index, device in enumerate(devices):
        for day_index, day in enumerate(days):
            roll = random.Random(seed + device_index * 10_000 + day_index).random()
            status = "online" if roll < 0.955 else "fault" if roll < 0.98 else "offline"
            start_dt = datetime.combine(day, time.min, SHANGHAI)
            status_rows.append({
                "status_event_id": f"E-{device['device_id']}-{day:%Y%m%d}", "device_id": device["device_id"],
                "station_id": device["station_id"], "status": status, "start_time": start_dt,
                "end_time": start_dt + timedelta(days=1), "reason_code": None if status == "online" else ("SIM_FAULT" if status == "fault" else "SIM_OFFLINE"),
                "is_planned": False, "batch_id": batch_id, "source_type": "simulated",
            })
            if status == "online":
                for slot in range(5):
                    online_slots.append((device, day, slot))
    if len(online_slots) < session_count:
        raise RuntimeError("not enough non-overlapping online slots for requested sessions")
    rng.shuffle(online_slots)
    _bulk(db, DeviceStatusEvent, status_rows)

    session_rows = []
    station_day_energy: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    station_day_revenue: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    month_factor = {1: 0.82, 2: 0.86, 3: 0.93, 4: 0.98, 5: 1.03, 6: 1.12, 7: 1.18, 8: 1.16, 9: 1.04, 10: 1.00, 11: 0.92, 12: 0.86}
    for index, (device, day, slot) in enumerate(online_slots[:session_count]):
        local_rng = random.Random(seed * 7 + index)
        start_dt = datetime.combine(day, time(hour=1 + slot * 4, minute=local_rng.randint(0, 20)), SHANGHAI)
        duration_minutes = local_rng.randint(28, 86)
        status_roll = local_rng.random()
        status = "completed" if status_roll < 0.96 else "failed" if status_roll < 0.98 else "cancelled"
        duration_seconds = duration_minutes * 60 if status == "completed" else local_rng.randint(30, 300)
        end_dt = start_dt + timedelta(seconds=duration_seconds)
        if status == "completed":
            base_energy = Decimal(str(local_rng.uniform(12, 48) * month_factor[day.month] * (1.08 if day.weekday() >= 5 else 1)))
            max_energy = Decimal(str(device["rated_power_kw"])) * Decimal(duration_seconds) / Decimal(3600) * Decimal("1.05")
            energy = min(base_energy, max_energy).quantize(Decimal("0.0001"))
            electricity = _money(energy * Decimal(str(local_rng.uniform(0.78, 1.08))))
            service = _money(energy * Decimal(str(local_rng.uniform(0.22, 0.38))))
            settlement = end_dt + timedelta(minutes=local_rng.randint(1, 8))
            station_day_energy[(device["station_id"], day)] += energy
            station_day_revenue[(device["station_id"], day)] += electricity + service
        else:
            energy = electricity = service = Decimal(0)
            settlement = None
        session_rows.append({
            "session_id": f"CS-{seed}-{index:06d}", "station_id": device["station_id"], "device_id": device["device_id"],
            "connector_no": (index % 2) + 1, "user_id": f"U{(local_rng.randrange(10_000) + 1):05d}",
            "start_time": start_dt, "end_time": end_dt, "settlement_time": settlement,
            "charging_duration_seconds": duration_seconds, "energy_kwh": energy,
            "electricity_fee_net_amount": electricity, "service_fee_net_amount": service,
            "session_status": status, "batch_id": batch_id, "source_type": "simulated", "created_at": started,
        })
    _bulk(db, ChargingSession, session_rows)

    tariff_prices = {"valley": Decimal("0.42"), "flat": Decimal("0.61"), "peak": Decimal("0.86"), "super_peak": Decimal("1.03")}
    energy_rows = []
    expense_rows = []
    expense_config = [
        ("payment_fee", Decimal("0.006"), "by_orders"),
        ("maintenance_variable", Decimal("0.018"), "by_energy"),
        ("platform_variable", Decimal("0.010"), "by_energy"),
        ("marketing_variable", Decimal("0.008"), "by_orders"),
    ]
    for station in stations:
        station_id = station["station_id"]
        for day in days:
            energy = station_day_energy[(station_id, day)] * Decimal("1.02")
            for tariff, price in tariff_prices.items():
                period_energy = (energy / Decimal(4)).quantize(Decimal("0.0001"))
                energy_rows.append({"station_id": station_id, "cost_date": day, "tariff_period": tariff, "purchase_price_per_kwh": price, "settled_energy_kwh": period_energy, "energy_cost": _money(price * period_energy), "batch_id": batch_id, "source_type": "simulated"})
            revenue = station_day_revenue[(station_id, day)]
            for expense_type, rate, allocation in expense_config:
                expense_rows.append({"station_id": station_id, "expense_date": day, "expense_type": expense_type, "amount": _money(revenue * rate), "is_variable": True, "allocation_rule": allocation, "batch_id": batch_id, "source_type": "simulated"})
    _bulk(db, EnergyCost, energy_rows); _bulk(db, OperationExpense, expense_rows)

    metric_rows = [{"metric_id": key, "display_name": value[0], "unit": value[1], "version": VERSION, "status": "approved_for_implementation", "formula": value[2], "allowed_dimensions_json": json.dumps(ALLOWED_DIMENSIONS)} for key, value in METRICS.items()]
    _bulk(db, MetricDefinition, metric_rows)
    counts = {"regions": len(regions), "cities": len(cities), "stations": len(stations), "devices": len(devices), "users": len(users), "dates": len(days), "sessions": len(session_rows), "device_status_events": len(status_rows), "energy_cost_rows": len(energy_rows), "operation_expense_rows": len(expense_rows), "metrics": len(metric_rows)}
    run.actual_counts_json = json.dumps(counts)
    run.status = "completed"
    run.quality_status = "passed"
    run.finished_at = datetime.now(UTC)
    db.flush()
    from app.data.quality import validate_published_batch
    validate_published_batch(db)
    from app.scenarios.registry import install_charging_ops
    install_charging_ops(db, batch_id, publish=True)
    db.commit()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic simulated Alpha data")
    parser.add_argument("--session-count", type=int, default=300_000)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    with SessionLocal() as db:
        print(json.dumps(generate_simulated_data(db, args.session_count, args.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
