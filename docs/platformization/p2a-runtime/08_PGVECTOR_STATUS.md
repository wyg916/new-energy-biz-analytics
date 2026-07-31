# P2A pgvector 状态

更新时间：2026-07-31

## 1. 有界复核

在独立验收数据库 `renewable-p2a-runtime-db-1` 上执行只读检查：

```sql
SELECT current_setting('server_version');
SELECT name, default_version
FROM pg_available_extensions
WHERE name IN ('vector', 'pgvector');
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pgvector');
```

结果：

- PostgreSQL：`16.9`；
- `pg_available_extensions`：无 `vector` 或 `pgvector`；
- `pg_extension`：未安装 `vector` 或 `pgvector`；
- 数据库、Schema、扩展和数据卷修改数：0。

当前 `postgres:16.9-alpine` 镜像没有可直接启用的 pgvector 扩展。按冻结约束，
本轮不替换镜像、不在线安装包、不创建迁移、不删除或重建数据卷，也不把关键词
全文检索描述成混合/向量检索。

## 2. 结论

```text
RAG_VECTOR=PENDING
KNOWLEDGE_RETRIEVAL=keyword_full_text_only
```

该状态不阻塞 P2A Runtime 的模型/SQLBot/Shadow 判定，但在正式启用向量能力前
需要独立镜像升级方案、隔离 Schema 验证、向量维度与索引测试，以及 RAG 60 条
重新评测。

## 3. 回滚

本轮没有数据库变更，无数据库回滚动作。保留当前关键词全文检索和现有权限、
版本、引用及评测合同。
