# P2A Runtime Closeout 范围

更新时间：2026-07-31

## 1. 工作包与基线

- 工作包：`P2A-RUNTIME-CLOSEOUT`
- 独立 Worktree：`E:\新能源企业经营分析智能平台-p2a-runtime`
- 分支：`feat/p2a-runtime-closeout`
- 基线提交：`2117a875713b735d414d821bdb63b033870d9d56`
- 数据性质：固定随机种子的模拟数据，时间范围 `2025-01-01` 至
  `2026-06-30`
- `P0_EXTERNAL_SECURITY = PENDING`
- 远端核验：2026-07-31 再次执行 `git fetch origin --prune` 成功；关闭分支以
  远端基线 `2117a875713b735d414d821bdb63b033870d9d56` 为起点，未改写历史

原工作区的 Dashboard、指标、前端、E2E、未跟踪 `0015` 和四份用户源文档
不属于本工作包。本工作包不读取、不修改、不删除、不暂存、不提交这些内容，
也不将四份用户源文档摄取进知识库。

## 2. 目标

1. 发现并验证已声明的 OpenAI-compatible 模型合同；
2. 以 SQLBot v1.8.0 实际代码和接口为准配置模型和两个只读 Datasource；
3. 先运行 10 条 Smoke，再运行 100 条实际 Golden Set；
4. 完成 charging_ops、sales_ops 各 10 条真实 Shadow；
5. 验证会话隔离、只读、权限、跨场景、超时、熔断和故障降级；
6. 有界检查 pgvector、SBOM 和镜像漏洞状态；
7. 保持 DeterministicEngine 为用户主答案，只有全部阈值满足时才判定 Canary
   可用。

## 3. 非目标

- 不重做 P1A、P1B 或已完成的 P2A RAG、Response Composer 和双场景底座；
- 不修改冻结的 charging_ops 15 项和 sales_ops 12 项指标；
- 不新增第三场景、长期 Agent Memory、自由 SQL 或生产 Canary；
- 不连接真实企业业务系统或真实业务数据；
- 原则上不新增 Alembic 迁移，不接触原工作区并发 `0015`；
- 不把 Mock、离线合同或关键词检索结果表述为 live 模型、执行准确率或混合检索。

## 4. 当前现场事实

| 项目 | 当前证据 | 初始状态 |
|---|---|---|
| SQLBot 容器 | v1.8.0，healthy，restart_count=0，HTTP 200 | PASS |
| 原运行数据库 | `0015 (head)`，来自原工作区并发链路 | 与基线 `0014` 冲突，隔离处理 |
| 独立验收数据库 | `0014 (head)`，`alembic check` 无新增操作 | PASS |
| Kimi 候选 | 合同和运行时引用完整；DNS PASS；`/models` HTTP 401 | PROVIDER_AUTHENTICATION_FAILED |
| Mimo 候选 | 合同和运行时引用完整；DNS PASS；Bearer/`api-key` 均 HTTP 401 | PROVIDER_AUTHENTICATION_FAILED |
| DeepSeek 候选 | 合同和运行时引用完整；DNS PASS；`/models` HTTP 401 | PROVIDER_AUTHENTICATION_FAILED |
| SQLBot live 查询 | 尚无 live provider，不能执行真实 NL2SQL | PENDING |
| 真实 Shadow | 尚无 live SQLBot 结果 | NOT_PASS |
| pgvector | 历史证据为当前 PostgreSQL 镜像不可用 | 待本轮有界复核 |
| SBOM/漏洞扫描 | 历史扫描超时 | 待本轮有界复核 |

模型验证只输出 Provider、非秘密合同字段、模型列表、状态码、错误码、时延和
usage；禁止输出任何完整 Key、Token、密码、响应正文或内部认证值。四类运行时
引用已经完整，当前阻断来自官方接口认证失败，不再要求重复提供配置字段。具体
Secret 只能在不跟踪运行时环境中注入。

## 5. 安全与真实性门禁

- 新增明文秘密数必须为 0；
- 危险、越权、跨场景 SQL 成功数必须均为 0；
- SQLBot 故障导致 DeterministicEngine 主答案失败数必须为 0；
- 未授权模型上下文发送数必须为 0；
- LLM 生成的 SQL 必须通过 Query Guard，且只能由独立只读边界执行；
- 未达到运行阈值时固定
  `SQLBOT_CANARY_ELIGIBLE=false`、`QUERY_ENGINE_MODE=SHADOW`；
- 所有验收材料必须区分 live、Mock、离线合同、执行评测、Shadow、Pending 和
  外部待办。

## 6. 验收与回滚

本轮分别判定 MODEL_RUNTIME、SQLBOT_DATASOURCE_RUNTIME、
SQLBOT_QUERY_RUNTIME、SQLBOT_GOLDEN_RUNTIME、SQLBOT_SHADOW、
SQLBOT_CANARY、RAG_VECTOR、SBOM_SCAN 和 P2A_RUNTIME_CLOSEOUT。

即时应用回滚保持：

```text
SQLBOT_ENGINE_ENABLED=false
SQLBOT_RUNTIME_VERIFIED=false
CHATBI_READONLY_EXECUTION_ENABLED=false
QUERY_ENGINE_MODE=DETERMINISTIC_ONLY
```

代码和文档按本工作包独立提交执行 `git revert <commit>` 回滚；不得删除主平台
或 SQLBot 数据卷。
