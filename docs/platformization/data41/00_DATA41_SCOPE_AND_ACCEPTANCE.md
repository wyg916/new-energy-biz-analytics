# DATA-4.1 实施范围与验收

基线：`5de9ea85d0472b98a9265c29623c5ceb1b1cf1b2`。分支：`codex/data-open-source-41`。本阶段只引入可核验公开数据、血缘、质量门禁、统一 PostgreSQL 数据链路和一键启动升级，不启用 SQLBot，不改变 Query Guard、Answer Guard、OIDC 与只读执行边界。

验收标志：

- `DATASET_IMPORT`：两个提交快照均通过哈希验证并幂等落库。
- `DATA_QUALITY`：DATA 新增 28 项检查全部通过，旧 DQ 20/20 回归保持。
- `DATA_LINEAGE`：source、URL/identifier、license、ingestion_time、source_hash、dataset_version、transformation_version、run_id 可通过数据库及 API 查询。
- `DB_API_UI`：Dashboard、Revenue、Diagnostics 的元数据与指标来自活动 PostgreSQL 批次，前端全局状态显示“公开数据样本”。
- `DETERMINISTIC_CHATBI`：继续使用 Query Plan、确定性编译、Query Guard、只读执行与 Answer Guard；SQLBot 未启用。
- `ONE_CLICK_START`：根目录 `一键启动.bat` 继续调用唯一启动器；首次构建后复用镜像和已完成摄取运行，不在每次启动重新下载或导入。

回滚：停止 DATA Compose 服务；对数据库执行 `alembic downgrade p5_0001` 只删除 DATA 新增血缘/raw/staging 表。核心公开数据行按 `batch_id`/`seed_run_id` 可识别；如需业务回退，重新发布原模拟 scenario batch 并将模拟站点状态恢复为 `active`。不使用不可逆迁移。
