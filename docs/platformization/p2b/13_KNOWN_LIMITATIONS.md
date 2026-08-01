# 已知限制

## Conditional / Pending

- SQLBot 质量仍须以本轮真实 10/30/20 结果判定。当前 P2A API 容器未导出所需
  `P2A_SQLBOT_USERNAME/PASSWORD` CredentialReference，三套脚本均在外部请求前
  fail-closed，实际执行用例和外部请求均为 0；未经额外授权不得探查本地秘密文件。
  因此 SQLBot 保持 Shadow，Canary 禁用。
- SQLBot v1.8.0 的 MCP 调用在上游执行后返回 SQL 与结果；平台可以对返回 SQL 做 AST
  Guard 和 LIMIT 规范化，但不能把该上游接口改造成执行前审批。超量结果会明确拒绝，
  不进入主答案。
- Working Memory 的 Redis 降级不丢 PostgreSQL 审计，但降级期间无法提供完整跨轮继承。
- 语义检索是派生能力；当前最小闭环以结构化/关键词检索为主，不是完整知识图谱。
- Legal Hold 已预留合同和字段，企业法务策略与实际保留期限仍需部署阶段配置。
- UI 是自有 React 管理面；企业 SSO、生产密钥、真实客户数据和外部系统执行均未接入。
- 并发 worktree 存在未推送的 `0015_frontend_data_lineage`。未来合并必须显式创建或解决
  Alembic merge head，当前 P2B 分支不能静默选择。
- 80 条 Memory/Skill 固定行为评测中的 P50/P95 是隔离测试观察值，不是生产负载测试；
  企业容量、长期 Redis/索引增长和真实 Token 成本仍需 P3 压测与部署验证。

## 禁用项

多 Agent、自由 SQL、自动激活程序规则、自动邮件/工单、生产 Canary、生产发布、真实
企业连接和第三业务场景均保持禁用。所有展示仍为固定种子模拟数据。
