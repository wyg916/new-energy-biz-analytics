# SQLBot Q1 质量补丁

## 状态

SQLBot 仍为 Shadow，确定性引擎承担全部用户主答案，`SQLBOT_CANARY_ELIGIBLE=false`。
本补丁不改变引擎默认路由，不以 Canary 为 P2B 完成条件。

## 五项修复

1. **Structured Output**：按标准 JSON、锚定 JSON 代码块、锚定 SQL 代码块、完整单条
   SELECT、SQLBot Record 字段解析，其他格式明确失败；不从自然语言任意片段猜 SQL。
2. **LIMIT**：使用 sqlglot AST，平台硬上限 500，明细默认 100，聚合不强加无意义
   LIMIT，超过上限安全下调；禁止字符串替换，超量上游结果仍 fail-closed。
3. **Source Binding**：charging_ops→1、sales_ops→2，版本化、审批、ACTIVE、可回滚并
   审计，不修改 DeterministicEngine。
4. **Prompt Context**：只发送当前场景已授权表/字段、指标、维度、关系、时间字段、
   PostgreSQL 方言和 3 条高质量示例，并设上下文预算；禁止发送另一场景 Schema。
5. **Golden Oracle**：100 条用例补充 metric、dimensions、time range、sort、row range、
   result hash/容差、rejection 和 allowed variants，避免只做 SQL 字符串 exact match。

SQLBot v1.8.0 的真实 MCP/Record 字段已从固定镜像运行代码核验。补丁只在 10 Smoke、
30 代表性 Golden 和 20 Shadow 上复评；除非代表集达到 SQL 生成率 80%、Guard 通过率
70%、安全违规 0，否则不得立即重跑完整 100 条或开启 Canary。

## 发布与复评事实（2026-08-01）

- Source Binding 已正式发布：`charging_ops` datasource 1 保持 v1 ACTIVE；
  `sales_ops` datasource 2 从 v1 SUPERSEDED 升级为 v2 ACTIVE。v2 受控关系集为
  `active_context` 加 9 张销售语义表，敏感字段仍由字段级分类过滤。
- v1→v2、旧版 SUPERSEDED、重复启动不生成 v3、销售域敏感字段过滤的聚焦回归
  6/6 通过；SQLBot 相关后端聚焦回归 43/43 通过，并包含 AST LIMIT 与上游超量
  fail-closed。
- 已获准通过匿名管道复用现有 P2A CredentialReference，但 P2A API 容器实际没有导出
  `P2A_SQLBOT_USERNAME/PASSWORD`，三套脚本均在发起外部请求前 fail-closed；外部
  请求数为 0，未生成 10/30/20 运行产物，也没有凭据、模型自然语言或业务结果行落盘。
- 安全审查拒绝继续探查本地 `.env*` 秘密文件，未绕过该边界。因此本轮
  `SQLBOT_QUALITY_PATCH=CONDITIONAL`、`SQLBOT_CANARY_ELIGIBLE=false`；不得用离线
  100/100 或历史结果替代本轮真实复评。
