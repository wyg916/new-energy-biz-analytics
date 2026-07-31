# 引用与 RAG 安全

更新时间：2026-07-31

## 引用合同

每条最终引用包含：

- document_id、document_version_id、chunk_id；
- title、page/section、source；
- published_at、citation_text、retrieval_score。

Response Composer 将 claim_id 与 citation_id 显式绑定；最终只引用当前身份和
场景可见的有效 PUBLISHED 版本。无证据的纯知识问题拒答，不把任意 chunk
直接作为系统指令或未经校验的最终回答。

## 安全控制

- tenant/workspace/scenario/role/data_scope 前置隔离；
- 未发布、过期、撤回、删除和 SUPERSEDED 版本不可召回；
- RAG Prompt Injection 模式检测与证据块隔离；
- script/style/HTML 清理与控制字符清理；
- 只支持 Markdown/文本，单文档上限 2 MB；
- 四份未跟踪用户文档显式拒绝；
- 查询只记录 SHA-256，不记录原始敏感内容。

## 60 条验收底线

- unauthorized_retrievals=0
- cross_scenario_retrievals=0
- unpublished_or_retired_retrievals=0
- expired_version_retrievals=0
- prompt_injection_effects=0
- refusal_accuracy=1.0
- citation_accuracy=1.0
- citation_validity=1.0

当前实现不声明抵御所有未知 Prompt Injection；新增模式和真实恶意语料仍需
持续扩充。
