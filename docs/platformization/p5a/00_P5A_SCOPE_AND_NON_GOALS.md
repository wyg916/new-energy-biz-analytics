# P5A 范围与非目标

## 目标

P5A 仅修复并复验当前预生产环境内可以真实关闭的 P5 生产验收门禁：Git 远端分发、Docker/WSL 标准运行环境、PostgreSQL 权威回归、浏览器回归、镜像安全、容量耐久、故障与备份恢复，以及相应 Production Gate Registry 证据。

## 冻结边界

- 基线提交：`cf37a43c444515f2c92530aab050410efac4b544`。
- 冻结 P5 分支：`feat/p5-production-acceptance-gates`。
- P5A 分支：`fix/p5a-production-gate-remediation`。
- 独立工作树：`E:\新能源企业经营分析智能平台-p5a-remediation`。
- 数据仍为固定随机种子的模拟数据，时间范围为 2025-01-01 至 2026-06-30。
- 查询主链路继续为确定性参数化 SQL；`QUERY_ENGINE_MODE=SHADOW`，SQLBot 保持禁用且不进入 Canary。
- RAG 继续为 `KEYWORD_ONLY`，不发布向量运行时。
- `PRODUCTION_RELEASE_AUTHORIZED=false`，`PRODUCTION_TRAFFIC_SWITCHED=false`。

## 非目标

- 不进入 P6，不增加普通业务功能，不开放自由 SQL，不建设多 Agent。
- 不接入真实客户数据，不读取未授权 `.env*`，不搜寻旧凭据。
- 不用本地 Keycloak 冒充企业 IdP，不用本地 Vault 冒充托管生产 Secret Manager。
- 不伪造外部模型凭据、企业告警、变更窗口、风险接受或业务/安全/运维审批。
- 不删除或复用冻结阶段的 PostgreSQL、Redis、Vault 卷。
- 不修改 P4/P5 冻结工作树，不改写迁移或 Git 历史，不 force push。

## 验收真实性

只有本轮实际命令、当前数据库与当前生成证据可以关闭本地门禁。未运行、失败、缺少正式 waiver 或依赖外部授权的门禁保持 `OPEN`、`CONDITIONAL` 或 `BLOCKED`。即使本地技术整改全部通过，只要镜像 High 风险未消除且无正式 waiver，或外部门禁未关闭，最终仍为 `NO_GO`。
