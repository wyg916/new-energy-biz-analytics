# P2A Runtime 测试与验收矩阵

更新时间：2026-07-31

## 1. Runtime 门禁

| 项目 | 当前执行结果 | 判定 |
|---|---|---|
| SQLBot 固定镜像 | v1.8.0，根路径 HTTP 200，healthy，restart=0 | PASS |
| Provider 官方文档 | 8 个指定页面 HTTP 200；Kimi 端点/Auth 正文匹配 | PASS |
| Provider 真实直连 | 三家 DNS PASS；`/models` 均 HTTP 401；MiMo 两种 Header 均 401 | NOT_PASS |
| Model Gateway 发现 | 配置完整，但实际发现模型 0、可用 Provider 0 | NOT_PASS |
| SQLBot 模型列表 | 正式 API HTTP 200，配置数量 0 | PENDING |
| Datasource | charging_ops ID 1、sales_ops ID 2，正式 API HTTP 200 | PASS |
| 只读连接 | 2/2，Schema/View/字段/预览通过 | PASS |
| 负向安全 | dangerous/cross-scenario/public-base 成功数均为 0 | PASS |
| statement timeout | 2/2 在约 3000 ms 取消 | PASS |
| 10 条 live Smoke | 0/10，PROVIDER_AUTHENTICATION_FAILED | NOT_EXECUTED |
| 100 条 live Golden | 0/100，未把离线结果计入 | NOT_EXECUTED |
| 20 条真实 Shadow | 0/20 | NOT_EXECUTED |
| 故障降级 Shadow | 确定性主答案 20/20，错误证据 20/20 | PASS |
| pgvector | PostgreSQL 16.9 镜像无 vector 扩展 | PENDING |
| SBOM/CVE | 1,040 包；11 Critical、174 High 命中 | CONDITIONAL |

## 2. 当前分支回归

| 测试 | 命令/边界 | 结果 |
|---|---|---|
| 后端全量 | 35 文件、单进程共享内存 SQLite、源码只读挂载 | 174/174 PASS |
| Runtime blocker + Live Provider validator 专项 | 当前补丁与脱敏分支 | 9/9 PASS |
| Deterministic 固定评测 | `run_chatbi_eval.py` | 40/40 PASS |
| 双引擎离线合同 | `run_dual_engine_eval.py` | 100/100 PASS；runtime 指标仍为 null |
| charging_ops 指标对账 | `verify_p0_5_metric_reconciliation.py` | 15/15，differences={} |
| sales_ops 指标对账 | `verify_sales_ops_metric_reconciliation.py` | 12/12，differences={} |
| PostgreSQL DQ | `validate_published_batch` | 20/20，failures=[] |
| Query Security | 当前后端分组 | 15/15 PASS |
| SQLBot 只读角色 | 实际 PostgreSQL 负向脚本 | 2 角色 PASS，禁止成功数 0 |
| Alembic | 独立 PostgreSQL `current` + `check` | 0014 head；无新增升级操作 |
| Docker smoke | 隔离 API，受信 Host Header | 6/6 PASS |
| Vitest | `npm.cmd test` | 3/3 PASS |
| 生产构建 | `npm.cmd run build` | PASS |
| Playwright | 隔离 URL `127.0.0.1:18083`，单 worker | 20/20 PASS，3.2 min |
| npm audit | `--audit-level=high` | 0 vulnerabilities |
| Live Provider validator | 脱敏、成功/失败、MiMo 双 Header、模型选择 | 5/5 PASS |

本轮最终全量通过一次性容器读取当前 worktree，使用单进程共享内存 SQLite；
174/174 覆盖原 168 项及本轮新增的 6 项 Provider/阻断证据测试，不跳过或弱化
任何断言。只读挂载导致 pytest cache 写入警告，不影响测试、业务数据或退出码。

Docker smoke 首次以容器 DNS 名作为 Host 时由 TrustedHostMiddleware 正确返回
400；按脚本已支持的 `DOCKER_SMOKE_HOST_HEADER=127.0.0.1` 设置受信 Host 后
6/6 通过。该环境调整不属于业务失败重跑。

## 3. 真实性与秘密检查

- live `/models` 在探索、凭据文件更新复核和固化脚本阶段进行了有界重试；三家
  最终状态一致为 HTTP 401，MiMo 同时复核 Bearer 与 `api-key`。live completion
  调用数 0；Mock Provider 计入 live 指标数 0；
- live SQL 生成数：0；live SQLBot 查询数：0；
- 未授权模型上下文发送数：0；
- 新增明文秘密数：0；
- 原工作区未跟踪用户文件读取/修改/暂存/提交数：0；
- 运行大体积 JSON、SBOM、SARIF、Token 和完整模型响应提交数：0。

## 4. 运行命令摘要

```text
pytest（35 文件，单进程共享内存 SQLite）
python /scripts/run_chatbi_eval.py
python /scripts/run_dual_engine_eval.py
python /scripts/record_blocked_runtime_evaluation.py ...
python scripts/validate_live_model_providers.py --output .cache/p2a-runtime/live-provider-validation.json
python /scripts/verify_p0_5_metric_reconciliation.py
python /scripts/verify_sales_ops_metric_reconciliation.py
validate_published_batch(SessionLocal())
python /scripts/docker_smoke.py
python /tmp/verify_readonly_roles.py
alembic current
alembic check
npm.cmd test
npm.cmd run build
npm.cmd run e2e
npm.cmd audit --audit-level=high
docker scout sbom ...
docker scout cves ...
```

## 5. 验收结论

```text
MODEL_RUNTIME=NOT_PASS
MODEL_RUNTIME_BLOCKER=PROVIDER_AUTHENTICATION_FAILED
SQLBOT_DATASOURCE_RUNTIME=CONDITIONAL
SQLBOT_QUERY_RUNTIME=NOT_PASS
SQLBOT_GOLDEN_RUNTIME=NOT_PASS
SQLBOT_SHADOW=NOT_PASS
SQLBOT_CANARY=NOT_ELIGIBLE
RAG_VECTOR=PENDING
SBOM_SCAN=CONDITIONAL
P2A_RUNTIME_CLOSEOUT=NOT_PASS
```

Provider、base URL、preferred model 和凭据引用已经齐全。解除阻塞需要修复或
更换至少一家能通过官方认证的仓库外凭据/账户授权；Secret 仍只可注入不跟踪
运行环境。
