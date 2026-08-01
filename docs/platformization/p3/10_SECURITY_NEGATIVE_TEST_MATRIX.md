# 安全负向测试矩阵

| 控制 | 负向输入/状态 | 期望结果 | 实际结果 |
| --- | --- | --- | --- |
| 可信身份 | 伪造 tenant/user/role Header | 服务端身份不被覆盖 | PASS，成功数 0 |
| OIDC | 错误签名、issuer、audience、过期或未映射主体 | 拒绝认证 | PASS |
| RBAC | 主体没有 action permission | 默认拒绝并审计 | PASS |
| ABAC tenant | 请求其他 tenant 资源 | 拒绝并告警 | PASS，成功数 0 |
| ABAC workspace/user | 请求其他 workspace 或 owner 资源 | 拒绝 | PASS，成功数 0 |
| ABAC scenario | 跨场景请求 | 拒绝 | PASS，成功数 0 |
| 模型边界 | 模型文本要求提权 | 不改变服务端权限 | PASS，成功数 0 |
| CredentialReference | 缺失 provider 或 Secret | 外部请求前 fail-closed | PASS |
| CredentialReference | DISABLED/REVOKED 或 action 不允许 | 拒绝并审计 | PASS |
| Secret 输出 | 日志、API、审计导出 | 不出现 Secret 值 | PASS，泄漏数 0 |
| Legal Hold | ACTIVE Hold 下删除 | 阻止并审计 | PASS，成功数 0 |
| Legal Hold | 普通用户解除 | 拒绝 | PASS，成功数 0 |
| Retention | 尚在最严格保留期 | 阻止删除 | PASS |
| Procedure | 未审核直接激活 | 拒绝并告警 | PASS，成功数 0 |
| Policy/Release | 未审核直接 ACTIVE | 拒绝并审计 | PASS，成功数 0 |
| Governance Audit | 普通用户 UPDATE/DELETE | 拒绝 | PASS，成功数 0 |
| SQL Guard | 写入、多语句、危险函数、越权 source | 拒绝 | PASS，15/15 |
| SQLBot | 引擎不可用 | 不影响确定性主答案 | PASS |
| RAG | 索引不可用或无文档权限 | 受控降级、无伪造引用 | PASS |
| 健康检查 | PostgreSQL/Redis 不可用 | liveness 保持、readiness 503 | PASS |

测试使用隔离数据库、模拟身份和固定种子模拟业务数据；未读取真实企业凭据或生产数据。
