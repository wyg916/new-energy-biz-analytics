# V2-P0.5 数据接入治理工作包验收证据

> 验收日期：2026-07-29
> 数据边界：固定种子和业务规则驱动的模拟数据
> 阶段状态：V2-P0.5 核心验收项已实现并验证

## 1. 本工作包目标

在现有数据库驱动的数据源、字段映射和试运行能力之上，补齐：

```text
PostgreSQL 暂存批次
  → 8 条阻断型质量规则
  → 管理员提交审批
  → 审批通过/驳回
  → 受控发布版本
  → PostgreSQL 审计与前端状态展示
```

试运行完成不等于发布；质量失败、旧批次、未提交审批或未批准批次均不能发布。

## 2. 实现证据

- 迁移 `0005` 新增 `data_ingestion_quality_check` 与 `data_ingestion_review`；
- 每条规则记录规则 ID、名称、级别、结果、明细和校验时间；
- 工作流状态为 `quality_passed → pending_approval → approved → published`；
- 驳回需要原因，失败状态转换返回 409；
- 仅 `analyst_admin` 可执行质量、提交、审批和发布；
- 每个治理动作均写入 `audit_log`，不记录密码或 Token；
- 前端读取数据库工作流状态，显示 8 条质量规则和发布版本。

质量规则：

| 规则 | 说明 | 级别 |
|---|---|---|
| DQI-001 | 批次包含可发布数据 | 阻断 |
| DQI-002 | 关键字段完整 | 阻断 |
| DQI-003 | 场站主键唯一 | 阻断 |
| DQI-004 | 接入行数对账 | 阻断 |
| DQI-005 | 数值范围符合业务规则 | 阻断 |
| DQI-006 | 批次溯源与分类完整 | 阻断 |
| DQI-007 | SHA-256 源数据校验摘要存在 | 阻断 |
| DQI-008 | 受控结构不含直接身份字段 | 阻断 |

## 3. PostgreSQL 实际运行证据

本地 Docker Compose 的 PostgreSQL 16.9 实例最终完成：

- Alembic `0006 → 0005 → 0006`；
- 两张治理表实际创建；
- `charging_ops 0.1.0` 场景包发布并绑定 `SIM-20260722-v010-n300000`；
- 场景清单 SHA-256：`7950265c8d3d46ca22d23307b41b47579d1dbbafd527122f46e9ee10fc7f002b`；
- 接入运行：`ING-baa17d9b-e07b-45e1-bf2e-0a6c32aa42a8`；
- 写入 PostgreSQL 暂存数据 30 行；
- 质量结果 8/8；
- 提交状态 `pending_approval`；
- 审批状态 `approved`；
- 发布状态 `published`；
- 发布版本 `v2.0`；
- 固化不可变场站快照 30 行；
- 场站业务查询来源 `published_station_snapshot`；
- 数据分类 `simulated`。

这证明本地 Alpha 环境中的迁移和治理链路可执行，不代表企业生产环境上线。

## 4. 自动化测试

| 范围 | 结果 | 持久证据 |
|---|---:|---|
| 认证与生产配置 fail-closed | 6/6 | `phase-next-auth.xml` |
| SQL 安全与权限负向 | 15/15 | `phase-next-query-security.xml` |
| ChatBI、驾驶舱、诊断、记忆、指标、报告、收入 | 16/16 | `phase-next-backend-regression.xml` |
| 数据接入、质量、审批、发布、连接器安全 | 8/8 | `phase-next-data-integration.xml` |
| 后端最终全量回归 | 47/47 | `p0_5-final-backend.xml` |
| 前端 Vitest | 3/3 | 命令行验收记录 |
| TypeScript 与 Vite 生产构建 | 通过 | 命令行验收记录 |
| P0.5 专用 Playwright E2E | 1/1 | `data-integration-governance.png` |
| ChatBI 固定评测 | 40/40 | `tests/evaluation/output/chatbi_eval_v0.1.json` |
| Docker/API 烟测 | 6/6 | `tests/evaluation/output/docker_smoke.json` |
| 15 项指标迁移对账 | 15/15，差异 0 | `metric_baseline_before_scenario.json` |

## 5. 单屏 UI 验收

Chrome 以 1600×900、浏览器 100% 缩放验证：

- `html/body/product-shell` 均为 1600×900，无页面级滚动；
- 主工作区 1306×730，无横向或纵向溢出；
- 数据源、字段映射、5 行预览、映射配置与 8 条质量规则均完整可见；
- 浏览器控制台 error/warn 为 0；
- 页面显示“模拟数据”、数据时间、PostgreSQL 来源、`run_id` 和发布版本。

## 6. 合同冲突与范围边界

冻结的 `V2_P0_scope_and_acceptance.md` 将 MySQL 与 REST/API 列为 P0.5 禁止范围，
而项目负责人本轮明确要求 MySQL 为辅助连接验证、API 参与兼容性测试。
现有实现保留这两类连接测试，但不把它们计入 P0.5 验收，也不改变 PostgreSQL
为主存储的事实。若要将 MySQL/API 正式纳入 P0.5 产品范围，需要更新冻结范围与
验收合同，不能仅凭代码存在宣称范围已变更。

## 7. 阶段关闭情况

已关闭：

- `charging_ops` 已抽离为可导入、可版本化场景包；
- 已提供两份受版本控制的 CSV 样例，另有 Excel 连接器测试；
- 发布版本绑定不可变 PostgreSQL 快照；
- 完整覆盖授权场站和请求指标时，场站业务查询读取发布快照；
- 不完整或不匹配的快照不会覆盖底层已发布事实查询；
- 15 项指标迁移前后逐项一致；
- P0.5 专用 E2E 和仓库内截图已完成。

保留限制：当前场景包仍是模块化单体内的 Python 包，不是独立发布到外部包仓库的
制品；数据接入正式提升覆盖场站经营快照，底层会话、成本、设备事件事实仍绑定原
固定种子发布批次。两者均符合当前 Alpha 单实例与模拟数据边界。

## 8. 回滚

1. 应用代码执行 `git revert <P0.5 最终提交>`；
2. 仅回滚场景包和不可变快照执行 `docker compose exec api alembic downgrade 0005`；
3. 连同质量审批工作流回滚执行 `docker compose exec api alembic downgrade 0004`；
4. 降级不会删除原有模拟事实表，但会删除对应阶段新增的场景/快照或治理表；
5. 如需保留治理审计证据，应先导出新增表，再执行降级。
