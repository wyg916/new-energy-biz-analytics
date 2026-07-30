import hashlib
import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.models.sales import (
    SalesBusinessDate,
    SalesChannel,
    SalesCustomer,
    SalesOrder,
    SalesOrderItem,
    SalesPerson,
    SalesProduct,
    SalesProductCategory,
    SalesRegion,
)

DEFAULT_SEED = 20260730
DEFAULT_ORDER_COUNT = 50_000
SEED_RUN_ID = "SALES-SIM-v1-20260730"
PERIOD_START = date(2025, 1, 1)
PERIOD_END_EXCLUSIVE = date(2026, 7, 1)
SIMULATED = "simulated"


def _money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SalesSeedSummary:
    seed: int
    seed_run_id: str
    order_count: int
    order_item_count: int
    customer_count: int
    product_count: int
    period_start: str
    period_end_exclusive: str
    data_classification: str
    checksum: str

    def as_dict(self) -> dict:
        return asdict(self)


def _date_rows() -> list[dict]:
    rows = []
    current = PERIOD_START
    while current < PERIOD_END_EXCLUSIVE:
        rows.append({
            "business_date": current,
            "year": current.year,
            "quarter": (current.month - 1) // 3 + 1,
            "month": current.month,
            "week": current.isocalendar().week,
        })
        current += timedelta(days=1)
    return rows


def _dimension_rows(rng: random.Random) -> dict[str, list[dict]]:
    regions = [
        {
            "region_id": f"R{index:02d}",
            "region_name": f"模拟销售区域{index:02d}",
            "organization_code": f"ORG-{(index - 1) // 2 + 1:02d}",
            "data_classification": SIMULATED,
        }
        for index in range(1, 9)
    ]
    channels = [
        ("CH01", "直营网店", "online"),
        ("CH02", "第三方电商", "online"),
        ("CH03", "直营网点", "offline"),
        ("CH04", "渠道伙伴", "partner"),
        ("CH05", "企业直销", "direct"),
    ]
    channel_rows = [
        {
            "channel_id": code,
            "channel_name": name,
            "channel_type": kind,
            "data_classification": SIMULATED,
        }
        for code, name, kind in channels
    ]
    categories = [
        {
            "category_id": f"CAT{index:02d}",
            "category_name": f"模拟产品类别{index:02d}",
            "data_classification": SIMULATED,
        }
        for index in range(1, 13)
    ]
    products = []
    for index in range(1, 121):
        list_price = _money(80 + (index % 17) * 35 + rng.uniform(0, 25))
        products.append({
            "product_id": f"PRD{index:04d}",
            "product_name": f"模拟产品{index:04d}",
            "category_id": f"CAT{(index - 1) % 12 + 1:02d}",
            "list_price": list_price,
            "standard_cost": _money(list_price * Decimal(str(rng.uniform(0.48, 0.72)))),
            "data_classification": SIMULATED,
        })
    salespersons = []
    for index in range(1, 81):
        region = regions[(index - 1) % len(regions)]
        salespersons.append({
            "salesperson_id": f"SP{index:04d}",
            "salesperson_name": f"模拟销售人员{index:04d}",
            "region_id": region["region_id"],
            "organization_code": region["organization_code"],
            "data_classification": SIMULATED,
        })
    span_days = (PERIOD_END_EXCLUSIVE - PERIOD_START).days
    segments = ("enterprise", "small_business", "consumer", "government")
    customers = []
    for index in range(1, 8001):
        customers.append({
            "customer_id": f"CUS{index:06d}",
            "customer_name": f"模拟客户{index:06d}",
            "customer_segment": segments[(index - 1) % len(segments)],
            "home_region_id": regions[(index * 7) % len(regions)]["region_id"],
            "registered_date": PERIOD_START + timedelta(
                days=rng.randrange(span_days)
            ),
            "data_classification": SIMULATED,
        })
    return {
        "regions": regions,
        "channels": channel_rows,
        "categories": categories,
        "products": products,
        "salespersons": salespersons,
        "customers": customers,
    }


def _insert_chunks(
    db: Session,
    model,
    rows: list[dict],
    *,
    chunk_size: int = 2_000,
) -> None:
    for start in range(0, len(rows), chunk_size):
        db.execute(insert(model), rows[start:start + chunk_size])


