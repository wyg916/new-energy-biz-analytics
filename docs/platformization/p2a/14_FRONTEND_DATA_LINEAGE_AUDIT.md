# 前端全量审计与数据链路改造验收记录

更新时间：2026-07-31
工作包：Frontend Data Lineage / Phase 1
基线提交：`2117a87`

## 1. 目标、范围与非目标

### 目标

- 业务页面不再重复展示“模拟数据、真实数据、数据来源”等说明；
- 数据性质、数据时间、平台来源和 `run_id` 只在全局固定状态区统一展示；
- 页面业务值、指标定义、场景问题、日期默认值和趋势图均来自数据库事实或后端 API；
- 缺失业务数据必须先写入 PostgreSQL，再经权限过滤、语义层和后端 API 返回；
- 数据或已发布批次不可用时 fail-closed，不使用前端随机数、静态结果或跨域 fallback。

### 非目标

- 不把模拟数据伪装成企业真实数据；
- 不改变 Alpha 固定随机种子、数据期或 15 项 P0 核心指标；
- 不开放自由 SQL；
- 不改变 SQLBot、RAG、P2B 或生产发布准入结论；
- 不接入真实企业数据、密钥或生产连接串。

## 2. 审计结论

前端可执行入口已经收敛为 `main.tsx → ProductApp`。旧版未渲染 Dashboard、
重复数据说明和静态业务展示代码已移除。

对 `frontend/src` 的静态复核结果：

- “模拟数据/真实数据/数据来源”只剩全局状态区的一个受控映射；
- 不存在硬编码的 2025—2027 业务查询日期；
- 不存在原静态折线数组、静态指标定义、静态来源表映射或场景初始问题；
- 数据接入页保留“来源表”等治理功能字段，因为它们是管理员核验字段，不是数据真实性宣传；
- Blocked、Query Guard、Answer Guard、治理发布状态和因果边界继续显示。

## 3. 页面—API—数据库链路

| 前端页面 | 主要后端链路 | 数据库事实 / 受控状态 | 审计结果 |
|---|---|---|---|
| 全局状态区 | `GET /api/v1/dashboard/context`、Dashboard 响应元数据 | `data_generation_run`、`metric_definition`、`analysis_run` | 数据期、15 项指标、批次和运行标识由数据库返回；无发布批次时 409 |
| 功能总览 / 经营工作台 | `/dashboard/summary`、`/dashboard/trend`、`/dashboard/stations`、`/diagnostics/decomposition` | `fact_charging_session`、成本事实、场站维表、指标语义层 | KPI、趋势、贡献与场站排行均来自 API；已移除静态趋势形状 |
| 收入与订单 | `/revenue/analysis`、Dashboard API | 充电会话、场站维表、指标定义 | 当前期、基期、构成和排行均来自数据库查询 |
| 毛利与成本 | `/diagnostics/decomposition`、`/dashboard/trend` | 充电、电费成本、可变运营成本事实 | 筛选重置使用后端取得的初始数据期，不再硬编码日期 |
| 场站经营 | `/dashboard/summary`、`/dashboard/stations`、`/dashboard/trend` | 场站、城市、区域、充电与成本事实 | 排名、分布、趋势和详情均由 API 返回 |
| 设备健康 | `/dashboard/devices`、`/dashboard/trend` | `dim_device`、`fact_device_status_event` | 在线率、故障率、事件和趋势均由数据库计算 |
| 经营预警 | `/diagnostics/decomposition`、`/diagnostics/anomalies` | 结构化指标结果、规则结果、`analysis_run` | 无前端伪造告警；保留相关性不等于因果的边界 |
| AI 经营分析 | `/chat/scenarios`、`/assistant/query`、Dashboard 上下文 API | 场景注册、语义版本、Query Plan、QueryResult、会话状态和运行证据 | 初始/推荐问题来自后端；查询日期由全局数据库数据期派生；结论不重复数据性质 |
| 经营报告 | `/reports/draft`、`/reports/export`、Dashboard API | 已验证结构化结果、分析运行和报告草稿 | 报告只引用 API 结果；仍为可审核草稿 |
| 企业知识库 | `/knowledge/runtime`、`/knowledge/documents`、版本与检索 API | knowledge 六表、ACL、发布/撤回/回滚事件 | 生命周期、运行状态和检索证据由数据库/API 返回 |
| 数据接入与字段映射 | `/data-integration/*`、`/platform/foundation/*` | 数据源、导入运行、质量、审核、发布、激活、回滚和快照表 | 业务数据解析后先写 PostgreSQL；失败时 Blocked 且无 fallback |
| 指标与场景管理 | `/dashboard/metric-catalog` | `metric_definition`、语义模型与场景包 | 15 项指标定义、业务域、源表、粒度、类型和维度标签来自数据库 |

