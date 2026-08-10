# KNOWLEDGE-BASELINE-4.1 Full Integration Handoff

## 0. 冻结结论与边界

- 验收结论：`PASS`
- 工作包状态：`FROZEN`
- 冻结实现分支：`codex/knowledge-baseline-41`
- 冻结实现提交：`b0de3db63959002668b79e30ff5c784672beedf7`
- 冻结实现远端提交：`b0de3db63959002668b79e30ff5c784672beedf7`
- 冻结日期：`2026-08-10`
- 本文件是冻结后的文档型 Integration Handoff；包含本文件的后续小提交不改变上述实现基线身份。

本工作包不再继续开发 RAG，不升级 pgvector/BGE，不修改 Integration-Core 业务代码，不创建正式 RC tag。历史机器证据保持原样，不因新的事实口径而重写、删除或覆盖。

## 1. Branch

`codex/knowledge-baseline-41`

Full Integration 应以本分支的冻结实现提交为 Knowledge 输入，不得从更早的 `codex/rag-hybrid-41` 单独重建知识基线。

## 2. HEAD

冻结实现 HEAD：

`b0de3db63959002668b79e30ff5c784672beedf7`

该提交主题为：

`feat(rag): publish governed knowledge baseline v1`

包含本 Handoff 的文档提交是 `b0de3db...` 的后继提交，只补充 Integration 交接，不属于 Knowledge 功能实现变更。

## 3. merge-base

与 `codex/integration-4.1-core` 的直接 merge-base：

`0a2c776cd6ba47598a17286a793f3c570823cf77`

该提交也是 `b0de3db...` 的直接父提交。其 DATA-4.1 共同祖先为：

`75160df433bbf9273e10a87bae6a7aef29af9744`

## 4. 修改文件

冻结实现提交相对 `0a2c776...` 共修改 31 个文件，无数据库迁移。

### 4.1 根目录与说明

- `README_知识基线包落地说明.md`
- `SHA256SUMS.txt`
- `安装知识基线包.bat`
- `发布知识基线包.bat`

### 4.2 Knowledge 代码与测试

- `backend/app/knowledge/approved_sources.py`
- `backend/app/knowledge/reranker.py`
- `backend/tests/test_rag_hybrid_unit.py`

### 4.3 知识正文

- `docs/knowledge_baseline/v1/KB00_知识基线说明.md`
- `docs/knowledge_baseline/v1/KB01_15项核心指标定义.md`
- `docs/knowledge_baseline/v1/KB02_数据字典.md`
- `docs/knowledge_baseline/v1/KB03_charging_ops业务规则.md`
- `docs/knowledge_baseline/v1/KB04_sales_ops业务规则.md`
- `docs/knowledge_baseline/v1/KB05_收入与成本计算规则.md`
- `docs/knowledge_baseline/v1/KB06_数据接入说明.md`
- `docs/knowledge_baseline/v1/KB07_业务分析方法.md`
- `docs/knowledge_baseline/v1/KB08_SQL安全规则.md`
- `docs/knowledge_baseline/v1/KB09_项目功能使用说明.md`

### 4.4 Import plan 与验收 Evidence

- `integration/approved_sources_paths.txt`
- `integration/knowledge_import_plan.json`
- `integration/knowledge_manifest.json`
- `integration/source_provenance.json`
- `integration/publish_result.json`
- `integration/knowledge_baseline_v1_acceptance.json`
- `integration/knowledge_baseline_v1_governance_audit.json`
- `integration/knowledge_baseline_v1_identity_acceptance.json`
- `integration/knowledge_baseline_v1_index_inventory.json`
- `integration/knowledge_baseline_v1_regression.json`

### 4.5 安装、发布与验证脚本

- `scripts/install_knowledge_baseline_v1.py`
- `scripts/apply_knowledge_baseline_v1.py`
- `scripts/publish_knowledge_baseline_v1.py`
- `scripts/verify_knowledge_baseline_v1.py`

本 Handoff 小提交只应新增：

- `docs/platformization/knowledge41/04_KNOWLEDGE_BASELINE_INTEGRATION_HANDOFF.md`

## 5. Approved source 变化

`backend/app/knowledge/approved_sources.py` 在原 13 个 reviewed source 基础上新增 10 个 `docs/knowledge_baseline/v1/KB00`—`KB09` 路径，当前 allowlist 共 23 个路径。

安全边界保持不变：

