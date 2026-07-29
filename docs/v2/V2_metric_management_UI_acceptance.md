# 指标与场景管理 UI 验收记录

## 目标与范围

- 参考 Figma：`WieV5jUrSEpj7El8umwoVe`，节点 `3:2`。
- 参考图：`UI界面参考图/指标与场景管理.png`。
- 在 1600×900、浏览器 100% 缩放下完整展示指标管理主页，不产生页面级纵向或横向滚动。
- 页面读取当前数据库 `metric_definition` 中的 15 项 P0 冻结指标，不复用参考图中的虚构数量。

## 完成内容

- 四张目录概览卡：指标总数、业务场景、允许维度、本期变更。
- 指标管理标签页、左侧指标目录与标签、中央筛选工具栏和 8 条/页列表、右侧指标详情和场景应用预览。
- 支持指标名称/编码搜索、业务域筛选、重置、行选择与详情联动。
- 新建、导入、编辑等写操作保持只读边界，并明确提示需管理员或指标负责人审批。
- 页面底部固定展示“模拟数据”、数据时间、来源、`run_id` 和目录版本。

## 数据库与安全影响

- 无 Schema 或迁移变更。
- 新增只读接口 `GET /api/v1/dashboard/metric-catalog`。
- 接口需要登录鉴权，读取已发布指标定义，并写入成功审计日志。
- 不开放自由 SQL，不新增组织规则发布能力，不接入真实企业数据。

## 验收证据

- 页面截图：`docs/v2/evidence/ui/metric-management.png`。
- 后端契约：`backend/tests/test_metric_catalog.py`。
- 前端一屏与交互验收：`frontend/e2e/metric-management.spec.ts`。
- E2E 同时检查文档尺寸、页面和工作区底部、四个主面板的横纵向溢出。

## 测试结果

- `python -m pytest tests/test_metric_catalog.py -q`：2/2 通过。
- `npm.cmd run build`：通过。
- `playwright test e2e/metric-management.spec.ts`：1/1 通过。

## 限制与回滚

- 本工作包只完整落地“指标管理”主页；业务场景、数据视图、权限规则标签保留产品边界提示，不宣称为已完成的写入工作流。
- 参考图中的 1,268 项指标、86 个场景等为设计模拟值，产品实现按已冻结事实展示 15 项指标和 1 个 `charging_ops` 场景。
- 回滚时移除指标目录路由、服务方法、`metrics.tsx`/`metrics.css` 入口和对应测试、证据文件即可；无数据库回滚动作。
