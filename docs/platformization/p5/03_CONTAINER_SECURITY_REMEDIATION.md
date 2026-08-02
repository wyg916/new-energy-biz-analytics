# P5 容器安全复评与处置

## 实际结论

门禁状态为 `BLOCKED`。没有风险接受文件，任何 High 均未标记 `ACCEPTED`；没有忽略规则、降低严重级别或删除结果。

## 已实际执行

使用官方 Trivy v0.70.0、官方漏洞数据库，对 `quay.io/keycloak/keycloak:26.7.0` 进行了远端实际扫描。原始 JSON 为 `evidence/keycloak-26.7.0-trivy.json`，SHA-256 为 `7f5389ff720d99904384176b4c8d0dc0ce1e6da3bbc50d60a663597050df9948`。结果：Critical 0、High 15、唯一 High 12。

High 涉及 `mssql-jdbc 13.2.1`、`java-21-openjdk-headless 21.0.12`、`postgresql 42.7.11`、`jackson-core/databind 2.21.2` 和 `netty 4.1.135.Final`。除 OpenJDK 项未给出修复版本外，扫描器列出了对应组件修复版本；但截至本次执行没有确认到可直接替换且完成兼容验证的更高 Keycloak 官方镜像。不得通过手工替换 Keycloak 内部 JAR 冒充受支持升级，因此保留阻断。

另下载并按官方 checksums 验证了 Trivy v0.72.0（压缩包 SHA-256 `ed3cf122060f61818fe1f735fd97557954e16e10bc8b058af9852271cf2e91b3`）。v0.72.0 复扫远端拉取超过有界观察窗口，未生成新的完成结果；不能覆盖已完成的 v0.70.0 证据。

## 未完成的实际扫描

Docker/WSL 引擎在软重启后仍出现 `HCS_E_CONNECTION_TIMEOUT`，Docker API 探测无响应；Docker Hub 远端访问也超时。因此 API、Web、PostgreSQL、Redis、Nginx、Vault、SQLBot、告警接收端、迁移与备份任务镜像未完成本轮全部实际扫描，SQLBot 尤其仍无 P5 实际扫描证据。P4 Vault 的 0 Critical/1 High 只能作为历史基线，不能冒充 P5 复扫。

未删除容器、镜像或卷，未做破坏性恢复。恢复引擎后必须按 `deploy/preproduction/compose.yaml` 的实际启用及 profile 镜像枚举，逐一输出 CycloneDX SBOM、原始扫描 JSON、摘要和前后差异；目标仍是 Critical 0，High 0 或逐项正式例外。
