# P5A 故障、备份、恢复与回滚

## 验收边界

本页只记录独立 `renewable-p5a-remediation` 预生产验收环境。业务数据是 PostgreSQL 中 2025-01-01 至 2026-06-30 的固定种子模拟数据；本页不构成生产灾备承诺、生产 RTO/RPO 或发布授权。

故障注入必须逐项串行执行，每次恢复 healthy/readiness 后才能进入下一项。不得删除或重新初始化 PostgreSQL、Redis、Vault 现有卷，不得以新初始化数据冒充恢复。

## 已完成的迁移循环

隔离数据库 `p5a_migration_verify` 已实际完成 `base → p5_0001 → p4_0001 → p5_0001`：

- 唯一 head：`p5_0001`；
- 观察到的回滚 revision：`p4_0001`；
- 再升级回 `p5_0001`：PASS；
- 隔离临时库已移除；
- 现有数据卷删除数：0。

证据：`evidence/p5a-migration-cycle.json`。该数据库迁移循环不能替代服务、配置和代码回滚演练，因此 `ROLLBACK_DRILL` 在没有完整运行证据时继续为 `BLOCKED`。

## 故障注入与恢复结果

2026-08-03 在容量验收之后按 Redis → PostgreSQL → Vault → Keycloak 顺序串行执行。每项均先观察 readiness 503、liveness 200，再恢复到容器 healthy 与 readiness 200；卷删除、源库重建和异常自动重启均为 0。

| 故障 | readiness fail-closed | 容器 healthy | readiness 恢复 | 业务负向证明 |
|---|---:|---:|---:|---|
| Redis | 3.391 s | 5.375 s | 0.078 s | readiness 503、liveness 200 |
| PostgreSQL | 3.329 s | 5.437 s | 0.110 s | RAG 请求 HTTP 500、引用数 0、伪造引用 false |
| Vault | 3.375 s | 0.078 s | 0.109 s | CredentialReference 返回 `VAULT_AUTH_FAILED`，明文 fallback false |
| Keycloak | 3.375 s | 20.828 s | 0.328 s | OIDC provider 状态 `UNAVAILABLE` |

恢复后 SQLBot 容器数为 0，runtime/canary 均为 false；Deterministic 主链 HTTP 200 且结构化查询完成。第二轮最终证据为 PASS。第一轮实际执行因 Keycloak 历史 `RestartCount` 在手工启动时从 10 重置为 0，被脚本误判为新增重启而返回 FAIL；修正为仅把计数增加判为异常后完整重跑，未把第一次失败解释成基础设施通过。Vault 失败探测形成治理审计增量 2；首次探测触发 1 条安全告警，第二轮保留该告警记录。

证据：`evidence/p5a-fault-recovery.json`。

## Vault 与备份隔离恢复

P5A Vault 专用复验 run_id 为 `P5A-VAULT-20260803T101306Z`：AppRole、KV v2、禁用凭据、最新凭据绑定修复、轮换、回滚和回滚后只读连接均 PASS；Vault audit 增长 52,564 bytes，Secret 值输出为 false。

随后创建新备份 `/backups/p5a-acceptance-20260803T101319Z.dump`：

- 大小：28,222,229 bytes；
- SHA-256：`4b0ecc0c9cab9eb1ce25da16cd9661ca5b561409e8cc1faf71b772b2bf38e9ed`；
- 隔离库：`p5a_restore_verify_20260803`，完成核对后已移除；
- Alembic：源库/恢复库均为 `p5_0001`；
- 业务哈希：源库/恢复库均为 `a2075cae3f830db1bad5ca9ef845919e`；
- 固定数据量：300,000 charging sessions、50,000 sales orders、82,514 sales order items；
- Memory、Audit、Release Registry、Production Gate/history、acceptance、security alert、legal hold 计数全部一致；
- CredentialReference 明文列与禁止 metadata 行均为 0；
- 源库修改、已有卷删除、Secret 输出均为 false。

证据：`evidence/p5a-vault-acceptance.json`、`evidence/p5a-backup-restore.json`。

## 代码、配置与版本回滚方式

- 代码：保留冻结 P5 `cf37a43c444515f2c92530aab050410efac4b544`；如需撤销 P5A，先停止新的验收操作，在 P5A 分支按提交逆序使用普通 `git revert` 形成可审计回滚提交，不使用 `reset --hard`、force push 或改写历史。
- 镜像：按回滚提交对应的固定 tag/digest 重建或重新部署；回滚前后均复验 liveness、readiness、migration revision、固定数据量与 SQLBot disabled 状态。
- 配置：P5A 增加的数据库连接池环境项通过 `p5a.override.yaml` 管理；回滚配置时必须保持 Secret 文件挂载、OIDC-only、Query Guard、SHADOW、keyword-only RAG、SQLBot disabled 和生产发布 false，不允许用降低安全边界换取恢复。
- 数据库：P5A 没有新增或改写 migration。只有在明确批准的维护窗口、完整备份已验证、隔离迁移循环已通过时，才允许针对目标 revision 执行受控 Alembic downgrade/upgrade；不得删除源库或卷。
- 数据卷：PostgreSQL、Redis、Vault 卷始终原地保留。若服务回滚失败，保持 fail-closed，记录真实阻断并恢复到最后已验证版本，不重新初始化数据。

## 当前结论

本地故障恢复、Vault 复验、新备份与隔离恢复均已验证，可关闭 `BACKUP_RECOVERY` 与 `BACKUP_RESTORE`。迁移循环虽已通过，但没有完整代码、配置、镜像和服务版本回滚演练，因此 `ROLLBACK_DRILL` 继续 `BLOCKED`，不得外推为生产 RTO/RPO。
