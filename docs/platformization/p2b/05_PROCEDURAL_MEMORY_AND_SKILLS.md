# Procedural Memory 与 Skills

## Registry

ProcedureRegistry 和 SkillRegistry 已实现版本、Owner、输入/输出 Schema、步骤、条件、
校验、失败处理、测试证据、Shadow 结果、灰度、回滚和审计。

生命周期为 `DRAFT → CANDIDATE → REVIEWING → APPROVED → SHADOW → CANARY →
ACTIVE`，并支持 `DEPRECATED`、`RETIRED`、`FAILED`。自动反思只能创建 CANDIDATE；
APPROVED/ACTIVE 需要授权人工、测试证据和显式状态迁移。模型不能直接修改已发布 Skill。

## 场景复用

通用 Procedure 通过 Metric Registry、Dimension Registry、Scenario Package 参数和
Analysis Adapter 适配场景。charging_ops 注册 5 个 Skill；sales_ops 复用前三个通用
Procedure，并提供场景适配器，没有在流程主体堆叠场景 if/else。

Skill 执行记录共享 orchestrator run_id，并包含独立 execution/task/step ID、输入输出
摘要、校验结果、状态、错误、耗时和版本。失败执行不写成功 Episodic Memory。
