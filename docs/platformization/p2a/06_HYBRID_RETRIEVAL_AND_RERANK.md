# 检索、融合与 Rerank

更新时间：2026-07-31

## 已实现

- tenant/workspace/scenario/status/validity/role/data_scope SQL 前置过滤；
- 中文二元词与词项关键词检索；
- 内容哈希去重；
- 确定性 overlap、title、phrase boost Rerank；
- limit 1—10 证据预算；
- 检索事件、时延、chunk id、trace_id/run_id 审计。

权限过滤发生在 chunk 内容物化前，未采用“全库召回后交给模型过滤”。

## 向量事实

当前 PostgreSQL 16.9 镜像没有 pgvector 扩展，实际检查
`pg_extension.vector=false`。为避免破坏现有卷，本轮未更换数据库镜像或执行
不可逆扩展操作。

因此当前状态严格标记为：

- retrieval_mode=`keyword_full_text_only`
- vector_status=`VECTOR_PENDING`
- fusion=`NOT_AVAILABLE`

关键词结果没有被表述为向量或混合检索。Rerank 已实现并测试，但完整 hybrid
retrieval 仍是后续工作。
