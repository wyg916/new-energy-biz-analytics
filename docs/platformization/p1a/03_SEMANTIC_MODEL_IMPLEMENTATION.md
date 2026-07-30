# 通用语义模型实施记录

## 数据模型

迁移 `0008` 新增：

- `semantic_model`
- `semantic_model_version`
- `semantic_table`
- `semantic_field`
- `metric`
- `dimension`
- `relationship`
- `time_dimension`
- `semantic_filter`
- `data_policy`

## Registry

- `SemanticModelRegistry`
- `MetricRegistry`
- `DimensionRegistry`
- `RelationshipRegistry`
- `ActiveSemanticResolver`

解析链为：

`tenant/workspace → active scenario/version → active semantic version → active dataset version`

语义版本发布前不可正式解析；场景、数据集或兼容范围不匹配会拒绝。平台核心模型与 Registry 未加入 charging、station、device、energy_cost、charging_session 等业务词。

## 指标合同

Metric 支持 code、name、aliases、expression、aggregation、grain、time_field、dimensions、filters、unit、format、owner、version、status、permission_policy 和 lineage。

PostgreSQL 当前已落库：

- semantic_model：1
- semantic_model_version：1
- metric：15
- dimension：12

正式版本路由默认关闭；开启后四类消费者解析同一 activation 指针。
