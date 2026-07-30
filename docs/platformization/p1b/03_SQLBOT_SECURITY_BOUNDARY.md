# SQLBot 数据安全边界

更新时间：2026-07-30

## 结论

SQLBot 输出不能直接进入项目数据执行路径。平台新增独立
`guard_sqlbot_sql`，实际 SQL 必须通过 ACTIVE 场景、语义和数据集绑定后
才能被接受。

当前真实 SQLBot 运行仍为 `SQLBOT_RUNTIME_PENDING`，因此本文件记录的是
已实现并测试的平台安全合同，不是生产或真实外部数据验收。

## 强制链路

首选链路：

```text
用户问题
→ SQLBot 生成 SQL
→ 平台 Query Guard
→ 平台独立只读执行器
→ Answer Guard
→ QueryResult
```

固定 SQLBot v1.8.0 的公开 MCP API 未提供稳定的仅生成 SQL 合同。若后续
只能使用上游内部执行，则必须使用专用只读 semantic view，并且平台仍解析、
审计和校验实际上游 SQL 与返回规模。

## Query Guard

SQLBot SQL 当前必须满足：

- 恰好一个 PostgreSQL `SELECT`；
- 禁止注释、多语句、CTE 和通配字段；
- 禁止 INSERT、UPDATE、DELETE、DROP、ALTER、CREATE、MERGE 和控制命令；
- 禁止 `pg_catalog`、`information_schema`、`pg_read_file`、`pg_sleep`、
  `dblink`、`lo_import`、`current_setting` 和 `set_config`；
- 表必须属于当前 ACTIVE 场景的物理关系 allowlist；
- 字段必须属于当前 ACTIVE 语义版本且不能标为 sensitive/restricted；
- 必须有字面量 LIMIT，且不能超过当前 QueryContext 行数上限；
- SQLBot datasource、ScenarioVersion、SemanticModelVersion 和
  DatasetVersion 必须同时绑定；
- 缺少任一版本或 datasource 时 fail-closed。

## 身份与会话

会话绑定 tenant、workspace、subject、conversation、scenario、
scenario_version、semantic_version 和 dataset_version。任一维度变化都会
隔离新会话。

数据库只记录非秘密映射和证据：

- 可以记录 external chat_id；
- 禁止记录 access token、账号密码或原始秘密；
- 浏览器响应和日志不得包含上述内容；
- 认证失效最多重建一次。

## 数据库执行边界

SQLBot 实际运行前还必须完成：

- 独立只读 LOGIN 角色；
- 事务只读；
- statement timeout；
- 只授权专用 semantic schema/view；
- 不授权基础表、系统表和敏感字段；
- 行数与并发限制；
- 当前模拟数据版本绑定；
- 同一套安全负向脚本复验。

在这组运行证据完成前，`SQLBOT_RUNTIME_VERIFIED=false`。

## 负向测试

Adapter 安全测试覆盖 14 类危险或越权 SQL；现有 Query Security 继续覆盖
13 项自由 SQL 拒绝。危险 SQL、越权表/字段、跨场景表和超大结果的成功数均
为 `0`。

Prompt Injection 和 SQL Injection 的问句级黄金集在 P1B 评测工作包继续
覆盖；它们不能绕过上述 SQL AST 与版本 allowlist。

## 回滚

关闭 `SQLBOT_ENGINE_ENABLED` 或把路由切到 `DETERMINISTIC_ONLY` 即可停止
所有 SQLBot 调用。独立 SQLBot 只读角色若已创建，应先撤销 LOGIN，再清理
其对象授权；不影响 DeterministicEngine。
