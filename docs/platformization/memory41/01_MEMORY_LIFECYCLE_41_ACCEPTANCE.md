# Memory 4.1 生命周期与自动遗忘验收

## 结论

**PASS（本地候选实现）**。该结论只覆盖本工作树内隔离 PostgreSQL、Redis、SQLite 故障注入和固定评测，不代表生产准入、真实客户运行或真实对象/向量后端验收。

## 工作树与范围

- 工作树：`E:\新能源企业经营分析智能平台-memory-41`
- 分支：`codex/memory-lifecycle-41`
- 开始 HEAD / 唯一基线：`75160df433bbf9273e10a87bae6a7aef29af9744`
- 基线标签：`data41-baseline-20260808`
- 未合并 RAG、SQLBot 或其他分支；未修改前端、根一键启动、Compose 或依赖锁。

## 验收结果

| 项目 | 结果 | 证据 |
|---|---:|---|
| Migration | PASS | PostgreSQL `data_0001 -> memory_41_0001 -> data_0001 -> memory_41_0001` |
| Scheduler / lifecycle job | PASS | 幂等时间桶、任务领取、5 分钟 stale lease 回收、状态与指标测试 |
| TTL / decay / recall | PASS | `REDUCED_RANK/COLD/ARCHIVED/REVOKED` 与 recall signal |
| Forget job | PASS | 单条删除、用户清除、请求进程故障后 Worker 接管 |
| Legal Hold | PASS | 记录级与治理 Legal Hold 在生命周期/删除前阻断 |
| Outbox / retry | PASS | 持久 Outbox、指数退避、故障注入、`autoflush=False` 验证 |
| Cross-store delete | PASS/PARTIAL | PostgreSQL、Redis 实后端通过；向量/对象为适配接口和内存故障注入，当前无实际后端配置 |
| Delete verification | PASS | PostgreSQL/Redis `VERIFIED`；未配置后端显式 `NOT_CONFIGURED` |
| Memory 固定评测 | PASS | 40/40 |
| Skill 固定评测 | PASS | 40/40 |
| 生命周期固定评测 | PASS | 12/12 |
| 生命周期专项 | PASS | 28/28 |
| Memory/Skill 相关回归 | PASS | 95/95 |
| PostgreSQL API/会话集成 | PASS | 4/4 |
| Redis 集成 | PASS | 1/1 |

机器可读汇总：`evidence/memory41-acceptance-summary.json`。

## 执行命令

```powershell
python scripts/verify_memory41_migration_cycle.py --database-url <isolated-postgresql-url> --output docs/platformization/memory41/evidence/memory41-migration-cycle.json
python -m pytest tests/test_memory_lifecycle_41.py tests/test_memory_lifecycle_api_41.py tests/test_memory_lifecycle_evaluation_41.py tests/test_memory_governance_lifecycle.py --junitxml=../docs/platformization/memory41/evidence/memory41-lifecycle.xml -q
python -m pytest tests/test_memory_evaluation_report.py tests/test_memory_evaluation_expansion.py tests/test_skill_evaluation_expansion.py tests/test_memory_scope_authorization.py tests/test_memory_working_semantic_episodic.py tests/test_memory_skill_orchestration_api.py tests/test_initial_operational_skills.py --junitxml=../docs/platformization/memory41/evidence/memory41-memory-skill.xml -q
python -m pytest tests/test_memory_lifecycle_postgres_41.py tests/test_memory.py --junitxml=../docs/platformization/memory41/evidence/memory41-postgres.xml -q
python -m pytest tests/test_memory_lifecycle_redis_41.py --junitxml=../docs/platformization/memory41/evidence/memory41-redis.xml -q
python scripts/build_memory41_acceptance.py
python -m compileall -q backend/app/memory backend/app/main.py backend/app/core/config.py scripts/verify_memory41_migration_cycle.py scripts/build_memory41_acceptance.py
git diff --check
```

## 数据库与安全影响

- 数据库新增 3 表、3 列和相应索引，迁移可回滚；
- 用户删除会匿名化 PostgreSQL 正文并清理 Redis/已配置派生存储；该业务删除本身不可由 schema downgrade 恢复；
- 管理端仅可读，要求 `analyst_admin`，不返回正文、原始 memory ID 或 user ID；
- 删除验证保存资源摘要和最小状态，不保存被删正文；
- 权限硬过滤仍在召回查询前，当前数据库事实与明确指令仍高于记忆。

## 限制与风险

- 当前仓库没有实际启用的向量索引或对象存储 Memory 后端，因此只验证了接口、Outbox、故障注入和 `NOT_CONFIGURED` 真相边界；接入真实后端时必须提供 `delete/exists` 并重新跑集成；
- Scheduler 是模块化单体内的进程内循环；数据库任务/lease 支持多实例接管，但正式多副本部署仍需容量和竞争压测；
- 测试发现基线迁移库上的 SQLBot 语义视图会阻止通用 `Base.metadata.drop_all()`；迁移循环在该库通过，API 集成改用同一临时容器内独立空白数据库，未弱化断言；
- Starlette 提示现有 `httpx` TestClient 弃用告警，不影响本工作包结果；
- Integration 合并后必须同步部署环境的 `EXPECTED_DATABASE_REVISION=memory_41_0001`，本工作包遵守约束未修改最终 Compose/根启动器。

## 回滚与 Integration

- 回滚：停 Scheduler，确认无 `RUNNING` 任务，执行 `alembic downgrade data_0001`，再回滚本工作包 Git commit；
- 不可恢复项：已按用户指令删除的正文和外部派生内容；
- **允许进入 Integration：是**，前提是 Integration 负责人处理期望迁移版本并保留真实向量/对象后端为独立准入项；不得由此宣称生产准入。
