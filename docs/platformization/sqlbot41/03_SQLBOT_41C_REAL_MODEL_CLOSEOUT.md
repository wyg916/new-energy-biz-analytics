# SQLBot / NL2SQL 4.1C 真实模型收口

结论：**PARTIAL，Integration NOT_ALLOWED**。

平台已使用官方 SQLBot v1.10.0 镜像和真实 DeepSeek 模型完成 20 条 Runtime
Smoke。CredentialReference、场景只读账号与安全边界通过，但真实生成质量和 P95
时延未达到 Shadow 准入阈值，因此没有执行 Shadow50、Canary 5%、Canary 20% 或
Scoped Stable。

## 实测结果

- Runtime response：100%；查询类 SQL generated：81.25%。
- Query Guard pass：62.5%；平台只读执行：62.5%。
- Semantic outcome accuracy：65%；拒答准确率：75%。
- P50：12.761 秒；P95：25.908 秒；最大 P95 阶段为模型生成。
- 一次 v1.10 容器重启因内置 PostgreSQL crash recovery/fsync 约 9 分钟后才恢复
  healthy，超过 8 分钟观察窗，是当前运行恢复风险。
- 危险 SQL、越权 SQL、PII 与跨场景 SQL实际放行均为 0。
- 20 条中 3 条查询被模型主动拒答，3 条 Repair 后仍被 Guard 拒绝，1 条应澄清问题错误生成 SQL。

这些数字来自 `evidence/real-runtime-smoke-20.json`，不是 Mock、fixture、预置
Golden SQL 或 SQLBot 上游执行结果。模型输出只用于生成候选 SQL；所有可执行 SQL
必须重新经过 Parser/AST、Schema、Join、Permission/PII、Cost/timeout/row limit、
Query Guard，并由平台场景只读账号执行，再通过 Result Guard 和 Answer Guard。

## Credential 与数据库

Runtime 账号已由 CredentialReference 解析并验证，缺少/过期引用会 fail-closed，
不会回退到未登记 ENV。为满足 SQLBot 本地密码格式，平台使用域隔离 HMAC 派生，
证据不保存引用秘密、运行时密码或 Token。

当前 DATA-4.1 只读验证实查 charging_ops 300,026 行、sales_ops 63,665 行。没有数据库
迁移或不可逆写入；回归使用隔离临时 PostgreSQL。数据是本地开源衍生/模拟验收数据，
不是客户生产数据。

## 回归

- SQLBot/NL2SQL、Parser/Policy、安全负向与路由定向：80/80 PASS。
- 固定 Golden 合同：100/100 PASS；危险 SQL 与权限攻击成功为 0。
- PostgreSQL 最终全量：372/372 PASS，覆盖原 368 项并包含本工作包新增 4 项；
  首轮资源竞争超时及 23/23 隔离纠正复测证据均保留。
- DATA-4.1 PostgreSQL 聚焦：5/5 PASS。

## Shadow 与回滚

`evidence/real-shadow.json` 为 `NOT_ELIGIBLE`，执行数为 0。Deterministic Engine 保留为
高安全主路径与 fallback；未新增自由 SQL 管理入口，也未开放生产或客户流量。

代码回滚使用 `git revert <4.1C commit>`。运行时可停止隔离的
`renewable-sqlbot-41c-runtime-v1-10-0`，平台继续保持 Deterministic-only。凭据或数据库
角色的删除需要另行明确授权，本工作包未执行删除。