- 仅显式 allowlist 中的仓库受控文件可以摄取；
- 禁止自动扫描工作区并摄取任意文件；
- 文件存在于磁盘不等于已批准；
- 摄取、发布、召回继续执行 tenant/workspace/scenario/role/data_scope 权限约束；
- 已废止、未发布或超出有效期的版本不得召回。

## 6. Import plan

`integration/knowledge_import_plan.json` 版本为 `1.0.0`，基于 `0a2c776...`，包含 17 个导入条目：

- `charging_ops`：9 个条目；
- `sales_ops`：8 个条目；
- 物理知识文件：10 个；
- 知识域：`system_help`、`metric_definition`、`data_dictionary`、`business_rule`、`scenario_guide`、`analysis_method`、`security_rule`；
- 数据范围：`workspace:all`，同时受身份、租户、工作区、场景和角色约束。

推荐导入顺序：

1. 执行 `python scripts/install_knowledge_baseline_v1.py --verify-only` 校验包完整性；
2. 确认 10 个知识路径已进入 approved-source allowlist；
3. 确认最终 Integration API、PostgreSQL、Redis 与 Knowledge runtime 已 READY；
4. 使用真实 `analyst_admin` OIDC 身份和治理权限执行 `scripts/publish_knowledge_baseline_v1.py`，或在本地 Integration 验收中执行 `scripts/apply_knowledge_baseline_v1.py`；
5. 对同 source/title 的已有文档复用 `document_id`，正文哈希相同且已 `PUBLISHED` 时执行 `SKIP_ALREADY_PUBLISHED`，避免生成无意义版本；
6. 发布后执行在线 20 问、Citation、ACL、Prompt Injection 与无证据拒答验收；
7. 只读核对发布版本、chunk 与 index 数量。

不得把 Token、密码或真实连接信息写入仓库、日志或 Evidence。正式环境不得使用 `--insecure` 跳过 TLS 验证。

## 7. Runtime 发布要求

Full Integration 发布 Knowledge baseline 前必须满足：

- 代码包含冻结实现 `b0de3db...`；
- PostgreSQL、Redis、API 与 Knowledge Service 健康；
- Alembic 只有 Full Integration 批准的唯一 head；本 Knowledge baseline 自身无新增 migration；
- 10 个知识文件已随镜像/部署包发布，且文件哈希与 manifest 一致；
- approved-source allowlist 包含 10 个知识路径；
- 使用真实 `analyst_admin`，并验证 `rag.document.view`、`release.review`、`release.activate`；
- 自动治理身份只做质量审查，不替代真实发布身份；
- 发布后 `/api/v1/knowledge/runtime` 返回 `knowledge_service=READY`；
- `published_chunk_count > 0` 且等于 `indexed_chunk_count`；
- 检索模式保持 `hybrid_bm25_vector_rrf_rerank`；
- 当前等价向量实现保持 `EQUIVALENT_VECTOR_READY`，不得宣称已使用 pgvector 或 BGE；
- 发布流程必须幂等，重复运行不得制造重复文档或重复已发布版本。

当前治理审计为 `PASS_WITH_REVIEW_DISCLOSURE`：15 个条目自动质量检查通过，2 个 `KB07` 双场景条目因正文包含防御性“绕过/拒绝”表述被标记为 `review_required`；它们未导致 Prompt Injection 证据进入回答，且 17 个版本最终均由已验证的真实用户身份发布。Full Integration 必须保留该披露，不得改写成“17/17 自动审核无告警”。

## 8. 知识版本数量

- Import plan 条目：17
- 已摄取：17
- 已发布：17
- 失败：0
- 当前版本号：全部为 version `1`
- 状态：17/17 `PUBLISHED`

同一个物理知识文件可以按场景形成不同的文档/版本记录，因此物理文件数 10 与已发布知识版本数 17 不矛盾。

## 9. Chunk / Index 数量

- Published Chunks：276
- Indexed Chunks：276
- 未索引差额：0
- Index backfill required：`false`
- Knowledge Service：`READY`
- Retrieval：`hybrid_bm25_vector_rrf_rerank`
- Keyword index：`equivalent_bm25_v1`
- Vector status：`EQUIVALENT_VECTOR_READY`
- `pgvector_claimed`：`false`

以上数量来自 `integration/knowledge_baseline_v1_index_inventory.json` 的只读实时数据库核对。Full Integration 合并或重新发布后必须重新生成最终环境的数量证据，不得复制旧数量冒充新运行证据。

