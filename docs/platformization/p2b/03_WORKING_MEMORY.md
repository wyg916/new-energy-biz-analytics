# Working Memory

## 已实现

Working Memory 使用 Redis 保存当前场景、数据集/语义版本、时间范围、指标、维度、
筛选条件、图表类型、上一轮结果摘要、Knowledge 引用、SQLBot session binding、
未完成 Task DAG 和 Response Profile。

每个 key 包含 identity、workspace、scenario 与 session/run 作用域；写入支持
idempotency key 和 TTL。会话关闭会清理对应 key。值大小和敏感字段在序列化前检查，
完整业务明细、API Key、Token 和数据库凭据均被拒绝。

## 多轮语义

固定评测覆盖以下继承链：收入查询建立时间与指标，区域追问只覆盖筛选，场站追问
追加维度，同比追问覆盖比较方式，报告请求复用累计状态。明确的新值覆盖旧值；未提及
字段继续继承，避免重新猜测。

## Redis 故障

Redis 不可用时返回显式 degraded 状态，不静默伪造工作状态；请求可以按无 Working
Memory 路径继续，但 PostgreSQL `memory_audit_event` 记录降级事实。恢复后不会把
降级期间的猜测状态反向写成 ACTIVE 长期记忆。
