# P5A 唯一本地预生产验收包：4.0.0-rc.2

生成日期：2026-08-03。数据性质：固定种子模拟数据，不是企业真实数据。数据范围：2025-01-01 至 2026-06-30。

## 结论先行

`LOCAL_PREPRODUCTION_RC=PASS_WITH_BLOCKED_PRODUCTION_GATES`。

该结论只表示 P5A 本地预生产收口完成，不代表生产就绪。必须同时保持：

- `PRODUCTION_ACCEPTANCE_READY=false`
- `PRODUCTION_RELEASE_AUTHORIZED=false`
- `PRODUCTION_TRAFFIC_SWITCHED=false`
- `SQLBOT_CANARY_ELIGIBLE=false`
- `GO_NO_GO=NO_GO`

不允许进入 P6，不允许提交正式生产发布申请，不允许切流或开启 SQLBot Canary。

## 标识与完整性

- RC version：`4.0.0-rc.2`，未复用 `4.0.0-rc.1`。
- Source Git SHA：`bd236ee7fc10413812573c0fcca098b821cb234f`。
- Branch：`fix/p5a-production-gate-remediation`。
- Alembic current / heads：`p5_0001 (head)`；无新增数据库模型变更，无新增 migration。
- RC Manifest：`evidence/p5a-rc-4.0.0-rc.2-manifest.json`。
- RC Manifest SHA-256：`25e9a3127fb0d81bb9aef009616e71446f0ff6dbae4d1d9eefd52d05a4445030`。
- CycloneDX SBOM：`evidence/p5a-sbom.cdx.json`，SHA-256 `32250006f64a39a12c03861999c77833e0ef5195b375642987f7beee988ddb1a`。
- Dependency / image inventory：`evidence/p5a-dependency-inventory.json`。

Source Git SHA 指向运行代码、测试、当前证据矩阵、SBOM 与依赖清单的冻结提交；Manifest 和本验收包在其后的独立 RC 文档提交中形成，最终 HEAD 与全部提交哈希由最终交付记录给出。

## 实际组件与镜像

| 角色 | 内容摘要 | RC |
|---|---|---|
| API | `sha256:d413e1427d5b470b862a8bc21800ea053f34c7435f2f0d91dff9f9c037a0b432` | included |
| Web | `sha256:5364a6c917fd39d37b284cdbd055d17d0b3cc0628e66b29d327f8cc3954aa43b` | included |
| PostgreSQL / backup | `sha256:486298eaa6cbd4830f8d1ae199e6dc9f33cee75a6bc178b0ee2d34c94b3041e3` | included |
| Redis | `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2` | included |
| Nginx | `sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752` | included |
| Keycloak | `sha256:c2b643bb866cb4c297176d11e8c60065ec4628102a19256ffb65b5a8d0bfeafd` | included |
| Vault | `sha256:a296a888b118615dc01d5f1a6846e6d4a7277946caaed5b447008fff5fe06b54` | included |
| alert receiver / migration | `sha256:42abcf52fdc4162f83bd4b188928e0d11a6b6afa9225eea6efff7dbd1a448205` | included |
| SQLBot 1.8.0 固定镜像 | `sha256:c4ca3acc34f0c63a64f3f3e7bb909760f17d184959635542278710144347d9e0` | excluded |

实际部署运行组件为 API、Web、PostgreSQL、Redis、Nginx、Keycloak、Vault、告警接收端和 backup；migration 为一次性任务且退出 0。SQLBot 默认 Compose 不创建服务，显式 profile 也使用 `pull_policy: never`，本轮容器数 0。

SQLBot 状态固定为：`ADAPTER=PASS`、`OFFLINE_CONTRACT=PASS`、`RUNTIME=DISABLED`、`IMAGE_SECURITY=BLOCKED`、`EXTERNAL_EVAL=CONDITIONAL`、`CANARY=false`。

## 当前测试与运行证据

