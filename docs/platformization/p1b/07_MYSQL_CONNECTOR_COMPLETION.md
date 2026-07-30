# MySQL Connector 补齐

更新时间：2026-07-30

## 范围

本工作包在现有 Connector SDK 下补齐 MySQL 的受控数据读取能力：

- `preview_data`
- `profile_data`
- `read_batch`
- LIMIT/OFFSET 分页
- 类型归一化
- 连接和语句超时
- 统一错误映射
- `health_check`

`read_incremental` 仍明确返回 `UNSUPPORTED`，未通过静默全量读取伪装成增量
能力。

## 安全边界

MySQL Connector 继续要求：

- 密码只能由 `env://...` 凭据引用在后端解析；
- Connector 配置不能包含 password、secret、token 等明文字段；
- 只允许配置中的单一 database；
- 表名和字段名必须通过安全标识符校验；
- 用户选择字段必须存在于实时发现的 Schema；
- 查询使用经过校验并反引号引用的 identifier；
- LIMIT/OFFSET 和 metadata 条件使用驱动参数；
- 每个连接设置 `TRANSACTION READ ONLY`；
- `MAX_EXECUTION_TIME` 限制在 100 至 60,000 毫秒；
- 单页最多 1,000 行；
- 驱动原始异常和凭据值不进入稳定错误结果。

跨 database、未知字段和包含 SQL 片段的 identifier 均在查询前拒绝。Connector
不会连接项目二可写应用账号，也没有接入任何附件或真实外部系统。

## 数据读取

读取流程：

1. 校验取消状态、连接生命周期、database 和 table；
2. 从 `information_schema.columns` 获取当前可见字段；
3. 校验所选字段并生成受控 SELECT；
4. 在只读事务和语句超时下执行；
5. 使用稳定排序、LIMIT 和 OFFSET 分页；
6. 把 Decimal、日期时间和二进制值转换成 JSON 可传输类型；
7. 生成 schema fingerprint、checksum、run_id 和数据分类证据。

`profile_data` 基于同一预览路径生成 sampled_rows、null_counts 和
distinct_counts，并用单独的只读 `COUNT(*)` 获取总行数。

## 测试

驱动级隔离模拟覆盖：

- 预览、批读和分页；
- Decimal、datetime、date、binary 类型归一化；
- Profile 行数、空值数和去重数；
- 连接测试和健康检查；
- 只读事务与 `MAX_EXECUTION_TIME`；
- 跨 database 拒绝；
- 未知字段 Schema drift；
- identifier 注入拒绝；
- 取消；
- 驱动超时映射；
- 增量能力明确未开放；
- 现有 CSV、Excel、Mock、PostgreSQL 和注册契约回归。

结果：

```text
test_mysql_connector.py + test_platform_connectors.py
24/24 PASS
```

这些测试使用内存中的隔离驱动模拟数据，没有连接真实 MySQL。当前 Docker
缓存中不存在 `mysql:8.4` 镜像，因此没有把本轮结果表述为真实 MySQL 容器
集成或服务器健康检查；该运行时验证列入 P1B 已知限制。

## 数据库影响

无 Alembic 迁移，不修改项目 PostgreSQL 数据，也不创建外部 MySQL 数据源
配置。

## 回滚

回滚本提交即可恢复为仅连接测试和 metadata discovery 的 MySQL Connector。
回滚不涉及数据库迁移或数据卷操作。若需要即时关闭数据读取，可在上层
Connector 注册或数据源状态中禁用 MySQL 数据源，不需要删除数据。
