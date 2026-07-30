# 当前依赖与归属矩阵

## 后端

| 路径/对象 | 分类 | 当前依赖与结论 |
| --- | --- | --- |
| `app/core/config.py`、`database.py`、`logging.py`、`observability.py`、`security.py` | PLATFORM_CORE | 配置、数据库、日志、低基数监控和认证基础；角色名称仍带场景假设 |
| `app/api/router.py`、`api/dependencies.py` | PLATFORM_CORE | API 聚合、认证和授权依赖 |
| `app/models/auth.py` | MIXED | 通用用户/审计结构，但缺 tenant/org/workspace，角色枚举为当前产品固定值 |
| `app/models/business.py` | CHARGING_OPS | Region、City、Station、Device、ChargingSession、成本、费用、设备事件 |
| `app/models/integration.py` | MIXED | 数据源/数据集/质量/审批较通用；暂存和发布快照是 station 专用 |
| `app/services/data_integration.py` | MIXED | 连接试读和治理机制可抽取；标准字段、数据集、快照和看板预览绑定 charging_ops |
| `app/services/metrics.py`、`metric_catalog.py` | MIXED | 语义计算框架可抽取；15 个指标和事实表绑定 charging_ops |
| `app/services/dashboard.py`、`revenue.py`、`diagnostics.py`、`reports.py` | CHARGING_OPS | 充电经营聚合、规则诊断和报告草稿 |
| `app/chatbi/plan.py` | MIXED | Query Plan 形状可复用；指标/维度枚举绑定 charging_ops |
| `app/chatbi/parser.py`、`compiler.py` | CHARGING_OPS | 中文词典和 SQL 编译直接依赖充电事实表 |
| `app/chatbi/guard.py`、`executor.py` | PLATFORM_CORE 候选 | SQL AST 校验、超时/行数边界可复用；执行账户只读性尚未独立证明 |
| `app/chatbi/memory.py`、`service.py` | MIXED | 结构化会话机制可抽取；场景槽位和分析编排绑定 charging_ops |
| `app/scenarios/registry.py` | PLATFORM_CORE 候选 | 场景注册机制雏形 |
| `app/scenarios/charging_ops/manifest.py` | CHARGING_OPS | 当前唯一场景清单 |
| `app/data/seed.py`、`quality.py` | CHARGING_OPS | 模拟数据生成与充电业务质量规则 |

## 前端

| 路径/对象 | 分类 | 结论 |
| --- | --- | --- |
| `frontend/src/overview.tsx` | MIXED | 产品壳、认证会话与通用状态可抽取；页面和 API 强绑定 charging_ops |
| `revenue.tsx`、`metrics.tsx` 与对应样式 | CHARGING_OPS | 充电经营页面和指标治理展示 |
| `main.tsx` 中未挂载的旧组件 | DEAD_OR_STALE | 真实入口只挂载 `ProductApp`；旧 App/Dashboard 等增加误读风险，P1 再安全清理 |
| `frontend/e2e/*.spec.ts` | MIXED | 业务验收可用，但将截图写入跟踪证据目录属于测试副作用，需本轮修复 |

## 数据与部署

| 对象 | 分类 | 结论 |
| --- | --- | --- |
| Alembic `0001`、`0003`、认证/审计/analysis_run | PLATFORM_CORE 候选 | 可复用但需要 tenant/workspace 演进 |
| `0002`、`0006` 业务与发布快照 | CHARGING_OPS | 充电场景表 |
| `0004`、`0005` 接入治理 | MIXED | 通用骨架与 station 专用字段共存 |
| `deploy/private/*`、`scripts/private_deployment.py` | PLATFORM_CORE | 单主机私有部署和恢复工具，不等于多租户生产平台 |
| `.github`/CI | 缺失 | 尚无仓库 CI/CD 门禁 |

## 关键耦合链

`DataIntegrationService → 固定 station mapping → StagingStationRecord/PublishedStationSnapshot → DashboardService.station_analysis`

`ChatBI parser → charging_ops 枚举 → deterministic compiler → 充电事实表 → Query Guard → executor`

`ReportService/DiagnosticsService/DashboardService → 同一指标服务但不统一依赖 ACTIVE DatasetVersion`

