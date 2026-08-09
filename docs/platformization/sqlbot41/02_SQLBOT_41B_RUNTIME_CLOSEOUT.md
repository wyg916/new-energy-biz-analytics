# SQLBot / NL2SQL 4.1B 结案

结论：**PARTIAL，不允许 Integration**。

代码、离线 Golden、安全负向、DATA-4.1 PostgreSQL 回归与受控路由合同已通过；真实 SQLBot 模型 Smoke 为 0/10，且 CredentialReference 与运行时账号尚未同步。因此 Shadow 不具备晋级条件，Canary 5%、Canary 20% 和 Scoped Stable 均未执行，不能宣称 PASS。

## 实现边界

- SQLBot v1.8.0 只经 `/api/v1/mcp/mcp_generate_sql` 生成 SQL，上游不执行 SQL。
- 生成结果必须依次经过 Parser/AST、Schema、Join、Permission/PII、Cost/timeout/row limit、Query Guard，再由平台场景隔离只读角色执行，随后经过 Result Guard 与 Answer Guard。
- 仅允许当前场景语义 Schema；允许的限定符会在 AST 中剥离，其他 Schema/Catalog 一律拒绝。
- 场景专用只读连接缺失即 fail-closed，不回退到通用数据库连接。
- Deterministic Engine 保留为高安全路径与自动 fallback；未新增自由 SQL 或管理员实验入口。

## 验收结果

| 门禁 | 结果 | 证据 |
|---|---:|---|
| SQLBot/NL2SQL 定向测试 | PASS，74/74 | `evidence/sqlbot41b-targeted-current.xml` |
| 离线 Golden 合同 | PASS，100/100 | `evidence/sqlbot41b-golden-contract-100.json` |
| 安全负向 | PASS，危险 SQL 成功 0、权限攻击成功 0 | 同上 |
| 修正后 PostgreSQL 全量回归 | PASS，368/368 | `evidence/sqlbot41b-postgres-full-final.json` |
| DATA-4.1 定向 PostgreSQL | PASS，5/5 | `evidence/sqlbot41b-postgres-data41-rerun.json` |
| 真实 SQLBot 模型 Smoke | FAIL，0/10 | `evidence/sqlbot41b-live-smoke-env-acceptance.json` |
| Shadow | NOT_ELIGIBLE | 真实 Smoke 未通过 |
| Canary 5% | NOT_EXECUTED | 未越过 Shadow 门禁 |
| Canary 20% | NOT_EXECUTED | 未越过 5% 门禁 |
| Scoped Stable | NOT_EXECUTED | 未越过 20% 门禁 |
| 自动回退 | PASS_CONTRACT_ONLY | 定向路由测试，非真实 Canary 流量 |

真实模型共请求 10 次，6 次生成 SQL；当时的 Guard 对显式场景 Schema 采取拒绝策略，全部安全停止，SQLBot 上游执行数和平台执行数均为 0。随后已将策略收紧为“仅当前场景 Schema 可规范化”，但当前 DATA-4.1 运行组被外部集成任务替换，未获得策略修正后的成功端到端查询证据。环境 allowlist 只用于验收；正式 CredentialReference 认证仍不匹配 SQLBot 账号，Vault 同步未成功且未改写现有 Secret。

## 数据库与安全影响

- 当前 DATA-4.1 数据库曾创建 `sqlbot_charging_readonly`、`sqlbot_sales_readonly`、`sqlbot_platform_charging_readonly`、`sqlbot_platform_sales_readonly` 四个角色；均为非超级用户、只读事务、3 连接上限、约 3 秒 statement timeout，并按场景隔离 Schema。
- 只读验证：危险写入成功 0、跨场景成功 0、`public` 基表读取成功 0；关系数 charging 3、sales 6。
- 运行凭据只写入未跟踪 runtime volume，未提交或输出 Secret。无迁移、无不可逆数据库操作、无生产切流。

## 修改范围与非目标

修改集中于 `backend/app/query_engines/sqlbot`、SQLBot 部署适配、评测/回归脚本、相关测试与证据；另对 `backend/app/core/config.py` 增加两个场景只读连接配置。未修改 `AGENTS.md`、`frontend/src`、根一键启动脚本、最终 Compose、公共 API schema 或公共依赖；未合并 RAG/Memory 分支。

## 限制、风险与后续门禁

主要阻塞是 CredentialReference 账号不同步、模型时延高且生成质量未达到真实 Guard→只读执行闭环。DeepSeek 实测 p50 89.409 秒、p95 90.370 秒，6 次可观测 token 总量 64,597。只有在受控 CredentialReference 修复、重新完成真实 Golden/安全负向、成功的 Guard→平台只读执行、Shadow 自动回退实证后，才可重新评估 Canary 5%；之后必须逐级满足门禁，不得跳级。

## 回滚

代码使用 `git revert <本工作包提交>`。运行时可停止 `renewable-sqlbot-41b-runtime-v1-8-0` 并保留 Deterministic Engine。数据库回滚需在明确授权后终止相关会话、撤销并删除上述四个专用角色，同时删除未跟踪 runtime volume 中的 SQLBot 4.1B 凭据文件；本工作包未执行这些回滚操作。

机器可读总证据：`evidence/sqlbot41b-closeout.json`。
