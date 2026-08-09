# RAG 4.1 企业级混合检索范围与事实边界

更新时间：2026-08-08

## 目标

本工作包从唯一共同基线 `75160df433bbf9273e10a87bae6a7aef29af9744`
升级现有 `keyword_full_text_only` 知识链路，形成模块化单体内的受控企业知识检索：

```text
Document Parse → Metadata → Chunk → ACL → BM25 等价索引
→ 确定性特征哈希向量 → Hybrid → RRF → Rerank
→ Query Rewrite → Context Build → Citation → Answer Guard
```

支持 Markdown、UTF-8 TXT、DOCX 和文本型 PDF。扫描型 PDF 不启用 OCR，必须拒绝。

## 事实声明

- PostgreSQL 16.9 的实际检查结果仍为 `pg_extension.vector=false`。
- 本版本没有伪称 pgvector；向量能力是数据库持久化的
  `deterministic_multilingual_feature_hash_v1`，256 维，版本 `1.0.0`。
- 关键词能力使用应用内确定性 BM25 等价实现，词频、文档长度和向量均持久化到
  `knowledge_chunk_index`。
- 该向量不等同于神经 embedding，不声明跨语言或开放域语义能力。
- 业务数据事实、DATA-4.1 来源/行数/许可/哈希和 15 项核心指标均未改变。
- 当前结论是本地候选与隔离 PostgreSQL 验收，不代表企业生产上线或真实客户收益。

## 非目标

- 不引入自由 SQL、LLM 直接执行 SQL、多 Agent 自动执行或跨系统动作；
- 不接入真实客户文档、密钥或生产连接；
- 不修改前端业务页面、根一键启动文件或最终 Compose；
- 不把自动质量审核伪装为人工发布审批。
