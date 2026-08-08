# Memory 4.1 生命周期与自动遗忘实施说明

## 结论

本工作包在既有 `MemoryLifecycleService` 与 `MemoryDeletionService` 上增量实现持续运行、可审计、可重试的生命周期链路。它不新增自动学习、跨会话无约束召回或未经批准的长期偏好能力。

实现链路：

`Scheduler -> lifecycle task -> TTL/expiration -> importance decay -> recall signal -> REDUCED_RANK/COLD/ARCHIVED/REVOKED/DELETED -> Legal Hold -> outbox -> retry -> cross-store delete -> delete verification`

## 数据库与迁移

迁移 `memory_41_0001` 以 `data_0001` 为唯一前置版本，新增：

- `memory_lifecycle_task`：任务类型、状态、幂等键、尝试次数、最大重试、下次重试、锁、失败原因和结果；
- `memory_lifecycle_outbox`：按任务、目标存储、操作和资源唯一投递；
- `memory_delete_verification`：按任务与存储记录删除后不可召回验证；
- `memory_record.recall_count`、`last_recalled_at`、`lifecycle_transition_at`。

迁移支持 downgrade 到 `data_0001`，并已在隔离 SQLite 与 PostgreSQL 执行升级、回滚、再升级。

## 调度、Worker 与状态

- 非测试环境默认启动进程内异步 Scheduler；同步数据库工作放入线程执行，应用退出时停止并等待任务结束；
- 每个场景按分钟时间桶生成幂等维护任务；Worker 使用数据库任务状态与 `next_attempt_at` 领取任务；
- 任务状态为 `PENDING/RUNNING/RETRY/COMPLETED/BLOCKED/FAILED`；
- Outbox 状态为 `PENDING/RUNNING/RETRY/COMPLETED/FAILED`，指数退避上限 300 秒，默认最多 5 次；
- Worker 可在请求进程完成任务落库后、主删除尚未发生的故障窗口继续执行 forget job；
- Legal Hold 或保留策略阻止任务时使用 `BLOCKED`，不伪造人工审批。

## 生命周期策略

- 到期语义记忆转 `REVOKED`；到期情景记忆转 `ARCHIVED`；
- 30 天无召回的语义/情景记忆衰减 importance 并转 `REDUCED_RANK`；
- 90 天无召回转 `COLD` 并停止召回；
- 合法召回后更新 `recall_count/last_recalled_at`，`REDUCED_RANK` 可恢复为 `ACTIVE`；
- `COLD/ARCHIVED/REVOKED/DELETED` 不进入召回候选；权限/租户/组织/工作区/用户/场景过滤仍在候选查询前执行。

## 跨存储删除

- PostgreSQL：正文和结构化值匿名化，状态转 `DELETED`；TTL/COLD 路径以不可召回状态验证；
- Redis：删除记录缓存、embedding 缓存和用户 working-memory registry 及其成员；
- 向量索引：提供 `delete/exists` 受控接口，实际后端接入后必须支持删除验证；
- 对象存储：提供 `delete/exists` 受控接口，仅在实际配置时产生 Outbox；
- 未配置存储明确记录 `NOT_CONFIGURED`，不宣称完成真实后端删除；
- 验证只保存资源 ID 哈希、存储状态和最小元数据，不保存被删正文。

## API 与运行指标

管理员只读接口：

- `GET /api/v1/memory/lifecycle/tasks`
- `GET /api/v1/memory/lifecycle/tasks/{task_id}/delete-verification`
- `GET /api/v1/memory/lifecycle/metrics`

接口仅允许 `analyst_admin`，返回 memory/user 哈希而非正文。隐藏的 Prometheus `/metrics` 增加生命周期运行、迁移计数和最后成功时间指标。

配置项：`MEMORY_LIFECYCLE_SCHEDULER_ENABLED`、`MEMORY_LIFECYCLE_INTERVAL_SECONDS`、`MEMORY_LIFECYCLE_BATCH_SIZE`、`MEMORY_LIFECYCLE_REDIS_ENABLED`、`MEMORY_LIFECYCLE_SCENARIO_IDS`。

## 安全与真实性边界

- 未修改前端、根一键启动、Compose、公共依赖或业务 API schema；
- 未读取或写入真实客户数据，测试数据为隔离构造数据；
- 未宣称生产运行、真实对象存储或真实向量后端已验证；
- 当前数据库事实与本轮明确指令优先于记忆；召回权限失败时 fail closed；
- 删除审计与验证不保留被删正文。

## 回滚

1. 停止或设置 `MEMORY_LIFECYCLE_SCHEDULER_ENABLED=false`；
2. 确认没有 `RUNNING` 任务；
3. 执行 `python -m alembic downgrade data_0001`；
4. 回滚本工作包 Git commit。

降级会删除生命周期任务、Outbox 与验证元数据以及三个召回信号列，不恢复已经按用户指令删除的正文或外部索引内容。
