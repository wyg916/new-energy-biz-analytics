# 功能总览 UI 开发验收记录

## 结论

PASS。功能总览已按 Figma 节点 `2:2` 和仓库内参考图完成 React/CSS 落地，并在本地 Docker Compose 环境通过构建、数据链路和 Playwright 验收。

## 目标与范围

- 复刻桌面端侧边导航、顶部工具栏、平台概览、两排功能卡片、常用分析入口、系统状态和视图说明。
- 复用现有认证、RBAC、指标语义层、驾驶舱、ChatBI、异常诊断与报告草稿接口。
- 使用固定种子模拟数据；页面展示数据时间、来源、批次或 `analysis_run_id`。
- 提供 760px 和 1080px 两级响应式降级；桌面总览采用视口高度自适应布局。

## 非目标

- 不新增指标、真实企业数据、自由 SQL、SSO、多租户或自动执行能力。
- 不把参考图中没有后端依据的告警数量、报告数量和数据源数量写成真实结果。
- 数据接入与指标管理入口仅如实说明当前 Alpha 能力边界。

## 修改文件

- `frontend/src/overview.tsx`
- `frontend/src/overview.css`
- `frontend/src/main.tsx`
- `frontend/src/format.ts`
- `frontend/public/figma-assets/*`
- `frontend/e2e/feature-overview.spec.ts`
- `docs/v2/evidence/ui/feature-overview.png`

## 数据库与安全影响

- 无数据库 Schema 或迁移变化。
- 无真实数据、密钥或连接串写入。
- API 请求继续携带现有 Bearer Token；401 继续清理本地会话并重新登录。
- 页面经营数字来自 `/api/v1/dashboard/*`，ChatBI、诊断和报告继续调用受控后端链路。

## 验收证据

- `npm.cmd test`：3/3 通过。
- `npm.cmd run build`：通过。
- `playwright test e2e/feature-overview.spec.ts`：1/1 通过，并断言 1600×900、浏览器 100% 缩放下页面无纵向滚动。
- Playwright 验证了数据库指标、模拟数据标签、数据来源、`analysis_run_id`、AI入口、异常诊断和报告草稿。
- 1600×900 运行截图：`docs/v2/evidence/ui/feature-overview.png`。

## 已知限制

- 当前主视觉使用 Figma 导出的稳定本地资源；图标遵循 Figma 参考代码中的字形图标方案。
- 数据接入和指标管理完整后台不是本次 UI 复刻范围。
- 本地 Playwright 浏览器安装在 `frontend/.playwright-browsers`，目录已忽略，不写入 C 盘或 Git。

## 回滚

对本工作包提交执行 `git revert <commit>`。本轮无数据库变化，不需要 Alembic 回滚；Figma 静态资源与前端页面会随提交一并回滚。
