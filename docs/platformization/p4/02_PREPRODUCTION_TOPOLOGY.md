# P4 预生产部署拓扑

## 实施结果

独立 Compose project `renewable-p4-rc` 已实际启动并通过健康检查。对外仅暴露反向代理 `8084/http` 与 `8444/https`；API、Web、PostgreSQL、Redis、Vault、Keycloak、告警接收端和备份任务均只在 `renewable-p4-rc-network` 内通信。业务数据为数据库中的固定种子模拟数据，期间 2025-01-01 至 2026-06-30。

| 服务 | 镜像/职责 | 健康与边界 |
| --- | --- | --- |
| api | `renewable-p4-rc-api:4.0.0-rc.1` | readiness 检查 PostgreSQL、Redis、Vault；本地认证关闭 |
| web | React production build | 只调用正式 `/api/v1`，无 Mock/fallback |
| proxy | `nginx:1.31.3-alpine@sha256:4a73073...` | TLS、Trusted Host、OIDC 反向代理；唯一对外入口 |
| db | `renewable-p4-rc-postgres:16.14` | 基于固定摘要 PostgreSQL 16.14，以 `su-exec` 替换上游易受影响的 `gosu`；`p4_postgres` 独立卷；revision `p4_0001` |
| redis | `redis:7.4.10-alpine@sha256:e7723f...` | `p4_redis` 独立卷；认证配置来自运行卷 |
| vault | `hashicorp/vault:2.0.3` | file storage 与 audit 独立卷；业务 Secret 不进数据库 |
| oidc | Keycloak `26.7.0` | 标准 Code + PKCE、JWKS、会话与用户映射 |
| alert-receiver | 本地预生产测试 Webhook | 签名、幂等、脱敏，不连接企业消息系统 |
| migrate/init | 一次性任务 | 先迁移再落库固定种子模拟数据与治理基线 |
| backup | `pg_dump` 定时任务 | `p4_backups` 独立卷，不删除源卷 |
| sqlbot | `dataease/sqlbot:v1.8.0` profile | 默认不启动；主链不依赖它 |

独立卷包括 `p4_runtime`、`p4_keycloak_runtime`、`p4_postgres`、`p4_redis`、`p4_vault_rc1`、`p4_vault_audit`、`p4_imports`、`p4_evidence` 和 `p4_backups`。本轮未删除任何现有 PostgreSQL、Redis 或 Vault 卷。

## 配置与启动

- 编排模板：`deploy/preproduction/compose.yaml`，SHA-256 `7eac848fdb1e6a57257205edf27e1f448ecd09c53419b9ddf1c5f72483ba9da8`；禁用的 SQLBot profile 也固定到 registry digest，避免 tag 漂移。
- `APP_ENV=preproduction`、`SIMULATED_DATA_ONLY=true`、`LOCAL_AUTH_ENABLED=false`、`QUERY_ENGINE_MODE=SHADOW`、`SQLBOT_ENGINE_ENABLED=false`、`PRODUCTION_RELEASE_AUTHORIZED=false`。
- `runtime-bootstrap` 只向专用运行卷写入随机启动材料；业务凭据由 Vault KV v2 和 CredentialReference 解析。仓库不包含真实 Secret。
- 启停与验收入口为 `scripts/Invoke-P4Preproduction.ps1`；`start`、`stop`、`migrate`、`acceptance`、`oidc-acceptance`、`secret-rotation`、`sqlbot-gate`、`soak`、`migration-check` 和需显式确认的 fail-closed `rollback` 均已提供。

## 真实性、限制与回滚

本拓扑是隔离预生产环境，不是生产 SLA 或生产切流。SQLBot profile 未启用且不会影响 DeterministicEngine。回滚先执行数据库备份，再回退代码/配置提交并运行已验证 migration downgrade；禁止删除卷或清除审计、凭据元数据和发布历史。
