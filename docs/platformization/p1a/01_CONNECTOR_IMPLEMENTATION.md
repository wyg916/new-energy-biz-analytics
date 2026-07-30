# Connector SDK 实施记录

## 通用目录

`backend/app/platform/connectors/` 包含：

- `base.py`、`capabilities.py`、`contracts.py`；
- `registry.py`、`errors.py`、`security.py`；
- PostgreSQL、CSV、Excel、MySQL、Mock 实现。

统一接口覆盖连接测试、Catalog/Schema/Table/Column/Relationship 发现、预览、画像、批读、增量读、健康检查和关闭。

## 数据源完成度

| Connector | 状态 | 边界 |
| --- | --- | --- |
| PostgreSQL | 完整实现并在 PostgreSQL 16.9 实跑 | 受控 Schema、参数化标识符、只读事务、分页/增量/画像 |
| CSV | 完整实现 | 受控目录、发现、预览、批读、画像；增量明确 UNSUPPORTED |
| Excel | 完整实现 | 工作表发现、字段推断、预览、批读、画像 |
| MySQL | P1A 最小插件 | 注册、能力、校验、连接与元数据发现；数据批读明确 UNSUPPORTED |
| Mock | 完整测试替身 | 失败、取消、分页、增量与生命周期 |

## PostgreSQL 运行证据

使用临时独立只读角色执行，未输出凭据，结束后角色已删除：

- connection/read_only/health：PASS；
- Catalog 1、Schema 1、受控表 5；
- `fact_charging_session` 字段 16、外键关系 3；
- preview 3、batch 3、incremental 3；
- profile 总行数 300000；
- credential exposed：false。

关系发现从 `information_schema.constraint_column_usage` 改为受限角色可读取的参数化 `pg_catalog` 查询，避免最小权限角色得到假空结果。

## 安全

- 配置拒绝 password/secret/token 等明文字段；
- 响应只返回是否配置凭据，不返回引用和值；
- 统一稳定错误码，驱动异常脱敏；
- 无 fallback 数据；
- 平台 Connector 核心未引用 charging/station/device 等业务实体。
