# Governance Audit 与站内告警

## 审计闭环

`governance_audit_event` 统一记录 tenant、workspace、actor、principal、action、resource、result、`trace_id`、脱敏 detail 和时间。覆盖身份映射、授权拒绝、CredentialReference 使用、Memory、Procedure/Skill、Legal Hold/Retention、数据源治理、SQL 安全、SQLBot Shadow、发布和回滚。

数据库层通过 ORM 事件拒绝 UPDATE/DELETE，业务 API 只提供新增、检索、过滤、分页和 CSV 导出；普通业务用户不能修改审计事件。检索条件覆盖 tenant、actor、resource、action、result、时间与 `trace_id`，导出执行同一作用域和权限过滤。

## 告警

`security_alert` 按规则和 correlation key 聚合重复事件，支持站内查看与确认。本轮规则覆盖连续权限拒绝、CredentialReference 失败、跨租户尝试、SQL 安全违规、未审核 Procedure 激活和受 Legal Hold 阻止的删除。

本轮不发送邮件、工单、Webhook 或其他外部消息。

## 运行证据

- 隔离验收结束时审计事件：97 行。
- 站内安全告警：1 行，证明真实触发链路可用。
- 审计 UPDATE/DELETE 负向测试通过，普通用户修改成功数为 0。
- 审计详情与导出未包含 Secret 值。

行数是本轮本地运行快照，会随重复验收增加；不应作为业务指标或生产规模证明。
