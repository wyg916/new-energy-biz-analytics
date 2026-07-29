# V2-P0.6 私有化部署与发布候选验收

> 验收日期：2026-07-29
> 发布候选：`0.6.0-rc1`
> 数据边界：固定随机种子模拟数据
> 部署边界：单客户、单主机、Docker Compose

## 1. 完成范围

- 独立私有化 Compose，数据库、Redis、API 不发布宿主机端口；
- Nginx TLS 1.2/1.3、HTTP 308 跳转、HSTS、CSP、Frame/Content-Type 安全头；
- 生产配置 fail-closed：拒绝弱密钥、HTTP 来源、通配 Host、开发版本和演示账户；
- 数据库/Redis/Alembic revision 就绪探针；
- 低基数 Prometheus 文本指标，仅在 Docker 私有网络采集；
- 请求级 JSON 日志，包含 request_id、方法、路径、状态和耗时，不记录查询参数或凭据；
- PostgreSQL custom-format 备份、SHA-256 清单和专用 schema 完整恢复演练；
- 动态 Alembic `head → previous → head` 升级回滚验证；
- 冷环境安装、监控快照和机器可读 RC 验收汇总。

## 2. 实际验收结果

| 门禁 | 结果 |
|---|---:|
| 后端 pytest | 60/60 |
| 前端 Vitest | 3/3 |
| 前端构建 | PASS |
| Playwright 全量 E2E | 13/13 |
| ChatBI 固定评测 | 40/40 |
| Docker smoke | 6/6 |
| npm audit | 0 个已知漏洞 |
| 冷环境安装 | 4/4 服务 healthy |
| HTTP → HTTPS | 308 |
| HTTPS readiness | 200 / ready |
| 外部 metrics | 404 |
| 迁移升级/回滚/再升级 | `0006 → 0005 → 0006` |
| 备份恢复 | 25 张表、507,283 行、业务指纹一致 |

冷安装使用全新 Compose project `renewable-rc-p06-cold2` 和全新命名卷。首轮
`renewable-rc-p06-cold` 因容器内 `localhost` 优先解析到 IPv6 导致 Web
健康检查误报；修复为 `127.0.0.1` 后使用第二个全新 project 重新执行，未把
补启动结果冒充冷安装。首轮和第二轮数据卷均未删除。

备份来源在隔离 RC 实例中装载固定种子批次
`SIM-20260722-v010-n300000`：300,000 会话、3 个区域、30 个场站、120 台设备。
恢复到随机 `rc_restore_*` schema，核对全部表行数、核心费用/电量指纹、
场景清单和 Alembic revision 后删除该专用 schema；原 `public` schema 和数据卷
未删除。

## 3. 机器证据

- [`preflight.json`](preflight.json)：配置、TLS、端口和生产门禁预检；
- [`cold-install.json`](cold-install.json)：全新环境安装和 HTTPS 验收；
- [`backup.json`](backup.json)：备份格式、大小、SHA-256、表行数与业务指纹；
- [`restore-drill.json`](restore-drill.json)：恢复对账和隔离 schema 清理；
- [`monitor.json`](monitor.json)：服务健康、就绪、指标和备份新鲜度；
- [`migration-rollback.json`](migration-rollback.json)：迁移升级/回滚/再升级；
- [`backend.xml`](backend.xml)：60 项后端 JUnit；
- [`e2e.json`](e2e.json)：13 项 Playwright 全量结果；
- [`rc-acceptance.json`](rc-acceptance.json)：全部门禁汇总。

固定评测和 smoke 证据继续位于：

- [`tests/evaluation/output/chatbi_eval_v0.1.json`](../../../../tests/evaluation/output/chatbi_eval_v0.1.json)
- [`tests/evaluation/output/docker_smoke.json`](../../../../tests/evaluation/output/docker_smoke.json)

## 4. 执行命令

```powershell
.\.venv\Scripts\python.exe scripts\private_deployment.py preflight
.\.venv\Scripts\python.exe scripts\validate_private_cold_install.py --project-name <new-project>
.\.venv\Scripts\python.exe scripts\private_deployment.py backup --output-dir <backup-dir>
.\.venv\Scripts\python.exe scripts\private_deployment.py restore-drill --backup <file> --manifest <file>
.\.venv\Scripts\python.exe scripts\private_deployment.py monitor --backup-manifest <file>
.\.venv\Scripts\python.exe scripts\verify_alembic_schema_cycle.py
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd test --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run e2e --prefix frontend
.\.venv\Scripts\python.exe scripts\run_chatbi_eval.py
.\.venv\Scripts\python.exe scripts\docker_smoke.py
```

运行时密码、证书私钥和 `.env` 均位于 Git 忽略目录，未进入证据或提交。

## 5. 限制与真实性

- 这是本地单机 Compose 发布候选验证，不是企业生产上线；
- 未使用企业真实业务数据，未验证真实客户、生产 SLA 或经营收益；
- 未验证 Kubernetes、高可用、跨主机灾备、共享多租户或 SSO；
- 自签证书只用于本地 RC 演练，真实交付必须使用客户批准的受信证书；
- 冷安装默认不创建演示账户、不自动生成业务数据；本次 30 万模拟会话是在冷安装
  验收完成后，仅为备份恢复演练显式装载。

## 6. 回滚

- 代码：`git revert <P0.6提交>`；
- 数据库：使用对应旧应用版本执行 `alembic downgrade <旧revision>`；
- 应用：恢复上一个已验证镜像标签并 `docker compose up -d`；
- 禁止使用 `docker compose down -v` 作为升级或回滚步骤；
- 若新版本已写入旧 schema 无法表达的数据，停止自动回滚并使用已验证备份流程。
