# Scenario Package Contract v0.1

状态：**目标合同已冻结；当前只有 charging_ops manifest 雏形**。

## 包结构

```text
scenario.yaml
semantic/
  model.yaml
connectors/
  mappings/
chatbi/
  lexicon.yaml
  question_templates.yaml
diagnostics/
  rules.yaml
reports/
  templates/
samples/
tests/
```

## `scenario.yaml`

必须声明 scenario_id、version、platform_api_range、数据分类、依赖合同版本、入口能力、权限需求、迁移、校验、卸载边界和 checksum。

## 生命周期

`INSTALLED → VALIDATED → PUBLISHED → ACTIVE → DISABLED`

- 安装不等于激活。
- 校验必须检查合同版本、语义模型、数据集兼容性、权限、指标测试和禁止的自由 SQL。
- 场景包不得包含真实凭据或真实企业数据。
- 禁用场景不得删除历史版本、analysis_run 或报告草稿证据。

## 平台与场景边界

平台提供注册、解析、版本、权限、安全和审计；charging_ops 提供实体、指标、词典、编译绑定、规则、模板和模拟数据。场景包不得绕过 Query Guard 或在 LLM 文本中注入可执行 SQL。

## 当前差距

`app/scenarios/charging_ops/manifest.py` 与 registry 是最小注册雏形，未支持包校验、兼容区间、版本安装/激活或禁用。

