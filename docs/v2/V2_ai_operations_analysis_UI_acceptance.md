# V2 AI 经营分析 UI 落地验收

## 结论

**PASS。** 已依据 Figma `5dyUrTExd6FXAltC8hjeW2` 的 `1:2` 节点及仓库参考图完成 AI 经营分析界面落地。在 1600×900、浏览器缩放 100% 条件下，根文档和页面主体均无纵向滚动，完整内容可在单屏查看。

## 目标、范围与非目标

- 目标：复刻会话历史、提问区、当前条件、AI 结论、指标、趋势、贡献拆解、建议行动及证据面板的三栏高密度布局。
- 范围：现有可信 ChatBI、指标摘要、月度趋势、收入诊断和会话状态的前端整合。
- 非目标：未开放自由 SQL、未让大模型直接执行 SQL、未新增指标、未接入真实企业数据、未宣称生产数据或因果关系。

## 实现证据

- 初始经营问题通过 `/api/v1/chat/query` 执行完整 Query Plan、确定性 SQL Compiler、Query Guard、只读执行和 Answer Guard 链路。
- 四项指标、环比/同比、趋势和贡献拆解来自现有后端结构化接口，不使用前端静态业务数字。
- 证据面板展示数据分类、指标口径、查询条件、Query Plan、受控 SQL 入口和 `analysis_run_id`。
- 页面明确标记 `simulated`、固定 seed 数据源及“关联线索不构成因果结论”。
- 会话历史仅展示当前浏览器会话中真实执行的问题，不伪造历史记录。

## 修改文件

- `frontend/src/overview.tsx`
- `frontend/src/overview.css`
- `frontend/e2e/ai-operations-analysis.spec.ts`
- `docs/v2/evidence/ui/ai-operations-analysis.png`
- `UI界面参考图/AI经营分析.png`

## 数据库与安全影响

- 数据库：无 Schema、迁移或 seed 变更。
- 安全：沿用认证、RBAC、确定性编译、Query Guard、只读执行和 Answer Guard；未增加绕过入口。
- 配置：无新增密钥、Token、真实连接串或外部模型配置。

## 测试与验收

- `npm.cmd run build`：通过。
- `npm.cmd test`：3/3 通过。
- AI 经营分析专项 Playwright：通过。
- 既有功能总览、经营工作台 UI 回归：通过。
- 专项断言覆盖：可信分析完成、4 项后端指标、6 个趋势点、3 项贡献拆解、模拟数据标记、Query/Answer Guard、`analysis_run_id` 和 `scrollHeight <= innerHeight`。
- Docker Web 镜像完成重建并启动；API 与 Web 健康检查通过。

验收截图：`docs/v2/evidence/ui/ai-operations-analysis.png`

## 已知限制

- Alpha 使用 2025-01-01 至 2026-06-30 固定 seed 模拟数据，不代表真实企业经营结果。
- 当前页面默认演示 2026 年 6 月、全部授权区域的收入环比变化，避免把不存在的“下降”作为既定事实。
- 当前会话历史为页面生命周期内的短期状态；新会话仍遵循既有会话隔离和记忆合同。

## 回滚

执行本次提交的 `git revert <commit>`，随后运行：

```powershell
docker compose build web
docker compose up -d --no-deps web
```
