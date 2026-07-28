# V2 经营工作台 UI 落地验收

## 结论

**PASS。** 已依据 Figma `o5RbUvqmbTKaUIWyVsubam` 的 `1:2` 节点及仓库参考图完成经营工作台落地。在 1600×900、浏览器缩放 100% 条件下，页面全部内容可在单屏完整显示，根文档无纵向滚动。

## 目标、范围与非目标

- 目标：复刻经营工作台的信息架构、视觉层级和高密度经营分析布局。
- 范围：筛选区、AI 经营摘要、6 项核心指标卡、收入与毛利趋势、收入/毛利贡献拆解、重点问题和重点场站。
- 非目标：未新增指标、未开放自由 SQL、未接入真实企业数据、未改变冻结数据合同。

## 实现证据

- 页面数据来自现有后端指标、趋势、诊断及场站接口，不使用前端静态业务数字。
- AI 摘要仅引用结构化结果，并保留“关联因素不构成因果结论”的真实性边界。
- 页面显示数据范围、模拟数据及数据来源；场站名称沿用固定 seed 模拟数据。
- 筛选、继续追问、分析依据、生成报告等入口复用现有产品导航。
- 贡献拆解驱动项已转换为中文业务标签。

## 修改文件

- `frontend/src/overview.tsx`
- `frontend/src/overview.css`
- `frontend/e2e/operations-workbench.spec.ts`
- `docs/v2/evidence/ui/operations-workbench.png`
- `UI界面参考图/经营工作台.png`

## 数据库与安全影响

- 数据库：无 Schema、迁移或 seed 变更。
- 安全：未改变认证、RBAC、Query Guard 或只读查询边界。
- 配置：无新增密钥、连接串或生产配置。

## 测试与验收

- `npm.cmd run build`：通过。
- `npm.cmd test`：3/3 通过。
- `playwright test e2e/feature-overview.spec.ts e2e/operations-workbench.spec.ts`：2/2 通过。
- 经营工作台专项 E2E 验证：标题、后端指标值、核心图表、问题/场站列表和 `scrollHeight <= innerHeight`。
- Docker Web 镜像完成重建并启动。

验收截图：`docs/v2/evidence/ui/operations-workbench.png`

## 已知限制

- Alpha 使用 2025-01-01 至 2026-06-30 固定 seed 模拟数据，不代表真实企业经营结果。
- 当前趋势按自然月聚合；不提供未经指标合同批准的日粒度推算。
- 本次仅落地经营工作台，不扩展冻结范围外的业务能力。

## 回滚

执行本次提交的 `git revert <commit>`，随后运行：

```powershell
docker compose build web
docker compose up -d --no-deps web
```
