# Docker/WSL 恢复与独立标准环境

核验时间：2026-08-02T09:47:51Z。

## 现场根因与恢复边界

P5 期间的直接阻断是 WSL HCS connection timeout，Docker Linux Engine API 无响应。本轮接管时 WSL2 `docker-desktop` 已重新处于 Running，Docker Desktop Engine 已恢复；没有证据支持把该瞬时宿主故障归因到仓库代码，因此未伪造一次不存在的宿主修复动作。

恢复后的冻结 P4 栈显示了重启后真实的 fail-closed 行为：Vault 重新密封，API readiness 返回 503，告警接收端因 Vault AppRole 登录 503 而拒绝启动。P4 卷保持原状；P5A 没有删除、重置或复用这些卷。

P5A 首次独立启动又暴露并修复两项部署缺陷：

1. Docker Compose 5.3.1 在中文工作区对多服务 Bake 生成包含不可打印字符的 gRPC header。P5A 启动器改为逐镜像执行 BuildKit 构建，再以 Compose 启动服务；未禁用 BuildKit 安全边界。
2. PostgreSQL 原 healthcheck 可在官方 entrypoint 的临时 Unix-socket 初始化服务器阶段过早变为 healthy，导致 migration 与 Keycloak 抢跑并收到 connection refused。P5A healthcheck 改为探测最终 TCP listener `127.0.0.1:5432` 与 `renewable_p5a`。
3. P4 proxy healthcheck 固定发送 `Host: p4.localhost`，在 P5A trusted-host 策略下会得到拒绝。P5A override 使用 `Host: p5a.localhost`，保留 fail-closed host 校验。

## 当前标准环境

- Docker Desktop：4.84.0；Client/Server Engine：29.6.2；Linux context：`desktop-linux`。
- Docker Compose：5.3.1；WSL2 kernel：6.18.33.2-microsoft-standard-WSL2。
- 独立 project：`renewable-p5a-remediation`。
- 独立 network：`renewable-p5a-remediation-network`。
- 独立 named volumes：9 个，均使用 `renewable-p5a-remediation_` 前缀。
- 入口：`https://p5a.localhost:8445`；HTTP 8085 仅重定向到 HTTPS。
- 运行服务：API、Web、PostgreSQL、Redis、Nginx proxy、Keycloak、Vault、告警接收端、backup 全部 running；有 healthcheck 的运行服务全部 healthy。
- 一次性任务：runtime bootstrap、Vault permissions/bootstrap、DB prepare、migration、fixed-seed init 全部退出码 0。
- SQLBot profile 继续 disabled，未启动 Canary。

## liveness 与 readiness

- `GET /api/v1/health`：HTTP 200，`status=ok`，版本 `5.0.0-p5a`，数据分类 `simulated`。
- `GET /api/v1/health/ready`：HTTP 200，database revision `p5_0001`，PostgreSQL、Redis、Vault KV v2 和 Keycloak OIDC 均为 `ok`。
- PostgreSQL 当前固定数据量：charging sessions 300000、sales orders 50000、sales order items 82514。

Docker Hub 内部 DNS 与一次实际 `busybox:1.37` 拉取成功；随后一次独立 `docker manifest inspect` 在 registry 响应头前超时，说明仓库链路仍有间歇性风险。镜像扫描与外部拉取必须以各自最终实际结果判定，不能由本节替代。

## 容量修复阶段的后续构建事实

容量预检暴露连接池配置后需要重建 API 镜像。此时 Compose/Bake 路径再次出现 `x-docker-expose-session-sharedkey` 含不可打印字符的 gRPC 错误，`COMPOSE_BAKE=false` 也未规避。为完成这一单镜像、锁定 Dockerfile 的本地重建，本轮仅对该条命令设置 `DOCKER_BUILDKIT=0`，使用 Docker legacy builder 成功生成 `renewable-p5a-api:5.0.0-p5a`；没有修改 Docker daemon 全局配置、没有删除镜像/容器卷，也没有改动 P4/P5 冻结环境。

该构建器兼容问题仍是 Windows 中文路径下的本地工具风险，不得解释为已修复 Docker Desktop。API 当前运行镜像必须在最终提交前追加一次同标准 Trivy 复扫；旧 API 扫描不能替代重建后的镜像证据。
