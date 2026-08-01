"""Prepare the repeatable P3 PostgreSQL acceptance dataset and semantic releases.

The script only accepts a database already migrated to ``p3_0001``. It uses
the frozen business rules and fixed seeds, and refuses to mix charging batches.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.data.seed import SEED as CHARGING_SEED
from app.data.seed import generate_simulated_data
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.scenarios.charging_ops.package_adapter import install_platform_foundation
from app.scenarios.sales_ops.package_adapter import install_sales_ops_foundation
from app.scenarios.sales_ops.seed import DEFAULT_ORDER_COUNT, DEFAULT_SEED
from app.scenarios.sales_ops.seed import generate_sales_orders


EXPECTED_REVISION = "p3_0001"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--charging-sessions", type=int, default=300_000)
    parser.add_argument("--sales-orders", type=int, default=DEFAULT_ORDER_COUNT)
    args = parser.parse_args()

    with SessionLocal() as db:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != EXPECTED_REVISION:
            raise RuntimeError(
                f"P3 acceptance database must be at {EXPECTED_REVISION}, got {revision}"
            )
        analyst = db.scalar(select(User).where(User.username == "analyst"))
        if analyst is None:
            raise RuntimeError(
                "required pre-seeded local analyst principal is unavailable"
            )
        identity = IdentityContextFactory.from_user(analyst)

        charging_counts = generate_simulated_data(
            db,
            session_count=args.charging_sessions,
            seed=CHARGING_SEED,
        )
        charging_platform = install_platform_foundation(db, identity)
        sales_summary = generate_sales_orders(
            db,
            order_count=args.sales_orders,
            seed=DEFAULT_SEED,
        )
        sales_platform = install_sales_ops_foundation(
            db,
            identity,
            expected_order_count=args.sales_orders,
        )
        db.commit()

    print(json.dumps({
        "alembic_revision": revision,
        "data_classification": "simulated",
        "period_start": "2025-01-01",
        "period_end_exclusive": "2026-07-01",
        "charging_seed": CHARGING_SEED,
        "charging": charging_counts,
        "charging_platform": charging_platform,
        "sales_seed": DEFAULT_SEED,
        "sales": sales_summary.as_dict(),
        "sales_platform": sales_platform,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
