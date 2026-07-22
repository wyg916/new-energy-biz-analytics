from sqlalchemy import text
from sqlalchemy.orm import Session

from app.chatbi.compiler import CompiledQuery
from app.chatbi.guard import guard_compiled_query


def execute_readonly(db: Session, compiled: CompiledQuery) -> dict[str, float | int | None]:
    guard_compiled_query(compiled)
    row = db.execute(text(compiled.sql), compiled.parameters).mappings().one()
    result = {}
    for metric_id in compiled.metric_ids:
        value = row[metric_id]
        result[metric_id] = None if value is None else int(value) if metric_id in {"completed_order_count", "active_user_count"} else round(float(value), 6)
    return result
