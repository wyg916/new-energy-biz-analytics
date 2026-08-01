# Memory 架构

## 结论

P2B 已实现五类 Memory 的模块化单体闭环。PostgreSQL 是长期记录、版本、审批与
审计的权威源；Redis 只承载有 TTL 的会话/运行状态；关键词或语义索引是可重建的
派生能力，不能绕过数据库中的作用域和状态过滤。

| 类型 | 权威存储 | 写入条件 | 主要用途 |
|---|---|---|---|
| Working | Redis，PostgreSQL 审计 | 会话内自动、幂等 | 多轮上下文与未完成步骤 |
| Semantic | PostgreSQL | 用户明确确认后 ACTIVE | 稳定偏好与术语纠正 |
| Episodic | PostgreSQL | 成功运行后结构化写入 | run_id 回放与 Bad Case |
| Procedural | PostgreSQL | 候选、人工审核、测试 | 版本化 Procedure/Skill |
| Governance Meta | PostgreSQL | 随主记录自动生成 | 来源、冲突、保留、删除审计 |

核心模块位于 `backend/app/memory/`，模型与迁移由
`p2b_0001_memory_and_skills.py` 管理。持久化表包括四张 Memory 表、两张
Procedure/Skill 定义表、Skill 执行表和 SQLBot Source Binding 发布表。

## 数据流

请求先进入 IdentityContext，随后读取 Working State，并在数据库查询前完成
tenant、organization、workspace、user、scenario、status 与 validity 硬过滤。
ContextAssembler 将内容分区，Skill 执行只消费已授权上下文；成功结果写 Episodic，
偏好和程序规则只生成候选，分别等待用户确认或人工审核。

## 真实性与非目标

页面和证据均标注模拟数据。P2B 没有实现多 Agent、自由 SQL、自动审批、自动外部
执行或长期自动学习；SQLBot Shadow 结果只进入评测证据，不成为长期事实。
