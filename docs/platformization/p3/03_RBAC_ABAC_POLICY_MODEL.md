# RBAC 与 ABAC Policy Model

## 数据模型

RBAC 由 `governance_role`、`governance_permission`、`governance_role_permission` 和 `governance_binding` 组成；ABAC 规则由版本化 `governance_policy` 承载。初始化基线为 3 个角色、28 个权限、50 个角色权限关系、1 个策略和 3 个绑定。

权限覆盖数据源、数据集、指标、RAG 文档、Memory 查看/确认/纠正/删除、Skill 查看/执行、Procedure 审核/激活/停用/回滚、审计、CredentialReference、Legal Hold、Retention 和发布/回滚。

## 判定顺序

1. 从服务端 `IdentityContext` 获取主体与租户作用域。
2. 校验主体、组、角色和绑定状态及有效期。
3. RBAC 确认基础 action permission。
4. ABAC 校验 tenant、workspace、scenario、resource owner、数据分类和 environment。
5. 显式 DENY、作用域不匹配、策略未发布或未匹配均拒绝。
6. 拒绝写入审计，并按规则聚合站内告警。

统一授权服务已接入 Orchestrator、Memory、Skill/Procedure、RAG、SQL Guard 和 SQLBot 数据源绑定路径。业务层原有行级作用域与 Query Guard 继续保留，形成叠加防线。

## 负向验收

- 跨租户成功数：0。
- 跨用户成功数：0。
- 跨场景成功数：0。
- 模型提权成功数：0。
- 前端伪造 tenant/user 成功数：0。
- 未匹配 Policy 的授权成功数：0。

以上为本地隔离测试结果，不代表真实企业身份系统已经投产。
