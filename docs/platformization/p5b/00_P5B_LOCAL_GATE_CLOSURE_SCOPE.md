# P5B 最终本地门禁关闭范围

## 目标

P5B 只从 P5A 冻结提交 `d8c077d7c5ee72ca8a7bf5f0dccc861b17253cea` 关闭当前环境内可实际关闭的本地发布门禁，生成 `4.0.0-rc.3`。本轮不是重新执行 P0—P5A，也不进入 P6。

## 实施范围

- PostgreSQL、Keycloak、Vault 运行镜像的升级、加固、固定摘要和专项复验；
- SQLBot runtime 从 v4 首版 Compose、BOM、SBOM、readiness 和 RC 中正式排除，保留 Adapter 与离线合同测试；
- 在隔离环境完成代码、镜像、配置、RC、Release Registry 和 `p5_0001 -> p4_0001 -> p5_0001` 回滚演练；
- 受影响回归通过后执行最终全量验收，更新 Gate Registry 与证据包。

## 冻结边界

- `SQLBOT_INCLUDED_IN_V4_RELEASE=false`；
- `SQLBOT_RUNTIME=NOT_INCLUDED`；
- `SQLBOT_IMAGE_INCLUDED_IN_BOM=false`；
- `SQLBOT_CANARY_ELIGIBLE=false`；
- `SQLBOT_EXTERNAL_EVALUATION=DEFERRED`；
- DeterministicEngine 仍是唯一正式问数主链，RAG 仍为 keyword-only；
- 仅使用 2025-01-01 至 2026-06-30 固定种子模拟数据；
- 不修改 P5A 冻结工作树，不接触根工作树用户未跟踪文件，不读取 `.env*`；
- 不删除数据卷、Git 历史或审计证据，不部署生产、不切流、不使用真实客户数据；
- 外部 IdP、托管 Secret Manager、真实模型/SQLBot 评测、生产同构基础设施、生产 SLO、变更窗口和业务/安全/运维批准保持 OPEN/CONDITIONAL。

## 验收与真实性

所有 PASSED 必须由本轮实际运行证据支持。Trivy 不降级 severity、不使用 ignorefile、不删除发现、不虚构 waiver。SQLBot 原始 `49 Critical / 802 High` 仅作为历史扫描证据保留，不表述为已修复。正式生产验收、发布授权和流量切换始终为 `false`，最终 `GO_NO_GO=NO_GO`。
