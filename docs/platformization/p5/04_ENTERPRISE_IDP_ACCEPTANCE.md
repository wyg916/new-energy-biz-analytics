# P5 企业 IdP 验收

状态：`CONDITIONAL`。

已实现无 Secret 的 `p5-enterprise-idp-v1` 配置模板及离线 Metadata 校验器，覆盖唯一 issuer、HTTPS 且禁止 URL 内嵌凭据、Authorization Code、PKCE S256、RS256、claims 完整映射、禁用/离职用户值、session revocation、clock skew 和有界 JWKS cache。现有 OIDC 运行实现继续执行精确 audience/issuer 校验，并在未知 `kid` 时刷新 JWKS；错误配置 fail-closed。

模板：`deploy/production-acceptance/enterprise-idp.template.json`。真实 client secret 不属于模板，也不得进入 Git。配置测试 6 项通过。

用户未提供真实企业测试租户、授权端点或授权身份，因此没有发起外部 IdP 请求，未执行真实用户禁用、离职撤权、JWKS 轮换、session revocation 或切换演练。Keycloak P4 结果没有被当作企业 IdP 已接入证据。

切换步骤：在授权 Secret Provider 写入 client credential reference；校验 discovery metadata；用测试用户验证 claims 与作用域；验证禁用、撤权、未知 kid 和时钟偏移；仅在验收记录签署后更新 provider 配置。回滚时恢复上一 provider 配置版本、撤回新引用并强制终止新 provider session；本地认证不得在生产自动启用。
