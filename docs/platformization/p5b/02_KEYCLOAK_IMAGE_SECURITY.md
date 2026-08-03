# Keycloak 26.7.0 镜像安全处置

## 官方版本与原始发现

2026-08-03 核对 [Keycloak 官方 Releases](https://github.com/keycloak/keycloak/releases)：最新非预发布版本仍为 `26.7.0`，没有可直接升级的后续稳定版。P5A 原始镜像为 `0 Critical / 15 High`：OpenJDK 1 条、Jackson 5 条（含重复检测）、MSSQL JDBC 1 条、Netty 5 条、PostgreSQL JDBC 1 条。

## 受控加固

`deploy/preproduction/keycloak.Dockerfile` 基于官方 `26.7.0` 固定摘要构建，并执行以下最小兼容变更：

- Jackson Core/Databind 更新至扫描器声明的修复版 `2.21.4`；
- Netty codec 相关组件更新至修复版 `4.1.136.Final`；
- PostgreSQL JDBC 更新至修复版 `42.7.12`；
- v4 只支持 PostgreSQL，移除未使用的 MSSQL JDBC；
- 执行官方 `kc.sh build --db=postgres`；
- 最终文件系统扁平化，旧 JAR 不保留在可恢复父层。

最终镜像为 `renewable-p5b-keycloak:26.7.0-hardened`，image ID `sha256:11bf9869b68206e486c0d4d27d3d22f9fa4411575bfa0a8fc018ecf33505e051`。

## 最终扫描与精确处置

Trivy 0.70.0 完整扫描结果为 `0 Critical / 4 High`，未忽略、未降级、未建立 waiver：

- `GHSA-r7wm-3cxj-wff9`、`CVE-2026-54512`、`CVE-2026-54513` 仍由旧 Quarkus 文件名/元数据触发；本轮机器证据直接提取镜像内 JAR，嵌入 Maven 版本均为 `2.21.4`，且字节 SHA-256 与固定 Maven Central 修复制品一致，因此这 3 条不适用于实际交付字节；
- `CVE-2026-22020` 仍命中 `java-21-openjdk-headless 21.0.12`，Trivy 未提供 fixed version，官方最新稳定 Keycloak 镜像和最新 UBI OpenJDK 21 runtime 均为同一版本。本轮不虚构处置，保留为 `UPSTREAM_FIX_UNAVAILABLE`。

证据：

- `evidence/container-security/trivy-keycloak.json`，SHA-256 `663593ab09a54bc507820b0577b9e80071c896d70086d2d28502450daabc65d3`；
- `evidence/container-security/keycloak-component-verification.json`，SHA-256 `80bbab2f35fd5551895a1517604824be911b398e30692c51ba04ffeddaeb12b7`。

因此 Keycloak 由原始 15 High 降至 1 条实际未处置上游 High，Critical 始终为 0。OIDC、身份映射、安全负向和 Playwright 3/3 必须在 P5B 独立栈通过；`KEYCLOAK_SECURITY` 在上游修复发布前不得伪造为无条件安全 PASS。
