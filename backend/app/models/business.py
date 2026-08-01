from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Region(Base):
    __tablename__ = "dim_region"
    region_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    region_name: Mapped[str] = mapped_column(String(64), unique=True)
    display_order: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(16), default="active")
    source_type: Mapped[str] = mapped_column(String(16), default="simulated")


class City(Base):
    __tablename__ = "dim_city"
    city_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    city_name: Mapped[str] = mapped_column(String(64), unique=True)
    region_id: Mapped[str] = mapped_column(ForeignKey("dim_region.region_id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    source_type: Mapped[str] = mapped_column(String(16), default="simulated")


class Station(Base):
    __tablename__ = "dim_station"
    station_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    station_name: Mapped[str] = mapped_column(String(128), unique=True)
    city_id: Mapped[str] = mapped_column(ForeignKey("dim_city.city_id"), index=True)
    region_id: Mapped[str] = mapped_column(ForeignKey("dim_region.region_id"), index=True)
    operator_code: Mapped[str] = mapped_column(String(32), index=True)
    station_type: Mapped[str] = mapped_column(String(32), index=True)
    open_date: Mapped[date] = mapped_column(Date)
    connector_count: Mapped[int] = mapped_column(Integer)
    rated_power_kw: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(16), default="active")
    source_type: Mapped[str] = mapped_column(String(16), default="simulated")


class Device(Base):
    __tablename__ = "dim_device"
    device_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("dim_station.station_id"), index=True)
    device_model: Mapped[str] = mapped_column(String(64))
    connector_count: Mapped[int] = mapped_column(SmallInteger)
    rated_power_kw: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    commission_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")
    source_type: Mapped[str] = mapped_column(String(16), default="simulated")


class SimulatedUser(Base):
    __tablename__ = "dim_user"
    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    register_date: Mapped[date] = mapped_column(Date, index=True)
    acquisition_channel: Mapped[str] = mapped_column(String(32))
    user_segment: Mapped[str] = mapped_column(String(32), index=True)
    home_region_id: Mapped[str | None] = mapped_column(ForeignKey("dim_region.region_id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    source_type: Mapped[str] = mapped_column(String(16), default="simulated")


class DateDimension(Base):
    __tablename__ = "dim_date"
    date_key: Mapped[date] = mapped_column(Date, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger)
    quarter: Mapped[int] = mapped_column(SmallInteger)
    month: Mapped[int] = mapped_column(SmallInteger)
    iso_week: Mapped[int] = mapped_column(SmallInteger)
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    is_weekend: Mapped[bool] = mapped_column(Boolean)
    is_holiday: Mapped[bool] = mapped_column(Boolean)
    holiday_name: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ChargingSession(Base):
    __tablename__ = "fact_charging_session"
    session_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("dim_station.station_id"), index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("dim_device.device_id"), index=True)
    connector_no: Mapped[int] = mapped_column(SmallInteger)
    user_id: Mapped[str] = mapped_column(ForeignKey("dim_user.user_id"), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settlement_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    charging_duration_seconds: Mapped[int] = mapped_column(Integer)
    energy_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    electricity_fee_net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    service_fee_net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    session_status: Mapped[str] = mapped_column(String(16), index=True)
    batch_id: Mapped[str] = mapped_column(String(48), index=True)
    source_type: Mapped[str] = mapped_column(String(16), default="simulated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EnergyCost(Base):
    __tablename__ = "fact_energy_cost"
    station_id: Mapped[str] = mapped_column(ForeignKey("dim_station.station_id"), primary_key=True)
    cost_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    tariff_period: Mapped[str] = mapped_column(String(16), primary_key=True)
    purchase_price_per_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    settled_energy_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    energy_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    batch_id: Mapped[str] = mapped_column(String(48), index=True)
    source_type: Mapped[str] = mapped_column(String(16), default="simulated")


class OperationExpense(Base):
    __tablename__ = "fact_operation_expense"
    station_id: Mapped[str] = mapped_column(ForeignKey("dim_station.station_id"), primary_key=True)
    expense_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    expense_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    is_variable: Mapped[bool] = mapped_column(Boolean, default=True)
    allocation_rule: Mapped[str] = mapped_column(String(32))
    batch_id: Mapped[str] = mapped_column(String(48), index=True)
    source_type: Mapped[str] = mapped_column(String(16), default="simulated")


class DeviceStatusEvent(Base):
    __tablename__ = "fact_device_status_event"
    status_event_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("dim_device.device_id"), index=True)
    station_id: Mapped[str] = mapped_column(ForeignKey("dim_station.station_id"), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_planned: Mapped[bool] = mapped_column(Boolean, default=False)
    batch_id: Mapped[str] = mapped_column(String(48), index=True)
    source_type: Mapped[str] = mapped_column(String(16), default="simulated")


class DataGenerationRun(Base):
    __tablename__ = "data_generation_run"
    batch_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    generator_version: Mapped[str] = mapped_column(String(32))
    random_seed: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    target_counts_json: Mapped[str] = mapped_column(Text)
    actual_counts_json: Mapped[str] = mapped_column(Text)
    scenario_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), index=True)
    quality_status: Mapped[str] = mapped_column(String(16), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class MetricDefinition(Base):
    __tablename__ = "metric_definition"
    metric_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    formula: Mapped[str] = mapped_column(Text)
    allowed_dimensions_json: Mapped[str] = mapped_column(Text)
    business_domain: Mapped[str] = mapped_column(
        String(64), default="经营分析", server_default="经营分析"
    )
    definition: Mapped[str] = mapped_column(Text, default="", server_default="")
    source_tables_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]"
    )
    supported_grains_json: Mapped[str] = mapped_column(
        Text,
        default='["day", "week", "month"]',
        server_default='["day", "week", "month"]',
    )
    metric_type: Mapped[str] = mapped_column(
        String(32), default="aggregation", server_default="aggregation"
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_run"
    run_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(48), index=True)
    conversation_id: Mapped[str] = mapped_column(String(48), index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    role_id: Mapped[str] = mapped_column(String(32))
    allowed_region_ids: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    query_plan_json: Mapped[str] = mapped_column(Text)
    query_plan_version: Mapped[str] = mapped_column(String(16))
    sql_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params_redacted_json: Mapped[str] = mapped_column(Text, default="{}")
    metric_versions_json: Mapped[str] = mapped_column(Text, default="{}")
    batch_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    answer_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionState(Base):
    __tablename__ = "session_state"
    conversation_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    role_ids_json: Mapped[str] = mapped_column(Text)
    active_intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_metrics_json: Mapped[str] = mapped_column(Text, default="[]")
    active_dimensions_json: Mapped[str] = mapped_column(Text, default="[]")
    active_filters_json: Mapped[str] = mapped_column(Text, default="[]")
    active_time_range_json: Mapped[str] = mapped_column(Text, default="null")
    active_comparison_json: Mapped[str] = mapped_column(Text, default="null")
    active_entities_json: Mapped[str] = mapped_column(Text, default="{}")
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_run_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
