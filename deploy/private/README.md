# 单客户私有化部署与 RC 运维指南

> 适用范围：单客户、单主机、Docker Compose、固定种子模拟数据。
> 已验证不等于企业生产上线；本基线不包含 Kubernetes、高可用、多租户或 SSO。

## 1. 前置条件

- Docker Engine / Docker Desktop 与 Compose v2；
- 至少 4 CPU、8 GiB 内存和 30 GiB 可用磁盘；
- 客户提供的 DNS、TLS 证书 `tls.crt`、私钥 `tls.key`；
- 仅在部署主机保存的 `private.env`，权限应限制给运维账户；
- 发布包或已审阅的仓库提交。

数据库、Redis 和 API 不发布宿主机端口，唯一公开入口是 Nginx 的 HTTP/HTTPS 端口。HTTP 仅用于 308 跳转。

## 2. 配置

```powershell
Copy-Item deploy/private/private.env.example deploy/private/private.env
```

必须替换：

- `POSTGRES_PASSWORD` 与 `DATABASE_URL` 中的数据库密码，二者必须一致；
- 至少 32 字符的随机 `SECRET_KEY`；
- `PUBLIC_BASE_URL`、`CORS_ORIGINS` 和 `TRUSTED_HOSTS`；
- `TLS_DIR`，目录中必须存在 `tls.crt` 和 `tls.key`；
- `RELEASE_VERSION` 与 `EXPECTED_DATABASE_REVISION`。

生产配置使用占位值、弱密码、HTTP 来源、通配 Host、开发版本或自动演示账户时会 fail-closed。

本地 RC 验证可生成短期自签证书，不能把它用于真实交付：

```powershell
.\scripts\New-RcSelfSignedCertificate.ps1 `
  -OutputDirectory E:\private-runtime\tls `
  -DnsName localhost
```

## 3. 安装与启动

先执行不输出密钥的预检：

```powershell
.\.venv\Scripts\python.exe scripts\private_deployment.py `
  --env-file deploy\private\private.env `
  preflight
```

启动：

```powershell
docker compose `
  --env-file deploy/private/private.env `
  -f deploy/private/docker-compose.private.yml `
  up -d --build
```

验收：

```powershell
docker compose `
  --env-file deploy/private/private.env `
  -f deploy/private/docker-compose.private.yml `
  ps
```

- `db`、`redis`、`api`、`web` 必须为 `running/healthy`；
- `https://<host>/api/v1/health/ready` 必须返回 `ready`；
- 就绪结果应显示当前发布版本和数据库 revision；
- 生产启动不会创建演示账户，也不会自动生成模拟业务数据。

## 4. 备份与恢复演练

备份使用 PostgreSQL custom format，生成独立 SHA-256 清单，不在清单或日志中写入凭据：

```powershell
.\.venv\Scripts\python.exe scripts\private_deployment.py `
  --env-file deploy\private\private.env `
  backup --output-dir E:\private-backups
```

恢复演练不会覆盖现有 `public` schema。它会：

1. 校验备份大小和 SHA-256；
2. 创建随机 `rc_restore_*` 专用 schema；
3. 完整恢复表、序列、索引、约束和数据；
4. 对比全部表行数、Alembic revision 和关键业务指纹；
5. 删除本次专用恢复 schema，但不删除原数据库或数据卷。

```powershell
.\.venv\Scripts\python.exe scripts\private_deployment.py `
  --env-file deploy\private\private.env `
  restore-drill `
  --backup E:\private-backups\<file>.backup `
  --manifest E:\private-backups\<file>.manifest.json
```

正式灾难恢复应在隔离维护窗口执行，先保留损坏实例及其数据卷，再根据已验证清单恢复；禁止以 `docker compose down -v` 作为恢复步骤。

## 5. 监控

外部监控使用 HTTPS 就绪探针；Prometheus 文本指标仅保留在私有 Docker 网络，不经 Nginx 暴露。容器日志采用 JSON stdout/stderr，Compose 配置限制为单文件 10 MiB、最多 5 个文件。

```powershell
.\.venv\Scripts\python.exe scripts\private_deployment.py `
  --env-file deploy\private\private.env `
  monitor --backup-manifest E:\private-backups\<file>.manifest.json
```

最低告警建议：

- 任一容器不为 `running/healthy`；
- `/api/v1/health/ready` 非 200；
- 数据库 revision 与发布合同不一致；
- 24 小时内没有成功且校验和完整的备份；
- HTTP 5xx 数量持续增长；
- 磁盘剩余空间低于 20%。

## 6. 升级与回滚

升级前必须完成备份和恢复演练，然后验证迁移可回滚：

```powershell
.\.venv\Scripts\python.exe scripts\verify_alembic_schema_cycle.py
```

升级：

1. 记录当前镜像标签、Git 提交和数据库 revision；
2. 完成备份及恢复演练；
3. 更新 `RELEASE_VERSION` 和镜像标签；
4. `docker compose build`；
5. `docker compose up -d`，API 启动时执行 `alembic upgrade head`；
6. 执行就绪、业务 smoke、ChatBI 40 题、安全负向和数据质量回归。

回滚：

1. 停止流量进入新 Web 容器；
2. 使用对应旧应用版本执行目标 `alembic downgrade <旧版本revision>`；
3. 将 Compose 镜像标签恢复为上一个已验证版本；
4. `docker compose up -d`；
5. 重新执行就绪、smoke 和数据对账。

回滚不删除 PostgreSQL/Redis/import 数据卷。若新版本已产生旧 Schema 无法表达的数据，应停止自动回滚并按备份恢复流程处置。

## 7. 冷环境 RC 验收

冷安装脚本要求一个从未启动过的 Compose project name，并在验收后保留数据卷：

```powershell
.\.venv\Scripts\python.exe scripts\validate_private_cold_install.py `
  --env-file deploy\private\private.env `
  --project-name renewable-rc-cold-001
```

本地自签证书场景增加 `--allow-self-signed`。该参数只放宽测试客户端证书校验，不改变 Nginx 的 HTTPS 配置。

## 8. 真实性与限制

- 所有业务数据必须标记为“模拟数据”，并保留数据时间、来源、批次和 `run_id`；
- 当前只验证单客户、单主机 Compose 发布候选；
- 未验证真实企业数据、真实客户使用、生产 SLA、高可用或经营收益；
- MySQL、REST API 数据源、Kubernetes、SSO 和共享多租户不属于本 RC 基线。
