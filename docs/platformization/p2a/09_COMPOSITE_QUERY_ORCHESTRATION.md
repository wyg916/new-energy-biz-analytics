# 数据与知识复合编排

更新时间：2026-07-31

## 路由

- 精确数据问题：data → 现有场景 QueryEngine；
- 企业知识问题：knowledge → Knowledge Service；
- 数据加制度：data_and_knowledge → 两路证据 + Response Composer。

自动分类使用固定受控标记，也允许 API 显式请求合法路由。数据路径继续执行
现有权限、ACTIVE 版本、Query Guard、只读执行和 Answer Guard；知识路径先做
权限/版本过滤。

## 指定示例真实运行

三个任务原文示例已通过实际 Compose API 以 UTF-8 请求执行：

| 问题 | 路由 | 数据状态 | 检索/最终引用 | 结果边界 |
|---|---|---|---:|---|
| 最近30天收入下降多少？ | data | needs_clarification | 0/0 | 当前日期超出模拟数据截止日，未虚构数字 |
| 有效订单如何定义？ | knowledge | 无数据查询 | 5/3 | sales_ops 已发布场景口径 |
| 最近30天收入下降多少，按照经营预警制度应该怎么处理？ | data_and_knowledge | needs_clarification | 5/3 | 时间范围澄清 + 已发布预警处理边界 |

三次均返回模拟数据分类、统一 run_id、trace_id 和 model_call 状态。模型状态为
`MODEL_RUNTIME_PENDING`，最终组合为确定性证据编排。

## 审计与错误

- 分别返回 data_query_evidence、knowledge_retrieval_evidence、model_call；
- 反馈按 composite run_id 与当前用户审计；
- 场景错误映射为结构化 4xx；
- `METRIC_AMBIGUOUS` 不再泄漏为通用 500；
- 非管理员数据证据中的 SQL 被置空。
