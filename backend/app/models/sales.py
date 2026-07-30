from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class SalesBusinessDate(Base):
    __tablename__ = "sales_business_date"

    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer, index=True)
    week: Mapped[int] = mapped_column(Integer)


class SalesRegion(Base):
    __tablename__ = "sales_region"

    region_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    region_name: Mapped[str] = mapped_column(String(96))
    organization_code: Mapped[str] = mapped_column(String(32), index=True)
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")


class SalesChannel(Base):
    __tablename__ = "sales_channel"

    channel_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    channel_name: Mapped[str] = mapped_column(String(96))
    channel_type: Mapped[str] = mapped_column(String(32), index=True)
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")


class SalesPerson(Base):
    __tablename__ = "salesperson"

    salesperson_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    salesperson_name: Mapped[str] = mapped_column(String(96))
    region_id: Mapped[str] = mapped_column(ForeignKey("sales_region.region_id"), index=True)
    organization_code: Mapped[str] = mapped_column(String(32), index=True)
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")


class SalesCustomer(Base):
    __tablename__ = "sales_customer"

    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(96))
    customer_segment: Mapped[str] = mapped_column(String(32), index=True)
    home_region_id: Mapped[str] = mapped_column(ForeignKey("sales_region.region_id"), index=True)
    registered_date: Mapped[date] = mapped_column(Date, index=True)
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")


class SalesProductCategory(Base):
    __tablename__ = "sales_product_category"

    category_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category_name: Mapped[str] = mapped_column(String(96))
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")


class SalesProduct(Base):
    __tablename__ = "sales_product"

    product_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_name: Mapped[str] = mapped_column(String(128))
    category_id: Mapped[str] = mapped_column(
        ForeignKey("sales_product_category.category_id"),
        index=True,
    )
    list_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    standard_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")


class SalesOrder(Base):
    __tablename__ = "sales_order"
    __table_args__ = (
        Index("ix_sales_order_date_region", "order_date", "region_id"),
        Index("ix_sales_order_date_channel", "order_date", "channel_id"),
    )

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_date: Mapped[date] = mapped_column(ForeignKey("sales_business_date.business_date"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("sales_customer.customer_id"), index=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("sales_channel.channel_id"), index=True)
    region_id: Mapped[str] = mapped_column(ForeignKey("sales_region.region_id"), index=True)
    salesperson_id: Mapped[str] = mapped_column(ForeignKey("salesperson.salesperson_id"), index=True)
    organization_code: Mapped[str] = mapped_column(String(32), index=True)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_revenue: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    gross_profit: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(24), index=True)
    is_new_customer: Mapped[int] = mapped_column(Integer, default=0, index=True)
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")
    seed_run_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SalesOrderItem(Base):
    __tablename__ = "sales_order_item"
    __table_args__ = (
        UniqueConstraint("order_id", "line_number", name="uq_sales_order_line"),
        Index("ix_sales_order_item_product_order", "product_id", "order_id"),
    )

    order_item_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("sales_order.order_id"), index=True)
    line_number: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[str] = mapped_column(ForeignKey("sales_product.product_id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_revenue: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    gross_profit: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    data_classification: Mapped[str] = mapped_column(String(32), default="simulated")
    seed_run_id: Mapped[str] = mapped_column(String(64), index=True)


SALES_TABLES = [
    SalesBusinessDate.__table__,
    SalesRegion.__table__,
    SalesChannel.__table__,
    SalesPerson.__table__,
    SalesCustomer.__table__,
    SalesProductCategory.__table__,
    SalesProduct.__table__,
    SalesOrder.__table__,
    SalesOrderItem.__table__,
]
