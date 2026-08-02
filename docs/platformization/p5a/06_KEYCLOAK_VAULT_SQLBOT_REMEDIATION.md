# P5A Keycloak、Vault 与 SQLBot 风险处置

## 结论

三个安全门禁均为 `BLOCKED`，waiver 数为 0。SQLBot 继续 `disabled`，未启动 Canary；Keycloak 与 Vault 保持当前验收运行版本，未手工替换上游镜像内部依赖。

## Keycloak

- 实际镜像：`renewable-p5a-keycloak:26.7.0`，image ID `sha256:c2b643...feafd`；
- 实扫：0 Critical、15 High、12 个唯一 High；
- 主要包：Netty `4.1.135.Final`（扫描器给出 `4.1.136.Final`/`4.2.16.Final`）、Jackson core/databind `2.21.2`（给出 `2.21.4` 等）、PostgreSQL JDBC `42.7.11`（给出 `42.7.12`）、OpenJDK 21.0.12（无 fixed version）和 MSSQL JDBC `13.2.1`；
- 官方发布核对：Keycloak 最新非预发布仍为 [26.7.0](https://github.com/keycloak/keycloak/releases/tag/26.7.0)，发布日期 2026-07-09；
- 处置：没有更高的受支持官方 Keycloak 版本可做兼容升级。手工覆盖内部 JAR 会破坏官方运行合同，因此不执行；`KEYCLOAK_SECURITY=BLOCKED`。

本轮 OIDC Authorization Code + PKCE、未映射用户拒绝、禁用用户拒绝和 P5 Gate 登录仍为 4/4 通过；功能回归通过不能抵消镜像 High。

## Vault

- 实际镜像：`hashicorp/vault:2.0.3`，RepoDigest `sha256:a296a8...06b54`；
- 实扫：0 Critical、3 High；
- 受影响包：Go stdlib `1.26.4`（fixed `1.26.5`）、`google.golang.org/grpc 1.81.0`（fixed `1.82.1`）、`golang.org/x/text 0.37.0`（fixed `0.39.0`）；
- 官方发布核对：Vault 最新非预发布仍为 [v2.0.3](https://github.com/hashicorp/vault/releases/tag/v2.0.3)，发布日期 2026-06-17；
- 处置：上游尚无更高受支持版本，不能自行重编译官方二进制后仍宣称为受支持镜像；`VAULT_SECURITY=BLOCKED`。

AppRole、KV v2、审计、轮换、禁用和故障恢复由本轮后续故障脚本复验；即便功能通过，在无修复版本/waiver 时安全门禁仍不能通过。

## SQLBot

- 固定禁用镜像：`dataease/sqlbot:v1.8.0@sha256:c4ca3acc34f0c63a64f3f3e7bb909760f17d184959635542278710144347d9e0`；
- 实扫：49 Critical、801 High；24 个唯一 Critical、627 个唯一 High；
- 主要风险集中于 Debian `linux-libc-dev 6.1.158-1`、Perl 5.36、Node 18.20.4、OpenSSL 3.0.17、Python 3.11.2，以及 Pillow 12.2.0、NLTK 3.9.4 和多个 Go stdlib；完整 installed/fixed version 在原始 JSON 与汇总中；
- 官方发布核对：当前最新非预发布为 [v1.10.0](https://github.com/dataease/SQLBot/releases/tag/v1.10.0)，发布日期 2026-07-16，发布说明明确包含 SQL 注入、提示注入、权限提升和跨工作空间等安全修复；
- 处置：v1.10.0 比冻结 v1.8.0 新，但本轮没有 v1.10.0 的固定 digest、数据库迁移/API 兼容、全镜像复扫和 SQLBot 运行时验收。直接替换会绕过已冻结适配合同，因此不宣称“兼容修复版本已验证”。保持 `SQLBOT_ENGINE_ENABLED=false`、`SQLBOT_RUNTIME_VERIFIED=false`、`SQLBOT_CANARY_ELIGIBLE=false`，`SQLBOT_IMAGE_SECURITY=BLOCKED`。

离线安全聚焦有效 46/46、主链在 SQLBot 不可用时继续工作，只能证明确定性主链隔离，不能接受 SQLBot 镜像的 Critical/High。

## PostgreSQL/backup 关联阻断

Trivy 对最终 image ID 报告 1C/14H，目标为旧层路径 `usr/local/bin/gosu`。最终文件系统已核验为指向 Alpine C 实现 `su-exec` 的 symlink，但无权威不适用证明/waiver，仍保持 BLOCKED，详见 `05_CONTAINER_SECURITY_RESCAN.md`。

## 官方核对证据

结构化只读核对结果位于 `evidence/container-security/official-release-compatibility.json`。没有访问企业 IdP、托管 Secret Manager、外部模型或企业告警端点，也没有使用凭据。
