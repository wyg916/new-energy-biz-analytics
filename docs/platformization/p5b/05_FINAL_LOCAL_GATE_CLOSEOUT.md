# P5B 最终本地门禁与远端分发收口

## 结论

`P5B_IMPLEMENTATION=PASS`，`LOCAL_PREPRODUCTION_RC=PASS_WITH_BLOCKED_PRODUCTION_GATES`。该结论仅适用于本地预生产 RC3；正式生产验收、发布授权和流量切换均为 false，`GO_NO_GO=NO_GO`，不得进入 P6。

数据均为固定随机种子和已批准业务规则生成的模拟数据，期间为 2025-01-01 至 2026-06-30；来源为 P5B PostgreSQL，运行标识位于各证据 JSON 的 `run_id` 或时间戳字段。

## 镜像安全

- PostgreSQL：从 1 Critical / 14 High 收口到 0 Critical / 0 High；加固镜像 `renewable-p5b-postgres:16.14-hardened`。
- Keycloak：从 0 Critical / 15 High 收口到原始 0 Critical / 4 High、有效 0 Critical / 1 High。三条 Jackson 元数据命中由实际 JAR 2.21.4 和哈希证明不受影响；剩余 OpenJDK High 无可用修复版本。
- Vault：固定 `hashicorp/vault:2.0.3@sha256:a296a888b118615dc01d5f1a6846e6d4a7277946caaed5b447008fff5fe06b54`，仍为 0 Critical / 3 High，三项均为当前无修复版本的上游阻断。
- 全 RC：10 个角色、7 个唯一镜像，原始 0 Critical / 7 High，有效 0 Critical / 4 High，waiver 0。

因此 `IMAGE_SECURITY`、`KEYCLOAK_SECURITY`、`VAULT_SECURITY` 仍记录为 BLOCKED，等待上游修复和安全批准；它们不被伪造为 PASS。由于 PostgreSQL、Keycloak、Vault 均无未处置 Critical，本地 RC 结论满足冻结条件。

## SQLBot v4 范围

`SQLBOT_INCLUDED_IN_V4_RELEASE=false`、`SQLBOT_RUNTIME=NOT_INCLUDED`、`SQLBOT_IMAGE_INCLUDED_IN_BOM=false`、`SQLBOT_CANARY_ELIGIBLE=false`、`SQLBOT_EXTERNAL_EVALUATION=DEFERRED`。默认 Compose、readiness、RC 镜像清单和 SBOM 均无 SQLBot；Adapter 与 46/46 离线合同保留。原始 49 Critical / 802 High 扫描仍作为历史证据保留，未宣称修复。

## 回滚与恢复

实际演练完成当前 RC3 → 受控上一版 → RC3 的镜像和配置切换；隔离库完成 `p5_0001 → p4_0001 → p5_0001`。核心业务哈希和隔离迁移往返哈希一致，源卷未删除，临时库已回收。实际切换上一版耗时 410.625 秒，恢复 RC3 耗时 143.031 秒。

首轮证据判定因 Memory 探针缺少 `scenario_id` 以及场景发布启动时间戳刷新而 FAIL，原证据保留。修正探针后上一版与 RC3 均为 5/5 HTTP 200；逐字段证明变化仅为 `published_at`、`activated_at`、`validated_at`，最终判定 PASS。

## 最终回归

- PostgreSQL 后端：收集 363 条；四批资源竞争下发生 1 个未改代码的 30 秒子进程超时，完整 19 条适配器文件隔离复跑通过，最终有效 363/363；不宣称单次干净全跑。
- Deterministic 40/40；charging_ops 15/15；sales_ops 12/12；DQ 20/20；Memory 40/40；Skill 40/40；RAG 60/60；Response Composer 7/7；Query Security 15/15；SQLBot 离线 46/46。
- Docker Smoke 6/6；Playwright 27/27（本地认证 23、真实 OIDC 3、P5 Gate 1）；Vitest 3/3；TypeScript/Vite PASS；npm audit 0。
- 备份/隔离恢复、Redis/PostgreSQL/Keycloak/Vault 故障恢复、Vault AppRole/KV v2/轮换/禁用/撤回均 PASS。

## Gate Registry

推送前精确 28 项：本地 13、外部 15；PASSED 8、BLOCKED 5、OPEN 15、WAIVED 0。已关闭本地门禁为 Docker Runtime、PostgreSQL 回归、Frontend E2E、容量、故障/备份恢复、RAG、备份恢复复验和 Rollback Drill。

推送前 BLOCKED 为 `REMOTE_PUSH`、`IMAGE_SECURITY`、`KEYCLOAK_SECURITY`、`VAULT_SECURITY`、`SQLBOT_IMAGE_SECURITY`。其中 SQLBot 镜像仅阻断未来 SQLBot 版本，不适用于 v4；普通推送并验证 0/0 后才可将 `REMOTE_PUSH` 写为 PASSED。

首次普通推送于 2026-08-04T12:48:42.7256980+08:00 发起并成功创建 `origin/fix/p5b-local-gate-closure`。冻结实现本地与远端 SHA 均为 `f173783dd5ba516e5cf7c376042dfc31da06a5a3`，ahead/behind 为 `0/0`，upstream 为 `origin/fix/p5b-local-gate-closure`。`REMOTE_PUSH` decision seed 与最终快照据此从 BLOCKED 更新为 PASSED；owner 为 `release_owner`，最后核验时间为 2026-08-04T12:49:18.1172700+08:00，证据 SHA-256 为 `79733cdfe5665debebc1ffb35cb3923aa7f72482ba4f6ae0083180af27dfd8e5`，最迟于 2026-08-18T12:49:18.1172700+08:00 或任何新提交后复核。本任务按冻结约束未修改数据库。

推送后精确 28 项：本地 13、外部 15；PASSED 9、BLOCKED 4、OPEN 15、WAIVED 0。仍为 BLOCKED 的本地门禁仅为 `IMAGE_SECURITY`、`KEYCLOAK_SECURITY`、`VAULT_SECURITY`、`SQLBOT_IMAGE_SECURITY`；其中 `SQLBOT_IMAGE_APPLICABLE_TO_RELEASE=false`。`PRODUCTION_ACCEPTANCE_READY=false`、`PRODUCTION_RELEASE_AUTHORIZED=false`、`PRODUCTION_TRAFFIC_SWITCHED=false`、`SQLBOT_CANARY_ELIGIBLE=false`、`GO_NO_GO=NO_GO`、`P6_ENTRY=NOT_ALLOWED` 均未改变。

15 个外部门禁继续 OPEN/CONDITIONAL：真实企业 IdP、生产 Secret Manager、Secret Manager、SQLBot 外部评审与运行时、真实生产数据及批准、生产容量、监控告警、企业告警、变更窗口、风险接受、业务/安全/运维批准。不得以本地证据替代。

## 回滚

应用代码使用 `git revert` 按本轮独立提交逆序回退；运行时使用 `p5b.rollback.override.yaml` 切回受控上一版镜像；数据库仅使用已验证迁移和演练前备份，保留 PostgreSQL、Redis、Vault 卷和审计历史。禁止 reset hard、force push、删卷或覆盖源数据库。
