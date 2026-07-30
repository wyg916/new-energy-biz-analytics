"""Add isolated simulated sales_ops dimensions and facts."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _classification() -> sa.Column:
    return sa.Column(
        "data_classification",
        sa.String(length=32),
        nullable=False,
        server_default="simulated",
    )


def upgrade() -> None:
    op.create_table(
        "sales_business_date",
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("business_date"),
    )
    op.create_index("ix_sales_business_date_year", "sales_business_date", ["year"])
    op.create_index("ix_sales_business_date_month", "sales_business_date", ["month"])

    op.create_table(
        "sales_region",
        sa.Column("region_id", sa.String(length=32), nullable=False),
        sa.Column("region_name", sa.String(length=96), nullable=False),
        sa.Column("organization_code", sa.String(length=32), nullable=False),
        _classification(),
        sa.PrimaryKeyConstraint("region_id"),
    )
    op.create_index("ix_sales_region_organization_code", "sales_region", ["organization_code"])

    op.create_table(
        "sales_channel",
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("channel_name", sa.String(length=96), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        _classification(),
        sa.PrimaryKeyConstraint("channel_id"),
    )
    op.create_index("ix_sales_channel_channel_type", "sales_channel", ["channel_type"])

    op.create_table(
        "sales_product_category",
        sa.Column("category_id", sa.String(length=32), nullable=False),
        sa.Column("category_name", sa.String(length=96), nullable=False),
        _classification(),
        sa.PrimaryKeyConstraint("category_id"),
    )

    op.create_table(
        "salesperson",
        sa.Column("salesperson_id", sa.String(length=32), nullable=False),
        sa.Column("salesperson_name", sa.String(length=96), nullable=False),
        sa.Column("region_id", sa.String(length=32), nullable=False),
        sa.Column("organization_code", sa.String(length=32), nullable=False),
        _classification(),
        sa.ForeignKeyConstraint(["region_id"], ["sales_region.region_id"]),
        sa.PrimaryKeyConstraint("salesperson_id"),
    )
    op.create_index("ix_salesperson_region_id", "salesperson", ["region_id"])
    op.create_index("ix_salesperson_organization_code", "salesperson", ["organization_code"])

    op.create_table(
        "sales_customer",
        sa.Column("customer_id", sa.String(length=32), nullable=False),
        sa.Column("customer_name", sa.String(length=96), nullable=False),
        sa.Column("customer_segment", sa.String(length=32), nullable=False),
        sa.Column("home_region_id", sa.String(length=32), nullable=False),
        sa.Column("registered_date", sa.Date(), nullable=False),
        _classification(),
        sa.ForeignKeyConstraint(["home_region_id"], ["sales_region.region_id"]),
        sa.PrimaryKeyConstraint("customer_id"),
    )
    op.create_index("ix_sales_customer_customer_segment", "sales_customer", ["customer_segment"])
    op.create_index("ix_sales_customer_home_region_id", "sales_customer", ["home_region_id"])
    op.create_index("ix_sales_customer_registered_date", "sales_customer", ["registered_date"])

    op.create_table(
        "sales_product",
        sa.Column("product_id", sa.String(length=32), nullable=False),
        sa.Column("product_name", sa.String(length=128), nullable=False),
        sa.Column("category_id", sa.String(length=32), nullable=False),
        sa.Column("list_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("standard_cost", sa.Numeric(precision=18, scale=2), nullable=False),
        _classification(),
        sa.ForeignKeyConstraint(["category_id"], ["sales_product_category.category_id"]),
        sa.PrimaryKeyConstraint("product_id"),
    )
    op.create_index("ix_sales_product_category_id", "sales_product", ["category_id"])

    op.create_table(
        "sales_order",
        sa.Column("order_id", sa.String(length=32), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("customer_id", sa.String(length=32), nullable=False),
        sa.Column("channel_id", sa.String(length=32), nullable=False),
        sa.Column("region_id", sa.String(length=32), nullable=False),
        sa.Column("salesperson_id", sa.String(length=32), nullable=False),
        sa.Column("organization_code", sa.String(length=32), nullable=False),
        sa.Column("gross_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("refund_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("net_revenue", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cost_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("gross_profit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("is_new_customer", sa.Integer(), nullable=False),
        _classification(),
        sa.Column("seed_run_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_date"], ["sales_business_date.business_date"]),
        sa.ForeignKeyConstraint(["customer_id"], ["sales_customer.customer_id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["sales_channel.channel_id"]),
        sa.ForeignKeyConstraint(["region_id"], ["sales_region.region_id"]),
        sa.ForeignKeyConstraint(["salesperson_id"], ["salesperson.salesperson_id"]),
        sa.PrimaryKeyConstraint("order_id"),
    )
    for name, columns in (
        ("ix_sales_order_order_date", ["order_date"]),
        ("ix_sales_order_customer_id", ["customer_id"]),
        ("ix_sales_order_channel_id", ["channel_id"]),
        ("ix_sales_order_region_id", ["region_id"]),
        ("ix_sales_order_salesperson_id", ["salesperson_id"]),
        ("ix_sales_order_organization_code", ["organization_code"]),
        ("ix_sales_order_status", ["status"]),
        ("ix_sales_order_is_new_customer", ["is_new_customer"]),
        ("ix_sales_order_seed_run_id", ["seed_run_id"]),
        ("ix_sales_order_date_region", ["order_date", "region_id"]),
        ("ix_sales_order_date_channel", ["order_date", "channel_id"]),
    ):
        op.create_index(name, "sales_order", columns)

    op.create_table(
        "sales_order_item",
        sa.Column("order_item_id", sa.String(length=40), nullable=False),
        sa.Column("order_id", sa.String(length=32), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("gross_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("refund_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("net_revenue", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cost_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("gross_profit", sa.Numeric(precision=18, scale=2), nullable=False),
        _classification(),
        sa.Column("seed_run_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["sales_order.order_id"]),
        sa.ForeignKeyConstraint(["product_id"], ["sales_product.product_id"]),
        sa.PrimaryKeyConstraint("order_item_id"),
        sa.UniqueConstraint("order_id", "line_number", name="uq_sales_order_line"),
    )
    for name, columns in (
        ("ix_sales_order_item_order_id", ["order_id"]),
        ("ix_sales_order_item_product_id", ["product_id"]),
        ("ix_sales_order_item_seed_run_id", ["seed_run_id"]),
        ("ix_sales_order_item_product_order", ["product_id", "order_id"]),
    ):
        op.create_index(name, "sales_order_item", columns)


def downgrade() -> None:
    for table in (
        "sales_order_item",
        "sales_order",
        "sales_product",
        "sales_customer",
        "salesperson",
        "sales_product_category",
        "sales_channel",
        "sales_region",
        "sales_business_date",
    ):
        op.drop_table(table)