## 10. Knowledge API 变化

冻结实现提交相对 `0a2c776...` 没有新增 Knowledge API 路由或请求/响应 schema。它复用现有受控接口：

- `GET /api/v1/knowledge/runtime`
- `GET /api/v1/knowledge/source-catalog`
- `GET /api/v1/knowledge/documents`
- `POST /api/v1/knowledge/documents/ingest`
- `POST /api/v1/knowledge/versions/{version_id}/publish`
- `POST /api/v1/knowledge/versions/{version_id}/retire`
- `POST /api/v1/knowledge/versions/{version_id}/delete`
- `POST /api/v1/knowledge/versions/{version_id}/rollback`
- `POST /api/v1/knowledge/retrieval/test`

本基线对 API 的可见影响是 source catalog 增加 10 个 approved source，documents/runtime 返回 17 个已发布版本及 276/276 chunk/index 状态。

当前历史验收中 `/knowledge/runtime` 与 `/knowledge/documents` 的 `data_classification` 仍为 `simulated`。这是已冻结历史证据，禁止重写。Full Integration 必须基于 DATA-4.1 的当前活动事实统一更新运行时口径，并至少区分：

| 分类 | 当前事实口径 |
|---|---|
| `OPEN_SOURCE_REAL_DATA` | ACN / UCI 公开源直接提供并经标准化保留的基础源字段 |
| `OPEN_SOURCE_DERIVED` | 依据公开源事实和确定性转换形成的派生经营字段 |
| `BUSINESS_ASSUMPTION` | 公开源不提供、由显式版本化业务规则补充的假设，例如销售成本为非退款净收入的 70% |
| `TEST_FIXTURE` | 仅用于测试和历史回归的固定随机种子数据 |

Full Integration 不得把派生经营字段描述成 ACN/UCI 原始字段，不得把 `BUSINESS_ASSUMPTION` 描述成公开源观测值，也不得把历史固定种子数据作为当前活动公开源事实。运行时最终采用单字段、结构化数组或 lineage 明细的具体 API 形态由 Full Integration 决定，但必须保持上述四类可辨识且可追溯。

## 11. Reranker no-evidence 修复

`backend/app/knowledge/reranker.py` 修复了等价 feature-hash 向量在无业务关键词证据时可能因哈希碰撞建立虚假证据的问题：

- 移除“什么、怎么、如何、多少、是否”等问题形式词，避免它们充当业务证据；
- BM25 只保留分数大于 0 的候选；
- 向量候选必须同时满足 `vector_similarity >= 0.30` 和 `keyword_score > 0`；
- 向量只融合、重排已有 FTS 支持的候选，不得单独跨越 no-evidence 边界；
- 无合格已发布证据时继续返回 `NO_PUBLISHED_EVIDENCE`，Answer Guard 状态为 `REFUSED_NO_EVIDENCE`。

对应单测为 `test_question_form_terms_cannot_establish_unrelated_evidence`。该修复不得在 Full Integration 冲突解决时被旧 reranker 实现覆盖。

## 12. 与 Full Integration 可能冲突的文件

### 12.1 高风险直接冲突

- `backend/app/knowledge/approved_sources.py`：其他知识包也可能追加 allowlist，必须集合合并，不能整文件择一覆盖。
- `backend/app/knowledge/reranker.py`：RAG 优化或模型升级容易覆盖 no-evidence 修复，必须保留问题形式词过滤和“向量不能单独建立证据”的边界。
- `backend/tests/test_rag_hybrid_unit.py`：测试集合合并时必须保留 no-evidence 回归用例。
- `SHA256SUMS.txt`：根目录完整性清单可能被其他工作包同时生成；Full Integration 应重新生成统一清单，历史清单保留。
- `integration/*.json`：Full Integration 可能生成同名汇总；不得覆盖本工作包历史 Evidence，应使用新的 final/integration evidence 路径或版本名。

### 12.2 预期由 Full Integration 统一修改的公共文件

- `backend/app/knowledge/api.py`：统一 `data_classification` 口径；本冻结提交未修改该文件。
- `scripts/release/start-project.ps1` 与根 `一键启动.bat`：统一最终 runtime、索引校验和展示口径；本冻结提交未修改这些文件。
- Compose、公共依赖、前端状态区、OpenAPI 快照：如需反映最终分类和 Knowledge readiness，只能由 Full Integration 统一修改。

