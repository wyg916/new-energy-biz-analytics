# P2A Runtime Closeout 最终报告

> 当前有效报告：2026-08-01。下方 2026-07-31 报告为 Provider 调用修正前的历史快照。

## 当前最终结论

```text
MODEL_RUNTIME=PASS
SQLBOT_QUERY_RUNTIME=COMPLETED_WITH_FAILURES
SQLBOT_GOLDEN_RUNTIME=NOT_PASS
SQLBOT_SHADOW=CONDITIONAL
SQLBOT_CANARY_ELIGIBLE=false
CANARY_DECISION=NO_GO
P2A_RUNTIME_CLOSEOUT=CONDITIONAL
P2B_ENTRY=ALLOWED_WITH_SQLBOT_REMAINING_SHADOW
```

Kimi 与 DeepSeek 官方调用真实通过；MiMo `api-key` 鉴权、文本和 JSON 通过但 SQL 合同失败。DeepSeek `deepseek-v4-flash` 依据延迟与遵循性选为主模型，Kimi `kimi-k2.6` 为第一备用。SQLBot v1.8.0 当前 3 个模型配置、唯一默认配置 ID `7489006022829281280`，重启后合同与凭据指纹一致。

真实运行不是 Mock：Smoke 10 次外部请求、Golden 100 次、Shadow 20 次。Smoke 仅 1/10 全链路成功；Golden 5/100 PASS、25% SQL 生成、2% Guard 通过；Shadow 确定性主答案 20/20 成功，真实 SQLBot 生成 SQL 8/20，但全部被 Guard 拒绝，另外 12 条上游失败。SQLBot 只读边界保持危险、DDL、系统表、public 原表和跨场景成功数为 0。

本轮修复三处真实集成问题：按三家官方差异化认证与探测；Datasource 已绑定时不发送字符串 `oid`；成功响应缺 token 时从 SQLBot record usage API补取。新增模型配置、Smoke/Golden/Shadow 验收与 ChatRecord 恢复脚本；未新增迁移、未修改产品 UI/RAG/场景包/数据库结构。

回归通过：后端全量 183/183（36 文件、共享内存 SQLite）、定向 pytest 29/29、Query Security 13/13、Deterministic 40/40、离线合同 100/100、charging 15/15、sales 12/12、DQ 20/20、只读角色安全、Docker smoke 6/6、Alembic 0014/check、Vitest 3/3、构建、Playwright 20/20、npm audit 0。

核心模拟事实恢复后复核：charging sessions 300000、sales orders 50000、sales order items 82514；日期范围 2025-01-01 至 2026-06-30。Secret 仅从仓库外文件注入，完整 Key 不进入 Git、Markdown、前端或验收 JSON。

P2A 以 `CONDITIONAL` 关闭的含义仅是完成真实运行链路与安全降级取证。SQLBot 必须保持 Shadow；修复 source binding、输出格式、Guard policy 对齐和结果值 oracle 后，才可重新申请 Canary。P2B 可进入，但不得把该结论解释为 SQLBot 生产准入。

---

## 历史报告（已取代）

更新时间：2026-07-31

## 最终结论

P2A 平台代码、SQLBot 容器、双 Datasource、只读安全、故障降级和全量回归已经
完成；P2A **运行验收尚未关闭**。本轮已读取用户授权的仓库外凭据，三家 DNS
正常，但 Kimi、MiMo、DeepSeek 官方 `/models` 均真实返回 HTTP 401；MiMo 的
Bearer 与 `api-key` 均失败。SQLBot 内部模型配置数量仍为 0，因此不得执行或
伪造模型调用、10 条 Smoke、100 条运行 Golden 和 20 条真实 Shadow。

```text
P2A_RUNTIME_CLOSEOUT=NOT_PASS
PROVIDER_AUTHENTICATION_FAILED
ALLOW_P2B=false
```

## 32 项汇报

1. **独立 Worktree 路径**：
   `E:\新能源企业经营分析智能平台-p2a-runtime`。
2. **分支、HEAD、远端和工作区**：分支 `feat/p2a-runtime-closeout`；既有运行
   代码提交为 `0046e53`，本轮 Provider 验证提交为 `d4b6e03`；远端基线 fetch
   成功且关闭分支已创建，最终文档提交和推送状态以最新 Git HEAD 为准。
3. **原脏工作区**：保持未修改。其 `ba732d9`、ahead 1 和 5 个未跟踪用户文件
   状态与本轮首次检查一致；读取、修改、暂存、提交均为 0。
4. **P0_EXTERNAL_SECURITY**：`PENDING`。
5. **三个 Provider 直连**：三家 DNS PASS；Kimi `/models` 401
   `invalid_authentication_error`，MiMo Bearer 与 `api-key` 均 401，DeepSeek
   `/models` 401 `invalid_request_error`；Mock 计数 0。
6. **实际模型 ID**：三个 preferred model 分别为 `kimi-k2.6`、
   `mimo-v2.5-pro`、`deepseek-v4-flash`，但模型列表发现均为 0，故不得把
   preferred 值宣称为实际可调用模型 ID；主备顺序未选定。
7. **MODEL_RUNTIME**：`NOT_PASS`，阻断码
   `PROVIDER_AUTHENTICATION_FAILED`。