## 4. 数据库与迁移

新增可回滚迁移 `0015_frontend_data_lineage.py`，在 `metric_definition` 增加：

- `business_domain`
- `definition`
- `source_tables_json`
- `supported_grains_json`
- `metric_type`

迁移兼容空库安装和已有库升级，升级时只补充缺失列并回填 15 项已发布指标；
降级时通过 batch alter 逆序移除新增列。

当前本地验收数据库：

- Alembic：`0015 (head)`
- `metric_definition`：15 行
- 业务域、定义、源表回填：15/15
- `fact_charging_session`：300000 行，改造未改变核心事实行数

独立 PostgreSQL 迁移循环已验证：

- base → head：PASS
- head → base：PASS
- base → head again：PASS
- 临时验收数据库已移除
- 既有业务卷未删除

## 5. 安全与真实性影响

- 所有新增接口继续要求认证；
- 数据权限仍在查询前执行，未引入前端直连数据库；
- 前端无随机数业务结果、无本地 mock、无业务 fallback；
- 数据集缺失时 `PUBLISHED_DATASET_NOT_READY` fail-closed；
- Query Guard、Answer Guard、只读执行和报告证据边界未被绕过；
- 全局状态区仍如实显示当前 Alpha 数据性质、数据时间、平台来源和 `run_id`，
  不把模拟数据表述为真实生产数据。

## 6. 测试与验收证据

| 验收项 | 结果 |
|---|---|
| 前端生产构建 | PASS，41 modules |
| Vitest | 3/3 PASS |
| Playwright 全量 | 21/21 PASS |
| 最终受影响页面复验 | 4/4 PASS |
| 新增 11 页面数据链路 E2E | PASS |
| 后端上下文正向、fail-closed、双场景目录 | 3/3 PASS |
| Python compileall | PASS |
| Alembic 隔离全循环 | PASS |
| 运行中 Compose | db / redis / api healthy，web running |
| `git diff --check` | PASS |

一次性 Compose pytest 容器在用例收集后阻塞且未返回断言结果；未把该次运行记为
PASS。相同目标用例随后在仓库内 E 盘 `.venv` 和隔离 SQLite 测试库中通过 3/3。

## 7. 已知限制与风险

- 当前数据仍是 Alpha 固定种子和业务规则驱动的模拟数据，不是企业生产数据；
- 页面统一状态区为真实性边界，不得在后续改版中隐藏或移除；
- 指标展示元数据当前由版本化迁移和种子逻辑发布，后续应进入管理员审批界面；
- SQLBot 真实模型、完整 Shadow、向量检索和 P2B 准入仍沿用 P2A 的
  `CONDITIONAL / NOT_ALLOWED` 结论；
- 未执行不可逆迁移，未删除业务卷，未接入外部真实数据。

## 8. 回滚

应用代码回滚：

```text
git revert <本工作包提交>
```

数据库回滚：

```text
docker compose exec -T api alembic downgrade 0014
```

回滚前必须确认没有下游代码依赖五个新增字段。回滚不会删除 15 项指标记录或核心
业务事实，但会移除本阶段新增的指标展示元数据列。

## 9. 阶段结论

`FRONTEND_DATA_LINEAGE_PHASE_1 = PASS`

允许进入下一阶段，但不改变 `P2B_ENTRY = NOT_ALLOWED`、生产发布禁令和真实数据
接入禁令；下一阶段只能在现有真实性、安全和数据库先行边界内继续。
