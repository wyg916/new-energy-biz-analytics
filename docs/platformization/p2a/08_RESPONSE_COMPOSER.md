# Response Composer

更新时间：2026-07-31

## Profile

项目二自己的确定性最终回答边界支持：

1. `executive_brief`
2. `analyst_detailed`
3. `operation_action`
4. `concise_query`

每个 Profile 固定最大长度、来源/指标口径/引用/置信度/SQL/行动建议展示
策略和禁止表达。SQL 仅对 analyst_admin 且 Profile 允许时展示。

## 统一合同

FinalResponse 包含 conclusion、key_metrics、analysis、drivers、evidence、
risks、recommended_actions、data_source、metric_definition、citations、
warnings、confidence、trace_id、run_id、profile、sql、refused 和数据分类。

组合输入只允许：

- 已通过 Query Guard/Answer Guard 的结构化数据；
- 当前有效已发布知识的 claim/citation；
- 明确的模拟数据与运行边界。

本轮兼容性修复保留底层 ChatBI 的 `CHAT-*`/`SALES-*` 业务 run_id、ACTIVE
版本、Guard 和 SHADOW 证据，同时保留 `COMPOSITE-*` 统一反馈审计 run_id。
sales_ops 原始结构化结论不会被通用句覆盖。

## 结果

Response Composer 专项 `7/7 PASS`；统一知识/数据/复合 API、角色 SQL 脱敏和
错误映射专项 `5/5 PASS`。未调用实际 LLM，当前生成方式是
`NOT_REQUIRED_DETERMINISTIC_COMPOSITION`，因此不存在用 Mock 冒充模型回答。

`RESPONSE_COMPOSER = PASS`
