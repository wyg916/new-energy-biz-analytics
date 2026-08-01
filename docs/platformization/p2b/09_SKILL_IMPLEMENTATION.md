# 首批 Skill 实现

## 已发布 Skill

| Skill | charging_ops | sales_ops | 输出性质 |
|---|---|---|---|
| revenue_decline_diagnosis | ACTIVE | ACTIVE | 收入变化、贡献、候选原因 |
| order_anomaly_analysis | ACTIVE | ACTIVE | 异常订单、证据、建议 |
| gross_profit_change_decomposition | ACTIVE | ACTIVE | 毛利贡献拆解与校验 |
| station_efficiency_diagnosis | ACTIVE | 不适用 | 场站效率诊断 |
| operating_report_generation | ACTIVE | 不适用 | 可审核经营报告草稿 |

## 执行合同

适配器使用当前 ACTIVE Scenario Package、Metric/Dimension Registry 和确定性查询结果。
标准输出包含 conclusion、metric_change、time_comparison、contribution_breakdown、
anomalies、evidence、candidate_causes、recommended_actions、limitations、confidence、
run_id 和 trace_id。

输出将已验证事实、统计关联、候选根因和建议分类；设备或经营变化不被表述为已证明因果。
贡献合计、版本绑定、证据来源和必需字段均在成功前校验。报告 Skill 只生成可审核草稿，
不自动邮件、建工单或跨系统执行。

## 记忆接入

成功执行写入结构化 Episodic Memory，并等待反馈；候选根因不会自动写 Semantic。
失败、超时或校验不通过只写执行/审计失败，不生成虚假成功记忆。
