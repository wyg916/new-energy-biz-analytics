# SQLBot 4.1 验收报告

## 状态

`PARTIAL`。平台侧实现、策略链、路由合同、自动回退、DATA-4.1 当前 PostgreSQL
只读查询和 368 项回归均通过；SQLBot v1.8.0 历史隔离 Runtime 本轮未恢复到
HTTP Ready，真实模型推理、真实 Shadow 一致性和真实流量 Canary 尚未验证。

## 工作树与基线

- 工作树：`E:\新能源企业经营分析智能平台-sqlbot-41`
- 分支：`codex/sqlbot-open-nl2sql-41`
- 开始 HEAD：`75160df433bbf9273e10a87bae6a7aef29af9744`
- 基线标签：`data41-baseline-20260808`

## 测试结果

| 验收项 | 结果 | 数量 |
|---|---:|---:|
| SQLBot 4.1 定向单测/安全负向/路由 | PASS | 75 |
| 双引擎 NL2SQL Golden 合同 | PASS | 100/100 |
| 新增安全负向 | PASS | 16/16 |
| 原 PostgreSQL 回归 | PASS | 368/368 |
| DATA-4.1 PostgreSQL 聚焦复测 | PASS | 5/5 |
| 新增内容 Secret Scan | PASS | 0 finding |
| 当前 DATA-4.1 PostgreSQL 只读查询 | PASS | 2 run + 10 bounded rows |
| SQLBot 实时模型推理 | BLOCKED | Runtime HTTP 未 Ready |

第一次 368 项运行是 366/368，两个失败均由 Windows 将已发布公开源快照检出为
CRLF 引起。新增 `.gitattributes` 固定两个快照为 LF，清单哈希恢复一致；随后
DATA-4.1 5/5 聚焦复测和完整 368/368 均通过。失败证据被保留，没有覆盖或删除。

## 执行命令

```text
docker build -f backend/Dockerfile -t renewable-sqlbot41-api:test .
pytest -m no_db tests/test_sqlbot_open_nl2sql_41.py ...
python scripts/run_dual_engine_eval.py --source tests/evaluation/nl2sql_dual_engine_v1.json
python scripts/run_p5a_full_postgres_regression.py ... --expected-tests 368
python scripts/run_p5a_full_postgres_regression.py ... --expected-tests 5 --data41-rerun
psql ... -c "BEGIN READ ONLY; SET LOCAL statement_timeout = 5000; ... LIMIT 5; ROLLBACK;"
python scripts/finalize_sqlbot41_evidence.py ...
```

命令中的数据库密码来自既有隔离 runtime 文件引用，未输出、未写入证据、未提交。

## Shadow / Canary / Stable / Fallback

- Shadow：主结果固定来自 Deterministic Engine；SQLBot 只比较和记录；
- Canary 5%：稳定用户分桶合同通过，未命中进入确定性控制组；
- Canary 20%：稳定用户分桶合同通过；
- Scoped Stable：tenant/workspace/user/scenario allowlist 合同通过；
- Fallback：Runtime 错误、超时、策略拒绝、未知失败和作用域外请求自动回退；
- 真实性限制：以上是平台路由合同测试，不是本轮真实模型流量结果。

## 修改范围

- SQLBot：Schema Catalog、Retrieval、Query Understanding、Policy、只读执行、结果校验；
- Router：分阶段策略、稳定分桶、自动回退；
- ChatBI 场景服务：动态识别核心/开放查询，注入平台只读执行器；
- Tests：黄金合同复用、新增安全负向和阶段路由验证；
- Evidence/Docs：机器可读 JUnit、JSON、哈希清单和本报告；
- 根目录例外：仅 `.gitattributes`，用于固定已发布快照字节哈希。

未修改 `AGENTS.md`、`frontend/src`、`一键启动.bat`、Compose、公共依赖或公共 API
schema；无数据库迁移。

## 风险与限制

- 外部 SQLBot Runtime 未 Ready，真实模型准确率、延迟、Token 和 Shadow 一致性为空；
- Scoped Stable 仅表示受控作用域模式存在，不代表全量开放或生产准入；
- 数据库实时验证使用当前本地 DATA-4.1 开源衍生数据，不是客户生产数据；
- 全表聚合在 5 秒内被取消，说明成本边界生效，也说明开放查询必须保持有界。

## 回滚与下一步

回滚本工作包 Git 提交，或立即关闭 `SQLBOT_ENGINE_ENABLED` 并设置
`QUERY_ENGINE_MODE=DETERMINISTIC_ONLY`。数据库无迁移、无数据回滚动作。

允许代码 Integration，但必须保持 SQLBot disabled 或 Shadow；不允许真实 Canary、
Scoped Stable 流量或生产发布，直到独立 SQLBot Runtime 恢复并完成真实黄金集与
Shadow 门禁。
