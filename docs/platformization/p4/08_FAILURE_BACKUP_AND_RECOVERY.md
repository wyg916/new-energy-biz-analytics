# 故障、备份与恢复

## 故障演练

Redis、PostgreSQL 和 Vault 均在不删除卷的前提下执行真实停止/恢复。三者不可用时 readiness 返回 503，恢复后返回 200；最终 API/DB/Redis/Vault restart count 均为 0。Vault 故障时 CredentialReference 解析 fail-closed，明文 fallback 和 Secret 泄漏均为 0。

RAG、SQLBot、Secret、Retention、Redis 等故障单元套件 58/58 PASS。RAG 不可用时受控降级且不伪造引用；SQLBot 不可用影响确定性主答案数 0。实际服务故障结果见 `evidence/p4_fault_recovery.json`。

## 备份恢复实测

RC 激活后创建 custom-format 最终备份 `/backups/p4-acceptance.dump`，SHA-256 `e5ccf0509d6bcd327fdc38a4796c4a87473ce0549d289dd0b50f850fd5ef5871`。在无并发业务写入下恢复到独立临时数据库 `p4_restore_verify_post_rc_clean` 后，源/恢复摘要与数据哈希一致：

- charging sessions 300000；sales orders 50000；sales order items 82514；
- metric definitions 15；published metrics 27；
- CredentialReference 元数据 9；datasource governance 3；验收记录 18；
- 权威 Memory 6527；Governance Audit 6594；既有 Release Registry 8；P4 PlatformRelease 1；
- 数据哈希 `a55192ad4704ff27870f2ba4da142051`；
- Governance Audit、Release Registry、权威 Memory、凭据元数据随 PostgreSQL 恢复；Secret 值不在数据库备份中；
- 恢复临时数据库已移除，源卷未删除。

Redis Working 状态按合同允许丢失并由权威 PostgreSQL/当前会话重建，不把 Redis 当作权威 Memory。证据见 `evidence/p4_backup_restore.json`。

## 迁移与回滚

独立临时数据库完成 `base → p4_0001 → base → p4_0001`，最终唯一 head/current 均为 `p4_0001`。代码、配置、发布版本和 Source Binding 回滚均保留历史；不得 `reset --hard`、改写 migration 或删除卷。迁移证据见 `evidence/p4_migration_cycle.json`。
