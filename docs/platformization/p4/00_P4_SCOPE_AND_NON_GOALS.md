# P4 范围与非目标

## 状态声明

- 工作包：`P4-PREPRODUCTION-INTEGRATION-AND-RELEASE-CANDIDATE`
- 冻结基线：`36ad33810031c52869d88de7cf35dbdaaaa10446`
- 开发分支：`feat/p4-preproduction-rc`
- 独立工作树：`E:\新能源企业经营分析智能平台-p4-rc`
- 业务数据：固定种子模拟数据，期间为 2025-01-01 至 2026-06-30
- 正式主答案：`DeterministicEngine`
- SQLBot：`SHADOW`、`SQLBOT_ENGINE_ENABLED=false`、`SQLBOT_CANARY_ELIGIBLE=false`
- 生产发布授权：`PRODUCTION_RELEASE_AUTHORIZED=false`

本文只冻结 P4 允许范围，不把目标描述为已完成。最终状态以本目录的测试矩阵、外部门禁和实施报告为准。

## 主线范围

1. 独立 Compose project、网络、端口和卷的可重复预生产拓扑。
2. 标准 Keycloak OIDC Authorization Code Flow、PKCE、JWKS、nonce/state、预映射与注销闭环。
3. Vault KV v2 非明文 Secret Provider、CredentialReference、版本、缓存、轮换和故障门禁。
4. 数据源创建、凭据引用、测试、发现、画像、分类、授权、审核、发布、激活、停用、轮换和回滚。
5. SQLBot 安全 CredentialReference 前置门禁和条件外部 10/30/20 复评。
6. 容量、30 分钟耐久、依赖故障、迁移、备份、恢复和一致性验收。
7. disabled-by-default 的签名 Webhook 告警测试适配器。
8. P4 管理 API、现有 React UI 扩展和 Release Candidate 交付清单。

## 非目标

- 不接入真实企业 IdP、真实客户数据或未经授权的外部模型凭据。
- 不宣称生产容量、生产 SLA、正式生产上线或真实经营收益。
- 不开启 SQLBot Canary，不替换确定性主链，不保存 Shadow 为长期业务事实。
- 不开发第三个场景、多 Agent、自由 SQL、自动审批、自动生产发布或真实外部通知。
- 不降低 RBAC/ABAC、Query Guard、Answer Guard、Memory Guard 或 RAG 权限过滤。
- 不删除 PostgreSQL/Redis/Vault 卷，不改写既有 migration，不读取或扫描 `.env*`。

## 条件轨道

真实 SQLBot 10 Smoke、30 Golden、20 Shadow 只有在授权的外部模型配置和安全 CredentialReference 均可用时执行。任一前置条件缺失时必须在网络调用前 fail-closed、外部请求为 0，并报告 `CONDITIONAL`。

## 回滚原则

代码按 P4 独立提交逆序 `git revert`；数据库只执行已验证 Alembic downgrade；Compose 配置和 RC Manifest 回到上一已验证版本。任何回滚均不得删除运行卷或审计/发布历史。
