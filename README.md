# 新能源企业经营分析智能平台（产品级 Alpha）

> 状态：Phase 1—8 已实现并完成自动化验收。
>
> 数据边界：仅使用固定种子生成的模拟数据；未接入企业真实数据，不代表生产部署或真实经营收益。

本项目是面向新能源充电运营的模块化单体经营分析平台。它以统一的 15 项指标语义层为基础，提供数据库驱动的经营驾驶舱、受控 ChatBI、有限多轮会话状态、异常与经营拆解，以及可回溯的周报/月报草稿。

可信问数链路固定为：

```text
自然语言 → Query Plan → 确定性参数化 SQL → Query Guard
          → 只读执行 → 结构化结果 → Answer Guard → 证据面板
```

系统不开放自由 SQL，不包含多 Agent、自动交易、自动邮件/工单、生产级多租户、SSO 或真实企业数据接入。

## Docker Compose 启动（推荐）

前置：Docker Desktop / Docker Engine 与 Compose v2。

Windows 用户可直接双击根目录的 [`一键启动.bat`](一键启动.bat)。脚本会检查 Docker、创建本地 `.env`、构建并启动四个服务、幂等生成完整模拟数据，成功后打开产品页面。成功或失败时窗口都会停留，不会闪退；首次生成 30 万条会话可能需要数分钟。

也可以手动执行：

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose exec api python -m app.data.seed --session-count 300000
```

- Web：<http://localhost:8080>
- API 文档：<http://localhost:18000/docs>
- 健康检查：<http://localhost:18000/api/v1/health>
- 开发演示用户：`admin / AlphaAdmin!2026`、`analyst / AlphaAnalyst!2026`、`regional / AlphaRegion!2026`

以上账号只在 `APP_ENV=development` 且 `AUTO_BOOTSTRAP_DEMO_USERS=true` 时创建。生产配置使用示例密钥、空密钥或自动演示账号会 fail-closed。

数据生成具有幂等批次保护：相同批次会返回现有计数，非空数据库不会混入另一模拟批次。完整批次为 `SIM-20260722-v010-n300000`，覆盖 2025-01-01 至 2026-06-30。

## 验证

后端（Python 3.11）：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.lock
Push-Location backend
..\.venv\Scripts\python -m pytest --cov=app --cov-report=term-missing
Pop-Location
.\.venv\Scripts\python scripts\run_chatbi_eval.py
.\.venv\Scripts\python scripts\docker_smoke.py
```

前端（Node 24）：

```powershell
npm.cmd ci --prefix frontend
npm.cmd test --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd audit --prefix frontend
npm.cmd run e2e --prefix frontend
```

2026-07-22 的 Alpha 验收结果：后端 33/33（覆盖率 89%）、前端 3/3、固定评测 40/40、危险 SQL 12/12 拒绝、数据质量 20/20、容器烟测 6/6、Playwright 1/1、npm 已知漏洞 0。详情见[测试与评测报告](docs/test_and_evaluation_report.md)。

2026-07-29 的 V2-P0.5 新增了数据库批次质量校验、管理员审批、受控发布、
`charging_ops 0.1.0` 场景包和不可变场站快照。回归结果为后端 47/47、前端
3/3、P0.5 E2E 1/1、固定评测 40/40、烟测 6/6；15 项指标迁移前后差异为 0，
PostgreSQL 迁移完成升级/降级/再升级，1600×900 页面无滚动与溢出。详见
[V2-P0.5 工作包证据](docs/v2/evidence/p0_5/README.md)。

## 目录

```text
backend/                    FastAPI、SQLAlchemy、Alembic、业务服务与 pytest
frontend/                   React、Vite、Vitest、Playwright、Nginx
docs/                       冻结合同、架构、阶段验收和作品证据
scripts/                    固定评测和容器烟测
tests/evaluation/           40 题金标集与机器可读运行结果
docker-compose.yml          PostgreSQL、Redis、API、Web 统一编排
```

## 证据与限制

- [Alpha 实现架构](docs/architecture_alpha.md)
- [测试与评测报告](docs/test_and_evaluation_report.md)
- [Phase 8 / Alpha 验收](docs/phase_8_acceptance.md)
- [作品证据与表述边界](docs/portfolio_evidence.md)
- [页面截图](docs/evidence/README.md)
- [已批准产品范围](docs/project_scope_baseline.md)
- [15 项指标合同](docs/metric_dictionary_v0.1.md)
- [Query Plan 合同](docs/query_plan_contract_v0.1.md)
- [安全合同](docs/rbac_and_sql_security_contract_v0.1.md)
- [V2 产品化正式执行基线 v1.1](docs/v2/V2_productization_execution_baseline_v1.1.md)
- [V2 P0 范围与验收清单](docs/v2/V2_P0_scope_and_acceptance.md)
- [V2-P0.0 验收记录](docs/v2/V2_P0_0_acceptance.md)
- [V2-P0.0 Alpha 证据](docs/v2/evidence/alpha/README.md)

当前已知限制：自然语言解析为合同范围内的确定性中文规则，不是开放域大模型；会话记忆仅限结构化短期状态；报告导出为 Markdown/CSV 草稿；Compose 是单机 Alpha 部署，不包含高可用、备份编排或生产运维承诺。

## 回滚

应用按 Phase 提交逆序执行 `git revert <commit>`；数据库在对应代码版本下执行 `docker compose exec api alembic downgrade <revision>`。迁移已验证 `upgrade → downgrade → re-upgrade`。停止服务使用 `docker compose down`；只有明确接受删除项目专用模拟数据库时才使用 `docker compose down -v`。

## 真实性声明

可以表述为“产品级 Alpha、已实现并在模拟数据和本地 Compose 环境验证”。不得表述为生产上线、真实客户使用、接入真实企业数据或产生真实经营收益。
