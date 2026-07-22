# Alpha 测试与评测报告

> 执行日期：2026-07-22；环境：Windows + Python 3.11.9 + Node 24.3.0 + Docker Compose。

## 最终结果

| 验收项 | 结果 | 证据 |
|---|---:|---|
| 后端 pytest | 33/33 通过，89% 覆盖率 | `tests/evaluation/output/backend-junit.xml` |
| 前端 Vitest | 3/3 通过 | `frontend/tests/format.test.ts` |
| 前端生产构建 | 通过 | `npm run build` |
| 前端依赖审计 | 0 个已知漏洞 | `npm audit --audit-level=low` |
| ChatBI 固定评测 | 40/40，100% | `tests/evaluation/output/chatbi_eval_v0.1.json` |
| 危险 SQL | 12/12 拒绝，100% | `backend/tests/test_query_security.py` |
| 数据质量 | DQ-001—DQ-020，20/20 | `tests/evaluation/output/data_quality.json` |
| 容器 API 烟测 | 6/6 | `tests/evaluation/output/docker_smoke.json` |
| Playwright P0 旅程 | 1/1 | `frontend/e2e/alpha.spec.ts`、页面截图 |
| Alembic 空库迁移 | upgrade → downgrade → re-upgrade 通过 | `tests/evaluation/output/fresh_environment_acceptance.json` |

后端用例覆盖认证、401/403、生产 fail-closed、数据生成与质量、15 项指标对账、驾驶舱、Query Plan/Compiler/Guard、ChatBI/Answer Guard、会话隔离与覆盖、异常和拆解、报告回溯与导出。测试未被跳过或删除。

## 完整模拟数据验收

最终批次 `SIM-20260722-v010-n300000`：3 区域、6 城市、30 场站、120 设备、10,000 用户、546 日期、300,000 会话、65,520 设备状态、65,520 电力成本、65,520 运营费用、15 指标。固定 seed 为 `20260722`，时间为 2025-01-01 至 2026-06-30。

DQ-001—DQ-020 全部为 true，覆盖主键唯一、完成订单、外键、层级、时间范围、金额/功率、会话重叠、设备状态、成本计算、容量、能量对账、日期覆盖、规模、场景、模拟来源、隐私字段和批次发布状态。

完整 PostgreSQL 数据生成的前两次尝试暴露了 SQLite/PostgreSQL 时区表达式差异；修正强类型时区边界及按上海时区聚合后，第三次生成与 20 项规则全部通过。失败没有被忽略，未发布混合批次。

## ChatBI 与安全

固定评测文件没有按题号硬编码答案，运行器依据实际解析出的 Query Plan 与金标子集比较。40/40 包含指标、过滤、时间、比较、歧义和拒绝样例。Answer Guard 的无依据业务数字测试通过，因此验收观测值为 0。

12 条危险 SQL 语料覆盖 DROP、DELETE、UPDATE、INSERT、TRUNCATE、多语句、文件读取、系统表、延时函数、注释绕过和 COPY PROGRAM，拒绝率 100%。区域越权容器烟测返回 403。

## 冷环境与浏览器

在新建 Compose 数据卷上完成镜像构建、空库迁移、downgrade/re-upgrade、完整 seed、质量规则、API 烟测和浏览器旅程。Web 使用 `:8080`，API 使用宿主 `:18000`（容器内 `:8000`），避开本机已有且不属于本项目的 `:8000` 进程。

Playwright 从登录开始，经驾驶舱、ChatBI、异常诊断到报告草稿，全部请求真实 API；核心旅程 1/1 通过并生成 5 张截图。

## 复现命令

命令见根目录 `README.md`。机器可读结果位于 `tests/evaluation/output/`；截图位于 `docs/evidence/screenshots/`。
