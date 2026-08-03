# 4.0.0-rc.3 验收包

## 发布边界

RC3 的唯一正式 NL2SQL 主链为 DeterministicEngine；RAG 为 keyword-only；SQLBot runtime、镜像、Canary 和外部评测不属于本版本。所有业务数据为模拟数据，期间 2025-01-01 至 2026-06-30，来源为 PostgreSQL，`run_id` 位置随各证据记录。

## 机器可核验证据

- `evidence/p5b-rc-4.0.0-rc.3-manifest.json`：RC 组件、镜像 ID/digest、状态和证据哈希。
- `evidence/p5b-sbom.cdx.json`：CycloneDX 1.6 SBOM；SQLBot 出现次数必须为 0。
- `evidence/container-security/container-security-summary.json`：10 角色最终 Trivy 汇总及原始报告索引。
- `evidence/p5b-final-regression-summary.json`：后端、固定评测、前端和运行合同汇总。
- `evidence/p5b-backup-restore.json`、`evidence/p5b-fault-recovery.json`、`evidence/p5b-rollback-drill.json`：恢复与实际回滚证据。
- `evidence/p5b-gate-snapshot-pre-push.json`：推送前 Gate Registry 和本地历史。
- `evidence/p5b-secret-scan.json`：最终候选相对 P5A 冻结基线的敏感信息扫描。

## 发布结论

`P5B_IMPLEMENTATION=PASS`

`LOCAL_PREPRODUCTION_RC=PASS_WITH_EXTERNAL_PRODUCTION_GATES`

`PRODUCTION_ACCEPTANCE_READY=false`

`PRODUCTION_RELEASE_AUTHORIZED=false`

`PRODUCTION_TRAFFIC_SWITCHED=false`

`SQLBOT_CANARY_ELIGIBLE=false`

`GO_NO_GO=NO_GO`

`P6_ENTRY=NOT_ALLOWED`

下一步不是继续本地开发，而是等待并逐项取得生产同构环境、企业 IdP/Secret Manager/告警、真实数据授权、变更窗口、风险接受及业务/安全/运维批准；完成前不得提交生产发布申请。
