# Memory 检索与上下文

## 检索顺序

检索严格按 IdentityContext、Scope、Scenario、Status/Validity、Memory Type、结构/关键词
查询、可选语义召回、rerank、冲突处理和上下文预算执行。前五项进入数据库查询条件，
不存在“全库召回后让模型过滤”的路径。

## ContextAssembler

上下文被固定分区为：

1. `system_constraints`
2. `identity_and_permissions`
3. `active_procedure`
4. `semantic_facts`
5. `episodic_examples`
6. `working_state`
7. `current_data`
8. `rag_evidence`
9. `user_question`

每区有独立预算和来源标记，超预算按可信度、有效期和相关性截断。召回内容始终作为数据或
证据，不能成为系统指令。冲突记录在用户确认前不会合并成单一事实。
