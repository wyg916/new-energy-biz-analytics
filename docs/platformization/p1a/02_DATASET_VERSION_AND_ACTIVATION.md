# DatasetVersion、发布、激活与回滚

## 数据模型

迁移 `0007` 新增：

- `dataset`
- `mapping_version`
- `quality_result`
- `dataset_version`
- `review_record`
- `release_record`
- `semantic_activation`
- `rollback_record`

所有核心实体保留 tenant、workspace、scenario 范围；同一 dataset 通过部分唯一索引最多一个 ACTIVE。

## 生命周期

`QUALITY_PASSED → PENDING_APPROVAL → APPROVED → PUBLISHED → ACTIVE`

- APPROVED 不等于 ACTIVE；
- PUBLISHED 不等于 ACTIVE；
- 发布后内容不可变；
- 新版本激活在事务内将旧版本改为 SUPERSEDED；
- 失败 hook 已验证不会留下半激活；
- 发布、激活和回滚均有幂等键和审计。

## 服务

- `DatasetVersionService`
- `ReleaseService`
- `SemanticActivationService`
- `RollbackService`
- `ActiveDatasetResolver`

PostgreSQL 实跑发现并修复新 MappingVersion/QualityResult 的 flush 顺序问题。修复后同一事务显式先 flush 依赖记录，再插入 DatasetVersion；失败尝试完整回滚。

## PostgreSQL 运行结果

- v1：最终 `ACTIVE`
- v2：完成审核、发布和激活后又回滚，最终 `SUPERSEDED`
- `semantic_activation` 指针恢复到 v1
- `rollback_record` 和发布审计已落库
- 重复安装和重复操作使用幂等键
