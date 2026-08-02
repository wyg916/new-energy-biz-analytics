# P5 范围与非目标

冻结日期：2026-08-02。

## 唯一目标

P5 只负责生产验收门禁关闭、安全风险处置和最终 Go/No-Go 证据闭环。工作从 P4 冻结提交 `a28b92b5e83545bf8b0bb47bf2f3efa3c9d8d39d` 开始，不重新实现或重新声明 P0—P4 已完成能力。

允许范围包括：容器镜像安全复扫与兼容升级、Production Gate Registry、企业 IdP 与 Secret Manager 验收模板、授权存在时的 SQLBot 外部安全复评、RAG 正式模式决策、代表性本地容量验收、企业告警与生产数据接入门禁、治理 UI、回归测试、唯一验收包、独立提交和普通推送。

## 本阶段真实性边界

- 数据继续使用固定种子、业务规则驱动并已落库的模拟数据，期间为 2025-01-01 至 2026-06-30；不得将其描述为真实客户数据。
- 未提供真实企业 IdP 测试租户，`EXTERNAL_ENTERPRISE_IDP=CONDITIONAL`。
- 未提供授权外部模型 CredentialReference，不读取旧 Key、不读取或扫描 `.env*`、不发起外部模型请求；SQLBot 10/30/20 保持 `CONDITIONAL`。
- 未提供企业告警测试接收端，企业联调保持 `CONDITIONAL`；本地签名适配器的既有 PASS 不能替代企业联调。
- 未提供代表性生产规格，本地实测不能写成生产 SLA，`PRODUCTION_CAPACITY_VERIFIED=false`。
- 未授权真实客户数据接入；生产数据门禁保持 OPEN，继续使用固定种子模拟数据。
- 无正式批准人和风险接受依据时不得创建 WAIVED 状态。

## 固定技术合同

- 模块化单体；不拆微服务、不建设多 Agent。
- 自然语言问题仍经 Query Plan、确定性参数化 SQL、Query Guard、只读执行、结构化结果和 Answer Guard；不开放自由 SQL。
- DeterministicEngine 继续提供正式主答案；SQLBot 保持 Shadow、disabled-by-default，故障不得影响主答案。
- RAG 必须在本阶段做出明确二选一决策；除非完整 Vector 发布合同和评测全部通过，否则正式冻结为 keyword-only。
- 核心指标 15 项、发布结构 15+12 不得改变。
- Production Gate Registry 只能记录真实证据；普通用户只读，任何 WAIVED 必须有批准人与风险接受依据。

## 明确非目标

- 不执行正式生产部署、切流、自动审批或外部消息。
- 不启用 SQLBot Canary，不把候选资格自动置为 true。
- 不接入真实客户生产数据或未经授权的外部系统。
- 不改写历史 migration，不删除 PostgreSQL、Redis 或 Vault 卷。
- 不降低 Guard、扫描阈值或通过忽略 CVE 制造通过结果。
- 不伪造风险接受、审批人、SLA、外部联调或生产可用结论。

## 固定发布状态

在用户完成验收后另行明确授权前，始终保持：

```text
PRODUCTION_RELEASE_AUTHORIZED=false
PRODUCTION_TRAFFIC_SWITCHED=false
SQLBOT_ENGINE_ENABLED=false
SQLBOT_CANARY_ELIGIBLE=false
```

