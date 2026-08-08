# RAG 4.1 迁移、冷启动与回滚

## Migration

- revision：`rag_0001`
- down revision：`data_0001`
- 新表：`knowledge_chunk_index`、`knowledge_governance_event`
- 扩展：document version parser/chunk/embedding metadata；chunk paragraph/locator；
  retrieval rewrite/candidate/refusal/context/rank 审计。

迁移只建 Schema，不在 Alembic 事务内运行应用解析或外部模型。SQLite 和 PostgreSQL
均已验证 `data_0001 → rag_0001 → data_0001 → rag_0001`。

## 冷启动影响

旧知识版本在迁移后没有 `knowledge_chunk_index`。运行状态会显示
`INDEX_BACKFILL_REQUIRED`，检索对缺索引 chunk fail-closed，不临时构造或伪造向量。

执行：

```powershell
$env:PYTHONPATH = "backend"
python scripts/rebuild_rag_indexes.py --output docs/platformization/rag41/evidence/rebuild.json
```

重建会删除并重建当前 embedding model/version 的索引行，每个版本由
`rag_quality_agent` 写一条 `SYSTEM` 审计。验收要求 `chunk_count == vector_count`。
若安全规则文档本身包含攻击示例，自动扫描保留 `REVIEW_REQUIRED`，但不把人工复核旗标
误报为索引重建失败，也不会自动发布。新摄取文档在同一事务中直接生成索引，无额外
冷启动窗口。

## 回滚

代码回滚后执行：

```powershell
cd backend
alembic downgrade data_0001
```

回滚会删除 RAG 4.1 索引/治理表和新增字段，不删除 `knowledge_document`、版本、ACL、
chunk、发布事件或旧检索事件基础字段。执行前应导出 `knowledge_chunk_index` 和
`knowledge_governance_event` 审计；不得删除业务数据库卷。
