# Connector SDK Contract v0.1

状态：**目标合同已冻结，当前实现仅部分满足**。

## 接口

```text
Connector.discover(config, credential_ref) -> CatalogSnapshot
Connector.test(config, credential_ref) -> ConnectionTest
Connector.preview(selection, limit, policy_context) -> PreviewBatch
Connector.extract(selection, cursor, policy_context) -> ExtractBatch
Connector.capabilities() -> ConnectorCapabilities
```

## 必须语义

- `credential_ref` 只能引用外部秘密存储，日志、数据库和响应不得包含明文凭据。
- `discover` 返回 catalog/schema/table/column/主键/关系/类型/更新时间，不承诺所有源都支持关系发现。
- `preview` 和 `extract` 必须只读、限时、限行、受 allowlist 与权限策略控制。
- `ExtractBatch` 必须含 connector_id、source_version、schema_fingerprint、cursor、row_count、checksum、run_id 和数据分类。
- 支持的增量方式必须显式声明：无、时间戳、水位线或 CDC；不能用全量冒充增量。
- 失败分类固定为 ConfigError、CredentialError、PolicyDenied、SourceUnavailable、SchemaDrift、DataError、Timeout。

## 当前适配

- 已有：CSV/XLSX 解析、PostgreSQL/MySQL 只读试读、allowlist REST GET、单次凭据不落库、审计。
- 缺失：通用元数据发现、能力声明、秘密引用、schema fingerprint、增量游标、SDK 注册接口。
- charging_ops 八字段映射是场景适配器，不得进入未来平台 Connector 基类。

## 验收

契约测试必须覆盖凭据不持久化、只读拒绝、allowlist、超时、schema drift、分页/游标和错误分类；在完成这些测试前不得宣称“通用连接器平台”。