8. **SQLBot 模型配置**：正式 API 认证 200、模型列表 200、配置数 0；未产生模型
   配置 ID、调用、Token/usage 或延迟。
9. **SQLBot Datasource**：charging_ops ID 1、sales_ops ID 2；只允许批准的
   `semantic_sqlbot_charging` 3 个 View 和 `semantic_sqlbot_sales` 6 个 View。
10. **SQLBot 只读安全**：2/2 角色通过；字段 32/52；只读事务、连接上限 3、
   约 3000 ms timeout 生效；危险、跨场景、public 基础表成功数均为 0。
11. **10 条 Smoke**：0/10，`NOT_EXECUTED`；目标问题和完整 null 证据已生成，
    没有发送模型或 SQLBot。
12. **100 条运行评测**：0/100，`NOT_EXECUTED`；离线合同 100/100 PASS 与运行
    指标严格分离。
13. **charging_ops 运行指标**：live 指标 `NOT_AVAILABLE`；离线 Golden 48 条；
    确定性 15 项指标对账 15/15。
14. **sales_ops 运行指标**：live 指标 `NOT_AVAILABLE`；离线 Golden 52 条；
    确定性 12 项指标对账 12/12。
15. **真实 Shadow**：0/20，`NOT_EXECUTED`；不把降级验证计为真实 Shadow。
16. **SQLBot 故障降级**：隔离 API 20/20 返回确定性主答案，错误证据 20/20，
    主答案失败 0，run_id/trace_id 可关联。
17. **Canary 决策**：`SQLBOT_CANARY_ELIGIBLE=false`、
    `QUERY_ENGINE_MODE=SHADOW`、`NOT_ELIGIBLE`。
18. **pgvector**：PostgreSQL 16.9 镜像无可用/已安装 vector 扩展；
    `RAG_VECTOR=PENDING`、`keyword_full_text_only`。
19. **SBOM/漏洞**：Docker Scout 生成 1,040 包 SPDX；Critical/High 命中
    185（11/174），其中 4 条暂无修复版本；`SBOM_SCAN=CONDITIONAL`，镜像仅
    `LOCAL_ACCEPTANCE_ONLY`。
20. **所有回归**：本轮后端 174/174、Deterministic 40/40、离线 Golden 100/100、
    charging 15/15、sales 12/12、DQ 20/20、Query Security 15/15、Docker
    smoke 6/6、Vitest 3/3、生产构建 PASS、Playwright 20/20、npm audit 0；
    Provider/阻断证据专项 9/9 PASS。
21. **数据库版本/核心数据量**：Alembic 0014 head 且 `check` 无漂移；两个
    ACTIVE context 各 1；charging sessions 300000、sales orders 50000、
    sales order items 82514；日期均为 2025-01-01 至 2026-06-30，均为模拟数据。
22. **实际修改文件**：Runtime evaluator/测试、SQLBot Client、认证模型元数据、
    Datasource 运行 API/只读验证/启动脚本、blocked evidence 脚本、Playwright
    配置及 `docs/platformization/p2a-runtime/00` 至 `11`；逐文件清单以
    `git diff --name-only 2117a87..HEAD` 为准。
23. **新增迁移**：否；未创建或修改 Alembic revision。
24. **未解决风险**：三家凭据/账户授权均被官方接口拒绝；P0 外部凭据事件未关闭；无真实
    NL2SQL/运行准确率/Shadow；固定 SQLBot 镜像有 Critical/High 漏洞；pgvector
    不可用；上游 Datasource secret 治理仅满足本地隔离验收。
25. **MODEL_RUNTIME 结论**：`NOT_PASS`。
26. **SQLBOT_QUERY_RUNTIME 结论**：`NOT_PASS`。
27. **SQLBOT_GOLDEN_RUNTIME 结论**：`NOT_PASS`。
28. **SQLBOT_SHADOW 结论**：`NOT_PASS`。
29. **P2A_RUNTIME_CLOSEOUT 结论**：`NOT_PASS`。
30. **是否允许进入 P2B**：否。最低条件中的 Model/Query 至少 CONDITIONAL、
    真实 SQL/查询结果和 20 条真实 Shadow 均未满足。
31. **回滚方式**：应用即时切回四个 fail-closed 开关；代码按本分支独立提交
    `git revert`；停止独立 SQLBot/验收容器但保留卷；不得删除主平台或数据库卷。
32. **提交哈希**：`f9d659b`、`1a19a2b`、`ebdcd1c`、`61cd407`、`0046e53`、
    `cf0694e`、`c8dcd50`、`d4b6e03`；本最终文档提交以分支最新 Git HEAD 为准，
    避免文件自引用伪值。

## 解除条件

四类运行时引用已经完整，不再要求用户重复提供 provider、base URL、model 或
credential_ref。需要在仓库外文件中修复或替换至少一家能通过官方认证的凭据或
账户授权，且不得在 Git、普通日志或对话中提供 Secret 明文。认证成功后必须按
三类 Provider Smoke → 10 条 SQLBot Smoke → 100 条运行 Golden → 20 条真实
Shadow 的顺序执行；未达 Canary 阈值可以继续保持 Shadow，但不能跳过 P2B
最低准入条件。
