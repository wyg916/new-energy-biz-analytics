# 发布、审批与回滚治理

## Release Registry

`platform_release` 对 Scenario Package、Semantic Model、RAG Document、Procedure、Skill、SQLBot Source Binding 和 Policy Bundle 建立统一版本记录。唯一约束包含 tenant、workspace、对象类型、对象 ID、版本和环境；历史版本不因激活或回滚而删除。

状态机为：

`DRAFT → REVIEW → APPROVED → ACTIVE → SUPERSEDED / ROLLED_BACK`

同时保留 `DISABLED` 状态。只有 APPROVED 且保存审批主体的版本可以 ACTIVE。新版本激活时旧 ACTIVE 变为 SUPERSEDED；回滚创建新的 ACTIVE 记录，引用当前版本和目标历史版本，而不是改写或删除历史。

## 环境边界

- 本地/预发布状态机和审计闭环已通过。
- `environment=production` 的激活固定拒绝并审计。
- 未审核版本激活成功数为 0。
- Policy 未审核 ACTIVE 成功数为 0。
- Procedure 原有审核门禁继续生效。
- SQLBot Canary 不随 Release Registry 自动切换。

当前隔离数据库 `platform_release` 为 0 行；发布状态机测试使用隔离事务/临时数据库完成，未执行真实生产发布。
