# charging_ops 场景包迁移

## 场景包

根目录 `scenarios/charging_ops/` 包含：

- `manifest.yaml`
- `data_models.yaml`
- `metrics.yaml`
- `dimensions.yaml`
- `relationships.yaml`
- `terminology.yaml`
- `sql_examples.yaml`
- `diagnostics.yaml`
- `report_templates.yaml`
- `permissions.yaml`
- `response_profiles.yaml`
- `knowledge_manifest.yaml`

文件内容为 JSON 兼容 YAML，不含秘密值。

## 生命周期

`INSTALLED → VALIDATED → PUBLISHED → ACTIVE → DISABLED`

实现 `ScenarioPackageLoader`、`ScenarioValidator`、`ScenarioRegistry`、版本兼容检查与租户工作区范围。迁移 `0009` 增加场景包范围和生命周期元数据。

## 迁移结果

- 15 项指标代码和表达式与 `metric_dictionary_v0.1` 保持一致；
- 业务维度、术语、QueryPlan 示例、诊断、报告、权限和响应配置进入场景包；
- SQL 示例仅为 QueryPlan，`free_sql=false`；
- RAG 和长期记忆在 `knowledge_manifest.yaml` 中明确禁用；
- 兼容适配层保留旧实现，不在本轮大删除。

## 对账

`charging_ops` 包加载后，15/15 指标与冻结基线逐项相同，差异 `{}`。数据分类始终为 `simulated`。
