# P2A Runtime Closeout 最终报告

更新时间：2026-07-31

## 最终结论

P2A 平台代码、SQLBot 容器、双 Datasource、只读安全、故障降级和全量回归已经
完成；P2A **运行验收尚未关闭**。当前环境没有完整且启用的 live 模型合同，
SQLBot 内部模型配置数量也为 0，因此不得执行或伪造模型调用、10 条 Smoke、
100 条运行 Golden 和 20 条真实 Shadow。

```text
P2A_RUNTIME_CLOSEOUT=NOT_PASS
HUMAN_MODEL_CONFIG_REQUIRED
ALLOW_P2B=false
```

## 31 项汇报

1. **独立 Worktree 路径**：
   `E:\新能源企业经营分析智能平台-p2a-runtime`。
2. **分支、HEAD、远端和工作区**：分支 `feat/p2a-runtime-closeout`；本报告编写
   前已提交 HEAD 为 `0046e53`；远端基线 fetch 成功，关闭分支待最终文档提交后
   推送；工作区仅含本报告对应的受控文档修改。
3. **原脏工作区**：保持未修改。其 `ba732d9`、ahead 1 和 5 个未跟踪用户文件
   状态与本轮首次检查一致；读取、修改、暂存、提交均为 0。
4. **P0_EXTERNAL_SECURITY**：`PENDING`。
5. **实际模型 Provider/模型名**：无。kimi、mimo、deepseek 合同均不完整、
   disabled，运行环境未注入对应字段；本机 Ollama 无模型且不在批准候选中。
6. **MODEL_RUNTIME**：`NOT_PASS`，阻断码
   `HUMAN_MODEL_CONFIG_REQUIRED`。
7. **SQLBot 模型配置**：正式 API 认证 200、模型列表 200、配置数 0；未产生模型
   配置 ID、调用、Token/usage 或延迟。
8. **SQLBot Datasource**：charging_ops ID 1、sales_ops ID 2；只允许批准的
   `semantic_sqlbot_charging` 3 个 View 和 `semantic_sqlbot_sales` 6 个 View。
9. **SQLBot 只读安全**：2/2 角色通过；字段 32/52；只读事务、连接上限 3、
   约 3000 ms timeout 生效；危险、跨场景、public 基础表成功数均为 0。
10. **10 条 Smoke**：0/10，`NOT_EXECUTED`；目标问题和完整 null 证据已生成，
    没有发送模型或 SQLBot。
11. **100 条运行评测**：0/100，`NOT_EXECUTED`；离线合同 100/100 PASS 与运行
    指标严格分离。
12. **charging_ops 运行指标**：live 指标 `NOT_AVAILABLE`；离线 Golden 48 条；
    确定性 15 项指标对账 15/15。
13. **sales_ops 运行指标**：live 指标 `NOT_AVAILABLE`；离线 Golden 52 条；
    确定性 12 项指标对账 12/12。
14. **真实 Shadow**：0/20，`NOT_EXECUTED`；不把降级验证计为真实 Shadow。
15. **SQLBot 故障降级**：隔离 API 20/20 返回确定性主答案，错误证据 20/20，
    主答案失败 0，run_id/trace_id 可关联。
16. **Canary 决策**：`SQLBOT_CANARY_ELIGIBLE=false`、
    `QUERY_ENGINE_MODE=SHADOW`、`NOT_ELIGIBLE`。
17. **pgvector**：PostgreSQL 16.9 镜像无可用/已安装 vector 扩展；
    `RAG_VECTOR=PENDING`、`keyword_full_text_only`。
18. **SBOM/漏洞**：Docker Scout 生成 1,040 包 SPDX；Critical/High 命中
    185（11/174），其中 4 条暂无修复版本；`SBOM_SCAN=CONDITIONAL`，镜像仅
    `LOCAL_ACCEPTANCE_ONLY`。
19. **所有回归**：后端 168/168、Deterministic 40/40、离线 Golden 100/100、
    charging 15/15、sales 12/12、DQ 20/20、Query Security 15/15、Docker
    smoke 6/6、Vitest 3/3、生产构建 PASS、Playwright 20/20、npm audit 0。
20. **数据库版本/核心数据量**：Alembic 0014 head 且 `check` 无漂移；两个
    ACTIVE context 各 1；charging sessions 300000、sales orders 50000、
    sales order items 82514；日期均为 2025-01-01 至 2026-06-30，均为模拟数据。
21. **实际修改文件**：Runtime evaluator/测试、SQLBot Client、认证模型元数据、
    Datasource 运行 API/只读验证/启动脚本、blocked evidence 脚本、Playwright
    配置及 `docs/platformization/p2a-runtime/00` 至 `11`；逐文件清单以
    `git diff --name-only 2117a87..HEAD` 为准。
22. **新增迁移**：否；未创建或修改 Alembic revision。
23. **未解决风险**：缺少 live 模型合同；P0 外部凭据事件未关闭；无真实
    NL2SQL/运行准确率/Shadow；固定 SQLBot 镜像有 Critical/High 漏洞；pgvector
    不可用；上游 Datasource secret 治理仅满足本地隔离验收。
24. **MODEL_RUNTIME 结论**：`NOT_PASS`。
25. **SQLBOT_QUERY_RUNTIME 结论**：`NOT_PASS`。
26. **SQLBOT_GOLDEN_RUNTIME 结论**：`NOT_PASS`。
27. **SQLBOT_SHADOW 结论**：`NOT_PASS`。
28. **P2A_RUNTIME_CLOSEOUT 结论**：`NOT_PASS`。
29. **是否允许进入 P2B**：否。最低条件中的 Model/Query 至少 CONDITIONAL、
    真实 SQL/查询结果和 20 条真实 Shadow 均未满足。
30. **回滚方式**：应用即时切回四个 fail-closed 开关；代码按本分支独立提交
    `git revert`；停止独立 SQLBot/验收容器但保留卷；不得删除主平台或数据库卷。
31. **提交哈希**：`f9d659b`、`1a19a2b`、`ebdcd1c`、`61cd407`、`0046e53`；
    最终验收文档提交与推送哈希以本分支最新 Git HEAD 为准，避免文件自引用伪值。

## 最小人工输入

继续 live 关闭只需要以下四项运行时引用，不得在 Git、普通日志或对话中提供
Secret 明文：

1. `provider`
2. `base_url`
3. `model_name`
4. `credential_ref`

配置完成后必须按 10 条 Smoke → 100 条运行 Golden → 20 条真实 Shadow 的顺序
执行；未达 Canary 阈值可以继续保持 Shadow，但不能跳过 P2B 最低准入条件。
