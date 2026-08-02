# OIDC 集成与验收

## 已实现闭环

本地隔离 Keycloak 26.7.0 作为真实标准 OIDC Provider，provider code 为 `OIDC_PREPROD`。浏览器实际完成 Authorization Code Flow + PKCE S256：应用生成 Redis 一次性 state、nonce 和 verifier，Keycloak 返回授权码，后端交换并以远端 JWKS 验证 RS256 签名、issuer、audience、有效期与 nonce，再通过数据库中已审批 Principal、组、tenant 和 workspace 映射生成可撤销应用会话。

映射事实：外部 subject `11111111-1111-4111-8111-111111111111` → `PRN-P4-OIDC-ANALYST` → 本地 analyst；必需组 `analysts`；角色 `analyst_admin`；tenant `tenant-alpha`；workspace `workspace-alpha`；data scope `workspace:all`。身份字段只来自服务端映射，前端提交 tenant/user 不具有授权效力。

## 实际验收

- 最终依赖硬化镜像上的 Playwright：3/3 PASS。
- 完整 Code + PKCE 登录后读取 P4 正式 API：PASS。
- 未映射用户在 callback 阶段拒绝：PASS。
- 禁用用户无法取得授权码：PASS。
- state 一次性消费、nonce、JWKS、错误 audience、注销/会话失效：单元与集成测试 PASS。
- 预生产已有 LOCAL bearer 返回 401，`local_bearer_accepted=false`；不只关闭登录端点，也关闭本地令牌入口。
- 伪造 Token、错误 issuer/audience、过期、跨 tenant/workspace、前端伪造身份的成功数均为 0。

证据见 `evidence/p4_oidc_acceptance.json`。浏览器测试使用仅存在于运行卷的隔离验收账号材料，脚本执行后清除进程环境变量，输出不包含密码、Token、Cookie 或私钥。

## 安全影响与限制

OIDC 会话存于受认证 Redis，state 使用 `GETDEL`，注销删除本地会话并尝试上游注销；Redis 不可用时 fail-closed。真实企业 IdP 的 metadata、管理员审批和证书链仍未提供，因此 `ENTERPRISE_IDP_APPROVED=false`。这不否定隔离标准协议闭环，但阻止正式生产授权。

回滚为撤回 P4 OIDC 路由和映射提交并保持 `LOCAL_AUTH_ENABLED=false`；不得以重新开启本地认证作为预生产降级方案。
