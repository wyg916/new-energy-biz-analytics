# V2-P0.0 验收记录

## 1. 执行结论

**PASS**

Alpha 基线可复现，核心服务健康，主要测试全部通过，Alpha 标签正确，V2 分支安全建立，V2 v1.1 执行基线与 P0 范围完成，证据已固化。本阶段没有修改业务代码、指标口径、权限、安全链路或现有迁移。

## 2. 工作目录与 Git

| 项目 | 结果 |
|---|---|
| 工作目录 | `E:\新能源企业经营分析智能平台` |
| 起始分支 | `develop/alpha-fast-track` |
| 起始实际 HEAD | `1f6f2dc47bf99f4ecbb34d636b5efd5831a97d33` |
| 输入中的 Alpha 验收 HEAD | `1f580b6c251c0f20d4ed6927b4b60252b7deba8d` |
| 结束分支 | `feature/v2-productization` |
| P0.0 提交前基点 | `1f6f2dc47bf99f4ecbb34d636b5efd5831a97d33` |
| Alpha 标签 | `alpha-v1.0.0`，注释标签，指向 `1f580b6c...` |
| Remote | `origin = https://github.com/wyg916/new-energy-biz-analytics.git` |
| 已推送 | `develop/alpha-fast-track`、`alpha-v1.0.0` |

`1f6f2dc...` 是验收后追加的一键启动提交，不改变业务行为。为避免丢失用户已确认能力，V2 分支从该安全后继提交建立；Alpha 产品验收标签仍精确冻结在 `1f580b6...`。

## 3. Docker、API 与 Alembic

- 初始核查时 Docker daemon 未运行；启动位于 D 盘的 Docker Desktop 后，原数据卷和四个容器恢复，无镜像/数据卷删除。
- PostgreSQL、Redis、API 均为 running/healthy；Web 为 running，未配置容器 healthcheck，但 HTTP 200。
- API 健康检查 HTTP 200，响应 `status=ok`、`data_classification=simulated`。
- Web HTTP 200。
- Alembic current/head 均为 `0003`。
- 专用 schema `v2_p0_0_alembic_verify` 完成 upgrade→downgrade→re-upgrade，随后删除；业务 schema revision 仍为 `0003`。

## 4. 测试和评测真实结果

| 测试项 | 命令 | 通过 | 失败 | 跳过 | 耗时 | 结论 |
|---|---|---:|---:|---:|---:|---|
| 后端与覆盖率 | `pytest --cov=app --cov-report=term-missing` | 33 | 0 | 0 | 589.089s | PASS，89% |
| 前端测试 | `npm.cmd test` | 3 | 0 | 0 | 28.123s | PASS |
| 前端构建 | `npm.cmd run build` | 1 | 0 | 0 | 32.124s | PASS |
| Playwright P0 | `npm.cmd run e2e` | 1 | 0 | 0 | 141.975s | PASS |
| Docker 烟测 | `scripts/docker_smoke.py` | 6 | 0 | 0 | 9.515s | PASS |
| ChatBI 固定评测 | `scripts/run_chatbi_eval.py` | 40 | 0 | 0 | 2.676s | PASS |
| 危险 SQL | 精确 pytest 参数化用例 | 12 | 0 | 0 | 149.38s | 100% 拒绝 |
| Answer Guard 数字绑定 | 精确 ChatBI 链路用例 | 1 | 0 | 0 | 31.18s | 无依据数字 0 |
| 数据质量 | `validate_published_batch` | 20 | 0 | 0 | 16.919s | PASS，30 万会话 |
| npm audit | `npm audit --audit-level=low` | 0 漏洞 | 0 | 0 | 99.408s | PASS |
| Alembic 循环 | `scripts/verify_alembic_schema_cycle.py` | 4 | 0 | 0 | 35.012s | PASS |
| P0.0 页面证据 | 专用 Playwright spec | 1 | 0 | 0 | 31.483s | 9 张截图 |

完整命令、起止时间、退出码和计数见 `docs/v2/evidence/alpha/tests/test_run_summary.json`。

## 5. 与输入基线的差异

1. 输入称当前 HEAD 为 `1f580b6...`，实际为 `1f6f2dc...`；多出的提交仅为一键启动脚本。
2. 输入称 4 个服务仍在运行，初检时 Docker daemon 已停止；已恢复原容器和数据卷并重新验证健康。
3. 当前 Node 为 v24.18.0；旧报告记录为 v24.3.0。依赖锁文件未升级。
4. `docs/reference` 不存在；两份 Word 参考位于仓库根目录。
5. “产品功能架构与界面优化”Markdown 未找到。
6. 当前 Alpha 没有系统或审计前端路由；后端审计模型存在。
7. 本机无 LibreOffice/soffice，Word 文件完成结构化全文提取，未完成版式视觉复核。

其余核心测试数量、指标数量、数据规模、端口和能力边界与输入基线一致。

## 6. 新增或修改内容

- 新增 `docs/v2/` 正式执行基线、P0 范围、backlog、验收记录；
- 新增 `docs/v2/evidence/alpha/` Git、Docker、健康、OpenAPI、环境、测试和页面证据；
- 新增隔离 schema 迁移验证与证据采集脚本；
- 新增 P0.0 页面证据 Playwright spec；
- 纳入本轮提供的 V2 产品化 v1.0 Word 参考；
- 复跑正式评测后更新原 Alpha 评测时间戳与截图证据。

## 7. 业务代码与数据库影响

- 业务代码：未修改。
- 15 项指标：未修改。
- Query Plan、SQL Guard、Answer Guard、RBAC、审计：未削弱或修改。
- 数据库结构：无持久变化；测试 schema 已删除。
- 业务事实与 seed 数据：未删除、未重建、未修改。
- 正常审计影响：ChatBI、诊断、报告烟测按产品设计新增 `analysis_run`/审计记录；这些是可追溯验收请求，不是业务事实修改。

## 8. 敏感信息

- `.env` 未跟踪、未纳入提交；
- 未输出或提交真实数据库密码、Token、API Key 或企业数据；
- 仓库中的开发演示账号属于已声明的本地模拟环境，不是生产凭据；
- OpenAPI、Docker 状态和测试证据均未包含容器环境变量或连接串。

## 9. 已知限制与阻塞

阻塞项：无。

非阻塞限制：

- 系统/审计前端页面不存在；
- 第三份页面级 Markdown 参考缺失；
- Word 参考未进行 LibreOffice 视觉渲染；
- 当前仅证明本地 Compose 与模拟数据，不证明生产可用性。

## 10. 回滚

P0.0 文档和证据提交可使用：

```powershell
git switch feature/v2-productization
git revert <本阶段提交哈希>
```

Alpha 分支、`alpha-v1.0.0` 标签和远程备份作为封存证据保留。数据库无需 downgrade；本阶段没有持久迁移，验收 schema 已自动清理。

## 11. 下一阶段进入条件

本记录、机器验收 JSON、敏感信息检查和 P0.0 提交推送完成后，允许进入：

**V2-P0.1：公共产品框架和设计系统**

本轮不实施 V2-P0.1。

## 12. 本阶段 Git 提交

提交主题：`v2-p0.0: freeze alpha baseline and establish v2 execution control`

提交哈希在提交生成后以 `git log` 和最终交付回复为准；由于 Git 提交对象不能可靠地在自身内容中预写其最终哈希，本文件不伪造哈希。
