# 身份与 SSO 架构

## 已实现范围

P3 建立了服务端统一 `Principal`，覆盖本地用户、外部主体、组、组成员关系、角色、租户、组织与工作区映射。业务代码继续使用 `IdentityContext`，但身份来源在进入业务服务前由可信中间件和 `IdentityService` 解析，不接受前端自报的 tenant、workspace、user 或 role 作为最终事实。

本地开发认证使用已有本地用户与签名令牌闭环。OIDC 侧提供 `OIDCProvider` 协议和可测试的签名测试 Provider，校验 issuer、audience、subject、有效期与映射状态；只有预先存在且状态有效的主体映射可以登录，不做即时 JIT 建号。

## 信任边界

- Header 中伪造的租户、用户和角色不会覆盖服务端解析结果。
- 模型输出、自然语言问题和请求参数不能授予权限。
- 主体必须同时匹配 tenant、organization、workspace 和有效状态。
- 未映射、过期、签名错误、issuer/audience 不匹配均 fail-closed。
- 认证和映射结果写入治理审计，并由 `trace_id` 串联。

## 当前运行基线

- `identity_principal`：3 行本地主体。
- `identity_group`：0 行；`identity_group_membership`：0 行。
- 运行数据为固定种子模拟数据，期间为 2025-01-01 至 2026-06-30。
- 本轮未接入真实企业 IdP、企业目录或真实客户身份；真实 SSO 仍是生产门禁。

## 回滚

代码按 P3 独立提交执行 `git revert`；数据库使用 Alembic 从 `p3_0001` 降级到 merge revision。不得删除身份历史或数据库卷。
