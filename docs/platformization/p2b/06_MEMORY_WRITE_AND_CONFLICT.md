# Memory 写入与冲突

## Write Pipeline

所有长期写入依次经过候选生成、类型分类、作用域校验、数据分级、脱敏、去重、冲突
检测、可信度判断、保留策略和审批。`MemoryWriteCandidate` 保存 duplicate hash、
conflict group、trust level、approval required、retention policy、write reason 与
rejection reason。

默认策略：Working 可自动短期写；成功运行可写结构化 Episodic；Semantic 需用户确认；
Procedural 只能生成候选并由人工审核；Governance Meta 随主记录自动生成。

## 冲突规则

同稳定键但值不同会建立 conflict group，不静默覆盖。用户级偏好请求用户确认；企业
程序规则要求管理员或指标负责人审批。只有旧记录已 SUPERSEDED，新版本才允许 ACTIVE。

去重、Secret 拒绝、作用域拒绝、审批和冲突的每次决策都写审计。脱敏在持久化之前执行，
因此审计本身也不保存原始凭据。
