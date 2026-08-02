# P5 RAG 正式发布决策

## 决策

选择方案二：正式冻结 `KEYWORD_ONLY` 产品合同。门禁 `RAG_MODE=PASSED`，`RAG_VECTOR_RELEASED=false`，Vector 状态为 `VECTOR_DEFERRED_POST_P5`，不再作为本次生产阻断项。

API、知识运行时、前端概览、知识页面和 P5 门禁面板均显示 keyword-only；没有文本暗示 Vector 已发布。检索继续在 tenant/workspace/scenario 可信作用域内过滤，检索内容只作为不可信证据，不可覆盖系统权限和 Guard；无引用时不得伪造引用。

现有 60 条 keyword 固定评测、知识生命周期、权限、Prompt Injection 与 Response Composer 回归被更新为此正式合同，待本轮完整测试矩阵确认。机器证据为 `evidence/rag-keyword-release.json`。

后续发布 Vector 必须是独立版本，完成 embedding/分块版本、索引构建、删除同步、重建/回滚、权限过滤、keyword/vector/hybrid 对比、引用准确性、注入与降级评测后才能变更本合同。
