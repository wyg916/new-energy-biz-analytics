# Query Engine Contract v0.1

状态：**目标合同已冻结；当前 deterministic charging_ops 链路部分满足**。

## 请求与结果

```text
QueryRequest {
  question, conversation_state, tenant_id?, workspace_id?,
  scenario_id, semantic_model_version, dataset_version,
  identity_context, locale, limits
}
QueryResult {
  query_plan, compiled_query, parameters, structured_result,
  guards, lineage, run_id, warnings, metadata
}
```

## 固定链路

自然语言 → 场景路由 → 结构化 Query Plan → 语义校验 → 确定性参数化编译 → Query Guard → 只读执行 → 结构化结果 → Answer Guard。

## 安全不变量

- LLM 不直接生成或执行核心 SQL。
- 只允许 SELECT/CTE 和 allowlist 函数、表、列、join graph。
- 必须强制权限过滤、时间范围、行数、复杂度、超时和并发配额。
- Query Guard 拒绝不可绕过；失败返回稳定错误码。
- 答案中的业务数字必须可在结构化结果中定位。
- 结果元数据必须含 semantic/dataset/scenario 版本、run_id、数据时间和来源。

## 引擎扩展

未来 SQLBot 只能作为 `QueryPlanner` 或非核心探索适配器接入；核心指标仍由确定性编译器处理。任何双引擎路由必须显式、可审计、可关闭。

## 当前差距

当前 Query Plan 和 guard 可复用，但 parser/compiler/指标枚举绑定 charging_ops；执行使用应用数据库会话，尚未证明独立数据库只读角色、通用版本绑定和租户策略。

