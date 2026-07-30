from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.sales import SalesOrder, SalesOrderItem

SALES_METRICS = {
    "sales_revenue": ("销售收入", "元"),
    "order_count": ("订单数", "单"),
    "customer_count": ("客户数", "个"),
    "average_order_value": ("平均订单金额", "元/单"),
    "sales_quantity": ("销售数量", "件"),
    "gross_profit": ("销售毛利", "元"),
    "gross_margin": ("销售毛利率", "%"),
    "refund_amount": ("退款金额", "元"),
    "refund_rate": ("退款率", "%"),
    "new_customer_count": ("新客户数", "个"),
    "repeat_customer_count": ("复购客户数", "个"),
    "channel_contribution": ("最大渠道贡献率", "%"),
}


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


class SalesOpsMetricService:
    def __init__(self, db: Session):
        self.db = db

    def calculate(
        self,
        start: date,
        end_exclusive: date,
        *,
        region_ids: tuple[str, ...] | None = None,
        channel_ids: tuple[str, ...] | None = None,
    ) -> dict[str, float | int | None]:
        if start >= end_exclusive:
            raise ValueError("sales metric date range is invalid")
        conditions = [
            SalesOrder.order_date >= start,
            SalesOrder.order_date < end_exclusive,
            SalesOrder.status.in_(("completed", "refunded")),
        ]
        if region_ids is not None:
            if not region_ids:
                raise PermissionError("sales region scope is empty")
            conditions.append(SalesOrder.region_id.in_(region_ids))
        if channel_ids is not None:
            if not channel_ids:
                raise PermissionError("sales channel scope is empty")
            conditions.append(SalesOrder.channel_id.in_(channel_ids))
        aggregate = self.db.execute(
            select(
                func.coalesce(func.sum(SalesOrder.net_revenue), 0),
                func.count(SalesOrder.order_id),
                func.count(func.distinct(SalesOrder.customer_id)),
                func.coalesce(func.sum(SalesOrder.gross_amount), 0),
                func.coalesce(func.sum(SalesOrder.gross_profit), 0),
                func.coalesce(func.sum(SalesOrder.refund_amount), 0),
                func.count(
                    func.distinct(
                        case(
                            (SalesOrder.is_new_customer == 1, SalesOrder.customer_id),
                        )
                    )
                ),
                func.count(
                    func.distinct(
                        case(
                            (SalesOrder.is_new_customer == 0, SalesOrder.customer_id),
                        )
                    )
                ),
            ).where(*conditions)
        ).one()
        (
            revenue_raw,
            order_count,
            customer_count,
            gross_amount_raw,
            profit_raw,
            refund_raw,
            new_customer_count,
            repeat_customer_count,
        ) = aggregate
        quantity_conditions = list(conditions)
        quantity = int(self.db.scalar(
            select(func.coalesce(func.sum(SalesOrderItem.quantity), 0))
            .join(SalesOrder, SalesOrder.order_id == SalesOrderItem.order_id)
            .where(*quantity_conditions)
        ) or 0)
        channel_rows = self.db.execute(
            select(
                SalesOrder.channel_id,
                func.coalesce(func.sum(SalesOrder.net_revenue), 0),
            )
            .where(*conditions)
            .group_by(SalesOrder.channel_id)
        ).all()
        revenue = round(float(revenue_raw or 0), 2)
        gross_amount = round(float(gross_amount_raw or 0), 2)
        profit = round(float(profit_raw or 0), 2)
        refund = round(float(refund_raw or 0), 2)
        max_channel_revenue = max(
            (float(row[1]) for row in channel_rows),
            default=0.0,
        )
        return {
            "sales_revenue": revenue,
            "order_count": int(order_count or 0),
            "customer_count": int(customer_count or 0),
            "average_order_value": _ratio(revenue, int(order_count or 0)),
            "sales_quantity": quantity,
            "gross_profit": profit,
            "gross_margin": _ratio(profit, revenue),
            "refund_amount": refund,
            "refund_rate": _ratio(refund, gross_amount),
            "new_customer_count": int(new_customer_count or 0),
            "repeat_customer_count": int(repeat_customer_count or 0),
            "channel_contribution": _ratio(max_channel_revenue, revenue),
        }

    def by_dimension(
        self,
        start: date,
        end_exclusive: date,
        *,
        dimension: str,
        limit: int = 50,
    ) -> tuple[dict, ...]:
        dimensions = {
            "region": SalesOrder.region_id,
            "channel": SalesOrder.channel_id,
            "salesperson": SalesOrder.salesperson_id,
            "organization": SalesOrder.organization_code,
        }
        column = dimensions.get(dimension)
        if column is None:
            raise ValueError("sales dimension is not supported")
        if limit < 1 or limit > 500:
            raise ValueError("sales dimension limit is invalid")
        rows = self.db.execute(
            select(
                column.label(dimension),
                func.sum(SalesOrder.net_revenue).label("sales_revenue"),
                func.count(SalesOrder.order_id).label("order_count"),
                func.sum(SalesOrder.gross_profit).label("gross_profit"),
            )
            .where(
                SalesOrder.order_date >= start,
                SalesOrder.order_date < end_exclusive,
            )
            .group_by(column)
            .order_by(func.sum(SalesOrder.net_revenue).desc())
            .limit(limit)
        ).mappings().all()
        return tuple({
            dimension: row[dimension],
            "sales_revenue": round(float(row["sales_revenue"] or 0), 2),
            "order_count": int(row["order_count"] or 0),
            "gross_profit": round(float(row["gross_profit"] or 0), 2),
        } for row in rows)