| 范围 | 结果 | 证据 |
|---|---:|---|
| PostgreSQL 后端全量 | 359/359 effective PASS；完整披露修正重跑 | `evidence/p5a-final-regression-summary.json` |
| Deterministic / charging / sales / DQ | 40/40、15/15、12/12、20/20 | 同上、`evidence/chatbi-eval-p5a-final.json` |
| Memory / Skill / RAG / Response / Query Security | 40/40、40/40、60/60、7/7、15/15 | 同上 |
| SQLBot 离线聚焦 | 46/46，外部运行时未执行 | 同上 |
| Docker Smoke | 6/6 | `evidence/docker-smoke-p5a-final.json` |
| Playwright | 23/23 + OIDC 3/3 + Gate 1/1 = 27/27 | `evidence/playwright-*-p5a-*.xml` |
| Vitest / TypeScript / Vite / npm audit | 3/3、PASS、PASS、0 vulnerabilities | `evidence/frontend-static-p5a-final.json` |
| 两小时容量 | 7229.453 秒、35246 请求、错误率 0.059581%、超时率 0.002837% | `evidence/p5a-capacity-verification.json` |
| 故障恢复 | Redis/PostgreSQL/Keycloak/Vault PASS | `evidence/p5a-fault-recovery.json` |
| Vault 生命周期 | PASS，run `P5A-VAULT-20260803T101306Z` | `evidence/p5a-vault-acceptance.json` |
| 备份与隔离恢复 | 28222229 bytes，源/恢复摘要与关键哈希一致 | `evidence/p5a-backup-restore.json` |

容量 run_id 为 `P5-CAP-20260802T173756Z`；P50/P95/P99 为 2109.546 / 13311.483 / 20744.866 ms。越权成功、异常重启、连接池耗尽均为 0。所有当前前端业务值来自数据库、正式 API 与权限过滤，没有前端 Mock/fixture 兜底。

## 安全与 28 项门禁

Trivy 0.70.0 实扫 11 个角色、9 个唯一 image ID；按角色累计 51 Critical / 848 High，waiver 0。API、Web、Redis、Nginx、alert receiver 和 migration 为 0C/0H；PostgreSQL 与 backup 各 1C/14H，Keycloak 0C/15H，Vault 0C/3H，SQLBot 49C/802H。未忽略、未降级 CVE，镜像安全门禁保持 BLOCKED。

推送前 Gate 快照为精确 28 项：本地 13、外部 15；PASSED 7、BLOCKED 6、OPEN 15、WAIVED 0。已关闭本地门禁为 Docker、PostgreSQL 全量、Frontend E2E、容量、故障/备份恢复、RAG keyword-only、备份恢复复验。未关闭本地门禁为推送前 REMOTE_PUSH、四项镜像安全与生产 rollback drill。15 个外部门禁保持 OPEN / UI CONDITIONAL，详见 `12_UNRESOLVED_EXTERNAL_GATES.md`。

最终新增行敏感信息扫描在本验收包与 Manifest 冻结后执行，唯一依据为 `evidence/p5a-secret-scan.json`；扫描不读取 `.env*`，不把命中值写入证据。最终交付只有在该文件状态为 PASS 时才能报告新增泄漏 0。

## 回滚

1. 停止新增请求，保留全部源卷并验证本轮备份文件 SHA-256。
2. 按提交逆序使用普通 `git revert` 回滚 P5A 独立工作包；禁止 `reset --hard` 和 force push。
3. 配置变更通过受控配置版本回退；数据库无 P5A 新 migration。
4. 如需验证恢复，只恢复到独立临时数据库，核对 `p5_0001`、数据量、业务哈希、CredentialReference 和 Secret 边界后移除临时库。
5. 生产 rollback drill 尚未获批且未执行，因此 `ROLLBACK_DRILL=BLOCKED`，不能用上述本地验证替代生产演练。

## Go / No-Go

本地预生产 RC 可作为模拟数据验收候选交付，但镜像安全、生产回滚和 15 个外部门禁未关闭，且没有 waiver。因此最终推荐为 `NO_GO`；不得进入 P6 或生产发布流程。