本知识基线没有 Alembic migration，因此不会引入新的 migration head；若 Full Integration 为最终分类或其他工作包新增迁移，仍需单独验证唯一 head、upgrade/rollback/re-upgrade。

## 13. Final RC 必须重新执行的 RAG 测试

Final RC 必须在最终合并 SHA、最终 PostgreSQL/Redis、最终权限配置和最终统一启动链路上重新执行，旧 Evidence 只能作为历史输入，不能替代 Final RC 证据。

最低必跑集合：

1. 包完整性：`python scripts/install_knowledge_baseline_v1.py --verify-only`；
2. RAG 单元与 120 条固定评测：`python -m pytest backend/tests/test_rag_hybrid_unit.py backend/tests/test_rag_hybrid_120.py -q -s`；
3. 完整 Backend regression：`python -m pytest backend/tests -q`，并在最终环境处理当前隔离 Redis 测试的前置条件，不得无说明跳过；
4. 真实 OIDC `analyst_admin` 发布权限及 `rag.document.view`、`release.review`、`release.activate`；
5. 17/17 文档发布、重复发布幂等、版本复用与审计身份；
6. 只读实时数据库核对 published/indexed 数量相等；
7. `scripts/verify_knowledge_baseline_v1.py` 的在线 20 问；
8. Citation 20/20，检查 document/version/chunk、locator、source、published_at 与 score；
9. 未认证访问 401、Unauthorized Recall=0、跨 tenant/workspace/scenario/role/data_scope 隔离；
10. Prompt Injection 查询拒绝、危险注入 Evidence Used=0、内容注入在 ranking 前过滤；
11. 无证据拒答 `NO_PUBLISHED_EVIDENCE` / `REFUSED_NO_EVIDENCE`；
12. Knowledge cold start、warm restart、索引复用/必要 backfill、故障恢复；
13. 发布、retire、logical delete、rollback 的审计与召回行为；
14. 最终统一启动脚本中的 Knowledge Service `READY` 和分类口径展示；
15. 历史 Evidence 文件 hash/内容不变检查。

冻结时参考结果：Backend 397 collected / 396 passed / 1 skipped / 0 failed；RAG 120 条，Recall@10=1.0，MRR=0.8664，Citation accuracy=1.0；在线 RAG 20/20，Citation 20/20，Unauthorized Recall=0，Prompt Injection Evidence Used=0。Final RC 必须生成自己的时间、环境、SHA 和 run_id 证据。

## 14. Rollback 方式

Rollback 必须区分代码、运行时知识版本和 Evidence：

1. **代码回滚**：在 Full Integration 分支使用新的 `git revert` 回退引入 `b0de3db...` 的 merge/cherry-pick，不得 reset 或改写共享历史；若只需撤回知识正文，可按提交边界选择性回退，但必须保留安全 reranker 修复或提供等价验证。
2. **运行时回滚**：若目标文档已有上一已发布版本，使用治理接口 `POST /api/v1/knowledge/versions/{version_id}/rollback` 回到明确的 `target_version_id`；本 v1 基线没有前一版本时，逐项 `retire` 17 个 v1 版本，必要时执行 audit-preserving logical delete，禁止直接删除数据库记录。
3. **索引收敛**：版本状态变更后重新核对 published/indexed 数量与召回结果，确保被撤回版本不可召回，且无孤立有效索引。
4. **Allowlist 回滚**：仅在代码回滚要求下移除本次 10 个新增路径；不得影响原 13 个 approved source，也不得把任意工作区扫描作为替代。
5. **Evidence 保留**：所有既有 `integration/knowledge_baseline_v1_*`、`publish_result.json`、governance/identity/index/regression Evidence 原样保留；回滚生成新的回滚证据，不覆盖旧文件。
6. **恢复验证**：重新执行 API readiness、ACL、Prompt Injection、no-evidence、Citation 与最终统一启动验收，记录回滚前后 SHA、知识版本、chunk/index 数量和 run_id。

## 15. Full Integration 接收条件

Full Integration 可以接收本冻结工作包，但必须同时满足：

- 以 `b0de3db...` 为 Knowledge 冻结实现输入；
- 保留 reranker no-evidence 修复；
- 不改写历史 Evidence；
- 统一修正运行时数据分类，而不是修改旧验收结果；
- 在最终合并 SHA 上重新执行第 13 节测试；
- 未完成最终分类、最终权限、最终索引与最终启动验收前，不创建正式 RC tag。
