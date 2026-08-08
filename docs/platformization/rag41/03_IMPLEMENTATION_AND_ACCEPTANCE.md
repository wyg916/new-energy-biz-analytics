# RAG 4.1 实施与验收报告

## 完成内容

- 四类文档解析、解析/分块/embedding 版本元数据；
- page/section/paragraph Citation locator；
- ACL 与版本/有效期 SQL 前置过滤；
- BM25 等价检索、持久化等价向量、Hybrid、RRF、确定性 Rerank；
- 固定同义词 Query Rewrite、受控 Context Build、Citation 和 Answer Guard；
- Prompt Injection 查询拒绝与证据隔离；
- 发布、废止、逻辑删除、回滚、索引重建与受控自动治理审计；
- 原 60 条 + 新增 60 条，共 120 条固定 RAG Golden Set。

## 验收摘要

| 项目 | 结果 |
|---|---|
| RAG 120 | Recall@10 1.0000；MRR 0.8298；连续两轮一致 |
| Citation | accuracy 1.0；299 次 locator/版本合同检查 |
| ACL | unauthorized=0；cross-scenario=0 |
| Prompt Injection | query effects=0；10/10 查询拒绝 |
| 无证据拒答 | `NO_PUBLISHED_EVIDENCE` |
| SQLite 聚焦 | 19/19 |
| PostgreSQL 16.9 聚焦 | 19/19 |
| 后端全量最终回归 | 377/377 |
| 完全停止后 HTTP 冷启动 E2E | 1/1；28 chunk / 28 index；中文 Citation locator PASS |
| PostgreSQL 索引对账 | 142 chunk / 142 vector |
| 自动治理 | PostgreSQL 24/24 为 `actor_type=SYSTEM`；5 条安全示例旗标保留为 `REVIEW_REQUIRED` |
| Migration | SQLite 与 PostgreSQL 往返 PASS |

完整机器证据见 `evidence/rag41-acceptance.json`、`backend-full.xml` 和
`postgres-focused.xml`。第一次全量后端运行的 2 个失败被定位为 Windows CRLF 导致
DATA 快照字节哈希偏移；新增 `.gitattributes` 后快照内容仍与 Git blob 和 manifest
SHA 完全一致，2/2 复验通过；修复后最终全量为 377/377 PASS。

## 限制与风险

- 等价向量是确定性特征哈希，不是神经语义 embedding；
- PostgreSQL 未安装 pgvector，不提供 ANN 索引；当前授权候选上限 500，规模扩大前需
  容量复验；
- PDF 只支持文本抽取，不支持 OCR；
- Prompt Injection 为规则检测，不能证明覆盖未知攻击；
- 旧库迁移后必须完成受控 index rebuild 才能进入 Hybrid READY；
- 当前为隔离本地/临时 PostgreSQL 证据，不是生产准入或生产 SLA。
