import re
from datetime import date, timedelta

from app.chatbi.plan import Clarification, Filter, QueryPlan, TimeRange

METRIC_TERMS = {
    "charging_revenue": ["充电收入", "充电营收", "营收", "收入"],
    "service_fee_revenue": ["服务费收入", "服务费营收", "服务费"],
    "completed_order_count": ["完成订单", "订单数", "单量", "充电订单"],
    "charging_volume_kwh": ["充电量", "充电电量", "电量"],
    "energy_cost": ["电费成本", "采购电费", "电能成本"],
    "variable_operating_cost": ["可变运营成本", "变动运营成本", "可变成本"],
    "gross_profit": ["经营毛利", "毛利"],
    "gross_margin": ["毛利率", "经营毛利率"],
    "avg_order_energy_kwh": ["单均充电量", "单均电量", "每单电量"],
    "revenue_per_kwh": ["度电收入", "单位电量收入", "每度收入"],
    "cost_per_kwh": ["度电成本", "单位电量成本", "每度成本"],
    "station_utilization_rate": ["场站利用率", "利用率", "枪口利用率"],
    "device_online_rate": ["设备在线率", "在线率", "设备可用率"],
    "device_fault_rate": ["设备故障率", "故障率", "故障时长占比"],
    "active_user_count": ["活跃用户数", "活跃用户", "充电用户数"],
}
DANGEROUS = re.compile(r"(?i)(\bselect\b|\bdrop\b|\bdelete\b|\binsert\b|\bupdate\b|\btruncate\b|pg_catalog|information_schema|手机号|身份证|密码|密钥|token|删除.*表)")


def _metrics(question: str) -> list[str]:
    matches = []
    for metric_id, terms in METRIC_TERMS.items():
        positions = [question.find(term) for term in terms if term in question]
        if positions:
            matches.append((min(positions), metric_id))
    # Prefer exact compound concepts and remove generic overlaps.
    ids = [metric_id for _, metric_id in sorted(matches)]
    if "gross_margin" in ids and "gross_profit" in ids and "毛利和毛利率" not in question:
        ids.remove("gross_profit")
    if "revenue_per_kwh" in ids and "charging_revenue" in ids:
        ids.remove("charging_revenue")
    if "cost_per_kwh" in ids and "energy_cost" in ids:
        ids.remove("energy_cost")
    return list(dict.fromkeys(ids))[:5]


def _time_range(question: str) -> TimeRange | None:
    match = re.search(r"(20\d{2})年(\d{1,2})月", question)
    if match:
        year, month = map(int, match.groups())
        end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
        return TimeRange(start=date(year, month, 1), end_exclusive=end, grain="day" if "每日" in question else "month")
    match = re.search(r"(20\d{2})年(?:第)?([一二三四1234])季度", question)
    if match:
        year = int(match.group(1)); token = match.group(2); quarter = {"一":1,"二":2,"三":3,"四":4}.get(token, int(token) if token.isdigit() else 1)
        month = (quarter - 1) * 3 + 1
        return TimeRange(start=date(year, month, 1), end_exclusive=date(year + (quarter == 4), 1 if quarter == 4 else month + 3, 1), grain="month")
    match = re.search(r"(20\d{2})年上半年", question)
    if match:
        year = int(match.group(1)); return TimeRange(start=date(year, 1, 1), end_exclusive=date(year, 7, 1), grain="month")
    match = re.search(r"(20\d{2})年下半年", question)
    if match:
        year = int(match.group(1)); return TimeRange(start=date(year, 7, 1), end_exclusive=date(year + 1, 1, 1), grain="month")
    match = re.search(r"截至(20\d{2})年(\d{1,2})月(\d{1,2})日", question)
    if match and "最近12周" in question:
        end = date(*map(int, match.groups())) + timedelta(days=1); return TimeRange(start=end - timedelta(weeks=12), end_exclusive=end, grain="week")
    match = re.search(r"(20\d{2})年", question)
    if match:
        year = int(match.group(1)); return TimeRange(start=date(year, 1, 1), end_exclusive=date(year + 1, 1, 1), grain="month")
    return None


def parse_question(question: str) -> QueryPlan:
    normalized = question.strip()
    if DANGEROUS.search(normalized):
        return QueryPlan(status="rejected", intent="unsupported", clarification=Clarification(reason_code="unsupported_request", question="该请求不属于受控经营分析范围。"))
    metrics = _metrics(normalized)
    period = _time_range(normalized)
    if not metrics:
        return QueryPlan(status="needs_clarification", intent="metric_lookup", clarification=Clarification(reason_code="missing_metric", question="请明确要查询的经营指标。"))
    if period is None:
        return QueryPlan(status="needs_clarification", intent="metric_lookup", metrics=metrics, clarification=Clarification(reason_code="missing_time", question="请明确查询时间范围。"))
    filters = []
    region = re.search(r"区域\s*([ABC])", normalized, re.I)
    if region: filters.append(Filter(field="region", value=f"区域{region.group(1).upper()}"))
    station = re.search(r"场站\s*([A-Z]\d{2})", normalized, re.I)
    if station: filters.append(Filter(field="station", value=f"场站{station.group(1).upper()}"))
    intent = "metric_lookup"; dimensions: list[str] = []; analysis: list[str] = []
    if any(term in normalized for term in ("趋势", "每月", "每日", "每周")):
        intent = "trend"; dimensions = [period.grain or "month"]; analysis = ["trend"]
    if any(term in normalized for term in ("排名", "排行", "最高", "最低", "Top")):
        intent = "ranking"; dimensions = ["station"]; analysis = ["ranking"]
    if any(term in normalized for term in ("同比", "环比", "对比", "比较")):
        intent = "comparison"; analysis = ["comparison"]
    if any(term in normalized for term in ("为什么", "原因", "拆解", "贡献")):
        intent = "diagnosis"; analysis = ["diagnosis"]
    return QueryPlan(status="ready", intent=intent, metrics=metrics, time_range=period, filters=filters, dimensions=dimensions, analysis=analysis, limit=30 if intent == "ranking" else 100)
