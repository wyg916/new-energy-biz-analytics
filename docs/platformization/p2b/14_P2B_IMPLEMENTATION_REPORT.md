# P2B 实施报告

## 最终状态

| 能力 | 状态 | 验收事实 |
| --- | --- | --- |
| WORKING_MEMORY | PASS | Redis TTL、幂等、关闭清理、明确降级、PostgreSQL 审计与真实五轮继承 |
| SEMANTIC_MEMORY | PASS | 用户确认后 ACTIVE、纠正产生新版本、旧版 SUPERSEDED、禁止实时值/推断/Secret |
| EPISODIC_MEMORY | PASS | 成功运行结构化写入、摘要与不可逆哈希、run_id 回放、场景隔离 |
| PROCEDURAL_MEMORY | PASS | CANDIDATE→人工审核→测试→ACTIVE，版本不可变且可回滚 |
| MEMORY_GOVERNANCE | PASS | 作用域硬过滤、审计、冲突、TTL/衰减/归档/删除/Legal Hold 预留 |
| SKILL_REGISTRY | PASS | 状态机、Owner、输入输出、步骤、校验、Shadow/灰度字段、停用和回滚 |
| INITIAL_SKILLS | PASS | charging_ops 5 个；sales_ops 复用 3 个通用模板；确定性适配器无场景 if 堆叠 |
| SQLBOT_QUALITY_PATCH | CONDITIONAL | 五项代码补丁和 Source Binding v2 已验；真实 10/30/20 被凭据阻塞 |
| P2B_IMPLEMENTATION | PASS | 80/80 行为评测、295/295 后端、前端/迁移/两场景回归通过 |

## 完成范围

新增 8 张权威 PostgreSQL 表，覆盖 Memory 记录/候选/使用审计/删除审计、Procedure、
Skill、Skill 执行和 SQLBot Source Binding release；Redis 只承载短期 Working 状态。
Memory 检索在查询前按 IdentityContext、scope、scenario、status/validity 和 type 硬过滤，
ContextAssembler 将系统约束、身份权限、程序、语义、情景、工作状态、当前数据、RAG 与
用户问题分区，记忆内容不能覆盖系统指令。

五个 Skill 通过 Metric/Dimension Registry、Scenario Package、Procedure Parameter 和
Analysis Adapter 使用已发布语义层。输出明确区分已验证事实、统计关联、候选根因和建议，
候选根因明确不构成因果；成功运行才写 Episodic，失败和 SQLBot Shadow 不写长期事实。

React 管理 UI 使用正式后端 API，支持记忆查看、确认、更正、拒绝、删除、导出和禁止记忆，
并展示 Skill 状态与治理信息；未实现的启用/停用/回滚控制真实禁用并说明原因。所有页面由
全局状态区持续标识模拟数据、时间、来源与 run_id，不使用前端 Mock 或静默虚构兜底。

## 验收证据

- 后端全量 295/295；精确 Memory 40 + Skill 40 行为评测 80/80。
- charging_ops 15/15、sales_ops 12/12、Deterministic 40/40、DQ 20/20、RAG 60/60、
  Query Security 15/15、Response Composer 7/7、Docker Smoke 6/6。
- Vitest 3/3、前端 build 通过、Playwright 20/20、npm audit 0。
- PostgreSQL `p2b_0001 (head)`，base→head→base→head 通过；62→70 表，核心模拟数据
  300,000 / 50,000 / 82,514 行不变，备份哈希见验收矩阵。
- sales_ops Source Binding v1 SUPERSEDED、v2 ACTIVE；重复启动幂等；字段级敏感信息过滤。
- 所有跨租户、跨用户私有、跨场景私有、删除后召回、未审核程序激活、Secret 写入、
  Prompt Injection 覆盖系统规则的成功数均为 0。

## SQLBot 边界

有效运行态为 `QUERY_ENGINE_MODE=SHADOW`、`SQLBOT_ENGINE_ENABLED=false`、
`SQLBOT_RUNTIME_VERIFIED=false`、`SQLBOT_CANARY_ELIGIBLE=false`。获准的匿名凭据转交未能
取得实际 CredentialReference，10/30/20 在外部请求前 fail-closed；没有运行产物，也没有
Secret、模型自然语言或业务结果行落盘。SQLBot 故障不影响确定性主答案。

## 风险、非目标和外部待办

- 在经授权的安全注入通道提供 `P2A_SQLBOT_USERNAME/PASSWORD` 后，才可按冻结集各执行
  一次 10 Smoke、30 Golden、20 Shadow；达到 80%/70%/0 之前不得跑完整 100 或 Canary。
- P50/P95 是隔离测试观察值，生产容量、长期存储增长与 Token 成本待 P3 验证。
- Legal Hold 仅完成合同和技术预留；企业策略、SSO、真实数据、生产 Secret 与发布流程
  属于 P3/外部待办。
- 并发 `0015_frontend_data_lineage` 尚未合并；未来必须显式解决 Alembic head。
- 多 Agent、自由 SQL、自动执行、自动激活程序、第三场景和生产发布均未建设。

## P3 决策与回滚

P3 企业部署 RC 的十项最低条件已满足，`P3_ENTER=GO`；前提是继续保持确定性主链、
SQLBot Shadow/Canary false，并在部署阶段补齐生产密钥、SSO、容量和 Legal Hold 策略。
SQLBot 外部复评是独立 Conditional，不阻塞 Memory/Skill 的 P2B PASS。

代码按工作包提交逆序执行 `git revert <commit>`；数据库先停写 P2B 管理操作，再执行
`alembic downgrade 0014`。如需恢复平台元数据，使用已校验的 0014 dump；不得删除数据库
卷。Source Binding 可通过 Registry 回滚生成新的 ACTIVE release，或保持 SQLBot disabled。
