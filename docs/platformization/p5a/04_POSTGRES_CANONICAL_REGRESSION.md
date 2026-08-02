# P5A PostgreSQL 权威回归

核对日期：2026-08-02。结论：本地可实现的 PostgreSQL 门禁通过。数据均为固定种子模拟数据，范围为 2025-01-01 至 2026-06-30；主库 revision 为 `p5_0001`，包含 charging sessions 300000、sales orders 50000、sales order items 82514。

## 范围与环境

- 生产验收主栈使用 `renewable-p5a-postgres:16.14`，镜像 ID `sha256:486298eaa6cbd4830f8d1ae199e6dc9f33cee75a6bc178b0ee2d34c94b3041e3`。
- 全量 pytest 使用同一 PostgreSQL 16.14 镜像、同一 Docker 网络和同一 API 依赖镜像；为规避 Docker Desktop 持久卷的 `DataFileImmediateSync` 放大，四个明确命名的测试库使用无持久卷的 tmpfs 数据目录。
- 测试数据库均为一次性隔离库。完成后容器随 `--rm` 移除；主 P5A 数据库、卷、备份均未删除。
- Memory/Skill 的固定 Oracle 按冻结合同使用测试内部的内存数据库验证 40+40 分布；没有把它们伪称为对 PostgreSQL 发出 SQL。涉及持久化的主链、RAG、API、治理和全量集成测试均连接 PostgreSQL。

## 全量 pytest

四批收集总数为 353，初次最终批次为 351 通过、2 失败、0 error、0 skip。两项失败分别是 Active Platform 和 Multi Scenario Chat，它们都因测试运行器错误地显式注入 `QUERY_ENGINE_MODE=DETERMINISTIC_ONLY`，使测试态无法按合同自动解析为 SHADOW。移除该环境变量后，两项保持原断言定向重跑 1/1 + 1/1 通过；没有修改应用代码或测试断言。有效结论为 353/353。

更早的首轮运行还继承了 P5A 的 OIDC-only、release version 和目录布局，产生 403 与文件缺失；对应 JUnit 作为运行器诊断证据保留，不作为产品失败结论。最终运行使用最小测试环境和只读仓库挂载。

## 固定评测与对账

| 项目 | 实际结果 | 真实性边界 |
| --- | ---: | --- |
| Deterministic | 40/40 | Query Plan 与安全行为 |
| charging_ops 指标对账 | 15/15 | differences `{}` |
| sales_ops 指标对账 | 12/12 | differences `{}` |
| DQ | 20/20 | 300000 sessions，失败规则 0 |
| Memory Oracle | 40/40 | 冻结分布与安全 Oracle；测试内部内存库 |
| Skill Oracle | 40/40 | 冻结分布与安全 Oracle；测试内部内存库 |
| Memory expansion | 8/8 pytest nodes | working/episodic 行为扩展 |
| Skill expansion | 35/35 pytest nodes | 五个正式 Skill；业务 Oracle 仍为 40 |
| RAG keyword | 60/60 | MRR 0.9667，Recall@10 0.8936，越权/注入生效 0 |
| Response Composer | 7/7 | 7 个 profile |
| Query Security | 15/15 | 危险 SQL 与 Guard 负向 |
| SQLBot offline | 46/46 effective | 初次 45/46；独立导入在并行满载时 30 秒超时，低负载原断言重跑 1/1；不代表外部运行时 |

## 迁移和回滚

专用数据库 `p5a_migration_verify` 完成 `base → p5_0001 → p4_0001 → p5_0001`。观察到的回滚 revision 为 `p4_0001`，再次升级回唯一 head `p5_0001`；专用库随后移除，现有卷删除数为 0。

## 证据

- 汇总：`evidence/p5a-postgres-regression.json`
- 迁移：`evidence/p5a-migration-cycle.json`
- 全量：`evidence/postgres-full-pytest-final-batch-1.xml` 至 `batch-4.xml`
- 修复重跑：`evidence/postgres-active-platform-rerun.xml`、`evidence/postgres-multiscenario-rerun.xml`
- 固定评测：`evidence/postgres-memory-skill-oracle-40-40.xml`、`evidence/postgres-fixed-rag-60.xml`、`evidence/postgres-fixed-memory-response-query.xml`、`evidence/postgres-fixed-skill-40.xml`、`evidence/postgres-fixed-sqlbot-46.xml`、`evidence/postgres-sqlbot-import-rerun.xml`
- Deterministic 明细：`evidence/chatbi-eval-40.json`

限制：本结论只证明当前本机隔离 P5A 标准 PostgreSQL 回归，不代表企业生产容量、生产数据或生产发布授权。
