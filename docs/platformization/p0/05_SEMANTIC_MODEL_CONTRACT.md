# Semantic Model Contract v0.1

状态：**目标合同已冻结；当前 15 项 charging_ops 指标字典和计算服务是场景实现**。

## 发布单元

`SemanticModelVersion` 必须不可变并包含：

- model_id、version、scenario_id、owner、reviewer、published_at；
- entities、dimensions、measures、metrics、relationships；
- grain、聚合规则、过滤规则、时间语义、单位、币种、空值语义；
- 同义词与歧义处理；
- 数据集兼容约束和 SQL 编译绑定；
- 指标测试向量、版本摘要和 checksum。

## 指标最低字段

`metric_id`、业务名称、定义、公式、分子/分母、粒度、窗口、单位、允许维度、排除项、数据新鲜度、owner、状态和版本。

## 规则

- 核心数字只能来自已发布语义版本。
- Query Plan 必须引用 `semantic_model_version`；编译器不得按自然语言拼接事实表。
- 关系只允许已发布 join graph；多路径歧义必须拒绝或要求澄清。
- 组织规则只有管理员或指标负责人可发布。
- 指标变更必须通过回归向量与受影响查询清单。

## 当前差距

当前 `metric_dictionary_v0.1.md` 和 `MetricService` 固定了 charging_ops 口径，但缺独立版本表、join graph、数据集兼容约束和原子激活。现有实现不得被描述为通用语义建模平台。

