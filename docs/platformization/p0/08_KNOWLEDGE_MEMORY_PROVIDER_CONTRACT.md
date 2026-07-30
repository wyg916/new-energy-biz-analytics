# Knowledge / Memory Provider Contract v0.1

状态：**目标合同已冻结；P0 不实现 RAG 或长期记忆**。

## Knowledge Provider

```text
index(document, version, acl, classification) -> IndexReceipt
retrieve(query, identity_context, scenario_id, filters, top_k) -> Evidence[]
delete(document_id, version?) -> AuditReceipt
```

- 适用于指标说明、制度、SOP、案例和报告证据，不承担实时精确经营数字。
- 权限过滤必须在召回前执行；每条证据含文档、版本、片段、时间、ACL 和引用。
- 文档更新、失效、删除和重建必须可审计。

## Memory Provider

```text
load(session_id, identity_context, scenario_id) -> WorkingState
apply(session_id, expected_version, patch, ttl) -> WorkingState
delete(scope, identity_context) -> AuditReceipt
```

- P0 仅允许同一会话结构化工作状态、明确覆盖、新会话隔离和 analysis_run。
- 禁止保存整段对话作为长期记忆；长期偏好、历史案例、自动纠错和学习属于 P1。
- 必须有 TTL、乐观版本、删除、审计、数据分类和权限前置过滤。
- 当前数据库事实和本轮明确指令高于记忆。

## 当前差距

当前有数据库会话状态、analysis_run 和应用内 WorkingMemory；Redis 未成为正式 Provider，未实现知识索引、长期记忆或跨会话召回。

