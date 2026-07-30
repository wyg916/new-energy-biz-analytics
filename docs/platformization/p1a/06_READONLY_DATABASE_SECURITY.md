# ChatBI 只读数据库安全

## 已实现

1. `deploy/postgresql/chatbi_readonly.sql`
   - 不创建或保存密码；
   - 创建/复用 NOLOGIN 角色；
   - 创建 `chatbi_semantic` 受控视图；
   - 只授予语义 Schema/View 的 USAGE/SELECT；
   - 撤销 public 表和敏感预定义角色；
   - 设置只读事务、statement_timeout、lock_timeout 和 search_path。
2. `scripts/verify_chatbi_readonly_role.py`
   - 在现有 PostgreSQL 数据库中创建临时 Schema 和独立临时登录角色；
   - 生成的临时凭据只存在于进程内，从不输出；
   - finally 清理角色和 Schema。
3. Readonly Executor
   - `CHATBI_READONLY_EXECUTION_ENABLED=false` 默认关闭；
   - 开启时必须提供 PostgreSQL 只读连接引用；
   - 独立连接先设置只读事务和本地 statement timeout；
   - 缺少配置时 fail-closed。

## PostgreSQL 运行结果

| 检查 | 结果 |
| --- | --- |
| 允许 SELECT 受控语义视图 | PASS |
| 拒绝直接访问基础表 | PASS |
| INSERT / UPDATE / DELETE | 全部拒绝 |
| DDL | 拒绝 |
| `pg_authid` 敏感系统对象 | 拒绝 |
| 默认 transaction_read_only | on |
| statement_timeout 配置与强制触发 | PASS |
| 临时 Schema 删除 | PASS |
| 临时角色删除 | PASS |
| 凭据暴露 | false |

## 当前部署状态

临时运行验证已通过；正式长期 LOGIN 凭据尚未配置，因为外部凭据轮换仍为 `EXTERNAL_PENDING`。正式 SQL 文件保留，运行开关保持关闭，不能把脚本存在或临时验证宣称为生产角色已投用。

## 回滚

- 不启用 `CHATBI_READONLY_EXECUTION_ENABLED` 即不切换执行连接；
- DBA 可先撤销 LOGIN，再 `DROP OWNED BY <role>` 和删除角色；
- 语义视图仅暴露模拟数据允许列，不修改基础事实。
