# SQLBot Datasource 运行验证

更新时间：2026-07-31

## 1. 隔离运行环境

为避开原工作区并发 `0015`，本轮创建独立 Compose 项目
`renewable-p2a-runtime` 和独立数据卷：

- Alembic：`0014`
- charging_ops ACTIVE context：1
- sales_ops ACTIVE context：1
- charging sessions：300000
- sales orders：50000
- sales order items：82514
- 数据性质：固定种子模拟数据

隔离数据库只连接到 SQLBot 私有代理网络；原 `0015` 数据库和卷未升降级、未
写入、未删除。

## 2. 配置方式

`deploy/sqlbot/provision_runtime_api.py` 在固定 SQLBot 容器内运行，通过
v1.8.0 正式 API 执行：

1. 运行时管理员认证和本地验收凭据轮换；
2. Datasource 连接检查；
3. Schema/View 发现；
4. 批准 View 精确白名单；
5. Datasource 创建或幂等复用；
6. 持久化连接复检；
7. 表和字段同步；
8. 业务事实 View 预览。

运行时只读密码来自容器环境引用。SQLBot v1.8.0 API 按其固定实现保存加密的
Datasource configuration；脚本不打印、不返回、不提交 configuration、
密码、Token 或内部认证值。

## 3. 实际结果

| 项目 | charging_ops | sales_ops |
|---|---:|---:|
| SQLBot Datasource ID | 1 | 2 |
| Schema | `semantic_sqlbot_charging` | `semantic_sqlbot_sales` |
| 批准 View | 3 | 6 |
| 字段 | 32 | 52 |
| 连接 | PASS | PASS |
| 预览关系 | `fact_charging_session` | `sales_order` |
| 预览行数 | 100 | 100 |
| 预览 SQL | 解码后 AST 校验为单条只读 SELECT | 解码后 AST 校验为单条只读 SELECT |
| ACTIVE 版本 | PASS | PASS |

## 4. 只读与隔离负向验证

两个独立 LOGIN 角色均验证：

- `default_transaction_read_only=on`
- connection limit=3
- statement timeout=3000 ms，`pg_sleep(5)` 在约 3001 ms 被取消
- 只发现本场景批准 View 和字段
- own Schema SELECT 成功
- CREATE/INSERT/UPDATE/DELETE/DROP/ALTER/COPY 成功数=0
- `pg_authid` 成功数=0
- public 基础表成功数=0
- 跨场景 Schema 成功数=0

总计：

```text
dangerous_successes=0
cross_scenario_successes=0
public_base_table_successes=0
secret_values_exposed=false
```

## 5. 限制与结论

SQLBot Datasource 已真实连接并读取固定种子模拟数据，但缺少 live 模型，尚未
产生实际 NL2SQL。上游 Datasource configuration 的加密实现属于固定镜像内部
能力，不等同于平台 CredentialReference；因此生产秘密治理仍需上游能力或
外部秘密代理，当前只允许本地隔离验收。

`SQLBOT_DATASOURCE_RUNTIME = CONDITIONAL`

回滚为停止独立验收容器并保留卷；隔离数据库角色可在独立数据库内撤销，不能
删除主平台或 SQLBot 原卷。