def generate_sales_orders(
    db: Session,
    *,
    order_count: int = DEFAULT_ORDER_COUNT,
    seed: int = DEFAULT_SEED,
) -> SalesSeedSummary:
    if order_count < 1 or order_count > 100_000:
        raise ValueError("sales order_count must be between 1 and 100000")
    existing = int(db.scalar(select(func.count()).select_from(SalesOrder)) or 0)
    if existing:
        if existing != order_count:
            raise RuntimeError(
                "SALES_SEED_CONFLICT: existing simulated order count differs"
            )
        item_count = int(
            db.scalar(select(func.count()).select_from(SalesOrderItem)) or 0
        )
        checksum = _persisted_checksum(db)
        return SalesSeedSummary(
            seed=seed,
            seed_run_id=SEED_RUN_ID,
            order_count=existing,
            order_item_count=item_count,
            customer_count=int(
                db.scalar(select(func.count()).select_from(SalesCustomer)) or 0
            ),
            product_count=int(
                db.scalar(select(func.count()).select_from(SalesProduct)) or 0
            ),
            period_start=PERIOD_START.isoformat(),
            period_end_exclusive=PERIOD_END_EXCLUSIVE.isoformat(),
            data_classification=SIMULATED,
            checksum=checksum,
        )

    rng = random.Random(seed)
    dimensions = _dimension_rows(rng)
    _insert_chunks(db, SalesBusinessDate, _date_rows())
    _insert_chunks(db, SalesRegion, dimensions["regions"])
    _insert_chunks(db, SalesChannel, dimensions["channels"])
    _insert_chunks(db, SalesProductCategory, dimensions["categories"])
    _insert_chunks(db, SalesPerson, dimensions["salespersons"])
    _insert_chunks(db, SalesCustomer, dimensions["customers"])
    _insert_chunks(db, SalesProduct, dimensions["products"])
    db.flush()

    date_span = (PERIOD_END_EXCLUSIVE - PERIOD_START).days
    order_dates = sorted(
        PERIOD_START + timedelta(days=rng.randrange(date_span))
        for _ in range(order_count)
    )
    customers = [row["customer_id"] for row in dimensions["customers"]]
    products = dimensions["products"]
    channel_ids = [row["channel_id"] for row in dimensions["channels"]]
    region_ids = [row["region_id"] for row in dimensions["regions"]]
    people_by_region = {
        region_id: [
            person["salesperson_id"]
            for person in dimensions["salespersons"]
            if person["region_id"] == region_id
        ]
        for region_id in region_ids
    }
    organization_by_region = {
        row["region_id"]: row["organization_code"]
        for row in dimensions["regions"]
    }
    first_customer_order: set[str] = set()
    order_rows: list[dict] = []
    item_rows: list[dict] = []
    digest = hashlib.sha256()
    created_at = datetime(2026, 7, 1, tzinfo=UTC)

    for index, order_date in enumerate(order_dates, start=1):
        order_id = f"SO{index:08d}"
        customer_id = rng.choice(customers)
        region_id = rng.choice(region_ids)
        channel_id = rng.choices(
            channel_ids,
            weights=(32, 22, 18, 16, 12),
            k=1,
        )[0]
        salesperson_id = rng.choice(people_by_region[region_id])
        line_count = rng.choices((1, 2, 3), weights=(50, 35, 15), k=1)[0]
        discount_rate = {
            "CH01": 0.04,
            "CH02": 0.08,
            "CH03": 0.03,
            "CH04": 0.10,
            "CH05": 0.06,
        }[channel_id] + rng.uniform(0, 0.04)
        refunded = rng.random() < 0.07
        refund_rate = rng.uniform(0.3, 1.0) if refunded else 0.0
        order_gross = Decimal("0")
        order_discount = Decimal("0")
        order_refund = Decimal("0")
        order_net = Decimal("0")
        order_cost = Decimal("0")
        selected_products = rng.sample(products, k=line_count)
        for line_number, product in enumerate(selected_products, start=1):
            quantity = rng.randint(1, 5)
            unit_price = _money(
                product["list_price"] * Decimal(str(rng.uniform(0.94, 1.08)))
            )
            gross = _money(unit_price * quantity)
            discount = _money(gross * Decimal(str(discount_rate)))
            refund = _money(
                (gross - discount) * Decimal(str(refund_rate))
            )
            net = _money(gross - discount - refund)
            cost = _money(product["standard_cost"] * quantity)
            profit = _money(net - cost)
            item_rows.append({
                "order_item_id": f"{order_id}-{line_number:02d}",
                "order_id": order_id,
                "line_number": line_number,
                "product_id": product["product_id"],
                "quantity": quantity,
                "unit_price": unit_price,
                "gross_amount": gross,
                "discount_amount": discount,
                "refund_amount": refund,
                "net_revenue": net,
                "cost_amount": cost,
                "gross_profit": profit,
                "data_classification": SIMULATED,
                "seed_run_id": SEED_RUN_ID,
            })
            order_gross += gross
            order_discount += discount
            order_refund += refund
            order_net += net
            order_cost += cost
        is_new = customer_id not in first_customer_order
        first_customer_order.add(customer_id)
        order_profit = _money(order_net - order_cost)
        order_rows.append({
            "order_id": order_id,
            "order_date": order_date,
            "customer_id": customer_id,
            "channel_id": channel_id,
            "region_id": region_id,
            "salesperson_id": salesperson_id,
            "organization_code": organization_by_region[region_id],
            "gross_amount": _money(order_gross),
            "discount_amount": _money(order_discount),
            "refund_amount": _money(order_refund),
            "net_revenue": _money(order_net),
            "cost_amount": _money(order_cost),
            "gross_profit": order_profit,
            "status": "refunded" if refunded else "completed",
            "is_new_customer": 1 if is_new else 0,
            "data_classification": SIMULATED,
            "seed_run_id": SEED_RUN_ID,
            "created_at": created_at,
        })
        digest.update(
            (
                f"{order_id}|{order_date}|{customer_id}|{channel_id}|"
                f"{region_id}|{order_net}|{order_refund}|{order_profit}"
            ).encode()
        )
        if len(order_rows) >= 2_000:
            _insert_chunks(db, SalesOrder, order_rows)
            _insert_chunks(db, SalesOrderItem, item_rows)
            order_rows.clear()
            item_rows.clear()
    if order_rows:
        _insert_chunks(db, SalesOrder, order_rows)
        _insert_chunks(db, SalesOrderItem, item_rows)
    db.commit()
    item_count = int(
        db.scalar(select(func.count()).select_from(SalesOrderItem)) or 0
    )
    return SalesSeedSummary(
        seed=seed,
        seed_run_id=SEED_RUN_ID,
        order_count=order_count,
        order_item_count=item_count,
        customer_count=len(customers),
        product_count=len(products),
        period_start=PERIOD_START.isoformat(),
        period_end_exclusive=PERIOD_END_EXCLUSIVE.isoformat(),
        data_classification=SIMULATED,
        checksum=digest.hexdigest(),
    )


def _persisted_checksum(db: Session) -> str:
    digest = hashlib.sha256()
    rows = db.execute(
        select(
            SalesOrder.order_id,
            SalesOrder.order_date,
            SalesOrder.customer_id,
            SalesOrder.channel_id,
            SalesOrder.region_id,
            SalesOrder.net_revenue,
            SalesOrder.refund_amount,
            SalesOrder.gross_profit,
        ).order_by(SalesOrder.order_id)
    )
    for row in rows:
        digest.update("|".join(str(value) for value in row).encode())
    return digest.hexdigest()


def main() -> None:
    from app.bootstrap import bootstrap_demo_users
    from app.core.database import SessionLocal
    from app.models.auth import User
    from app.platform.identity import IdentityContextFactory
    from app.scenarios.sales_ops.package_adapter import install_sales_ops_foundation

    bootstrap_demo_users()
    with SessionLocal() as db:
        summary = generate_sales_orders(db)
        analyst = db.query(User).filter_by(username="analyst").one()
        installed = install_sales_ops_foundation(
            db,
            IdentityContextFactory.from_user(analyst),
        )
    print(json.dumps({
        "seed": summary.as_dict(),
        "platform": installed,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
