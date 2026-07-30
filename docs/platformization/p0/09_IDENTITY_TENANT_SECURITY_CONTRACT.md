# Identity / Tenant / Security Contract v0.1

状态：**目标合同已冻结；当前为单客户私有部署 RBAC，不是多租户平台**。

## 身份上下文

`IdentityContext` 必须包含 subject_id、tenant_id、org_id、workspace_id、roles、groups、data_scopes、auth_strength、issued_at 和 request_id。

## 强制规则

- tenant/org/workspace 是服务端从可信令牌解析的安全边界，不能接受客户端任意覆盖。
- 权限过滤在数据查询、知识召回和记忆加载之前执行。
- 默认拒绝；资源权限、行级范围、列掩码和导出权限分别判断。
- 服务账户与人类账户分离；查询执行账户使用数据库只读角色。
- 支持 OIDC/OAuth2 的目标接口，但 P0 不声明已实现 SSO。
- 秘密只由秘密管理器引用，禁止进入仓库、日志、数据库明文字段和前端。
- 审计事件含主体、租户、工作区、动作、对象、结果、原因、request_id、run_id 和时间。
- 生产配置必须 fail closed；HTTPS、强密钥、PostgreSQL、Redis、受限 host、禁用 demo bootstrap 为硬门禁。

## 当前状态

已实现 JWT、PBKDF2、三个角色、区域过滤、审计和生产配置负向校验。未实现 tenant/org/workspace、SSO、列掩码、通用行策略、限流/熔断和独立只读数据库角色证明。

## 安全事件

本轮输入蓝图包含疑似明文密码/API key。它未被复制到仓库；所有相关凭据必须在原系统撤销、轮换并检查访问日志。轮换完成前 P0 安全验收不得标记 PASS。

