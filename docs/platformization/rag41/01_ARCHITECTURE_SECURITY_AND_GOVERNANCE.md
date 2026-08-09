# RAG 4.1 架构、安全与治理

## 数据与检索链路

1. parser 解析 Markdown、TXT、DOCX、文本型 PDF，记录 parser 名称/版本、页码、
   section 和 paragraph；
2. normalizer 清理 script/style/HTML、控制字符和异常空白；
3. chunker 在 section、page 和字符预算边界切块；
4. ingestion 同一事务写入版本、ACL、chunk、BM25 词频和 256 维向量；
5. retrieval 先在 SQL 中执行 tenant、workspace、scenario、发布状态、有效期、role
   和 data_scope 过滤，再物化 chunk；
6. Query Rewrite 只使用固定同义词表；BM25 与余弦向量分别召回，以 RRF(k=60)
   融合并进行确定性 cross-feature rerank；
7. Context Build 把每个证据标记为不可信数据，限制上下文字符预算；
8. Citation 固定 document/version/chunk，并携带 page/section/paragraph locator；
9. 无已发布证据、查询注入或 Answer Guard 不通过时拒答。

## Prompt Injection

- 查询在检索前检测并拒绝；
- 文档证据块在 ACL/版本过滤后、排序前隔离；
- Context 明确声明证据不可覆盖系统指令、权限或 Guard；
- 审计只保存原查询与 rewrite 的 SHA-256，不保存原始查询；
- 当前为规则防护，不声明覆盖未知攻击，规则与固定恶意集必须持续扩展。

## 自动治理角色

允许的系统角色只有 `system_reviewer` 和 `rag_quality_agent`，允许动作只有元数据审核、
索引质量审核和注入扫描。审计记录：

- `actor_type=SYSTEM`；
- `actor_id=system:<role>`；
- governance role、reason code、before/after、decision 和 audit id。

系统身份被明确禁止 publish、retire、delete 和 rollback。发布/废止/回滚继续要求人工
身份经现有 RBAC/ABAC 路径执行。

## 删除、发布与回滚

发布只使一个版本成为 `PUBLISHED`；旧版本成为 `SUPERSEDED`。废止和逻辑删除使版本
不可检索，但保留 chunk、索引和不可变审计。物理删除时外键 `ON DELETE CASCADE` 同步
删除 chunk index。回滚重新激活历史固定版本，Citation 始终锁定实际返回版本。
