# P5 唯一生产验收包

生成日期：2026-08-02。数据性质：固定种子模拟数据，不是企业真实数据。

## 标识与完整性

- P4 冻结基线：`a28b92b5e83545bf8b0bb47bf2f3efa3c9d8d39d`；
- P5 实现代码 SHA（验收文档提交前）：`36abd996b5104d83339d9bc525570298134bee47`；
- 基础 RC：`4.0.0-rc.1`；本轮未构建或发布新的生产 RC；
- 数据库 head：`p5_0001`，唯一 head；
- IdP 配置版本：`p5-enterprise-idp-v1`；
- 容量场景版本：`p5-capacity-scenario-v1`；
- RAG：`KEYWORD_ONLY`，Vector `VECTOR_DEFERRED_POST_P5`；
- SQLBot：SHADOW、disabled、runtime unverified、canary false；
- Release authorized：false；Traffic switched：false。

分发状态：本地最终提交已生成；普通 push 两次均因 `github.com:443` 连接超时失败，远端 P5 分支尚未创建。

## 镜像、SBOM 与 CVE

P4 SBOM/依赖清单保持冻结且哈希已核验，但不能代表 P5 新构建；本轮因 Docker/WSL 阻断没有新的完整镜像摘要和 SBOM。Keycloak 26.7.0 实际 Trivy 结果为 0 Critical/15 High（12 unique），原始证据 SHA-256 `7f5389ff720d99904384176b4c8d0dc0ce1e6da3bbc50d60a663597050df9948`。SQLBot 镜像实际扫描未完成；Vault 的 P4 0C/1H 仅为历史基线。镜像安全门禁为 BLOCKED，无风险例外。

## 外部与运行门禁

企业 IdP、生产 Secret Manager、模型 CredentialReference、SQLBot 10/30/20、企业告警、生产数据、代表性生产规格、变更窗口和三方批准均为 CONDITIONAL/OPEN。备份恢复和 P5 回滚演练为 OPEN。RAG keyword-only 为 PASSED。

## 测试、容量与恢复

后端 353/353、Deterministic 40/40、sales 12/12、RAG 60/60、迁移往返、P5 UI E2E、Vitest、build 和 npm audit 已通过。charging 在 SQLite 的 P5 对账失败，必须在 PostgreSQL 复验；原 26 条 Playwright 为 15 pass/8 fail/3 skip；Docker Smoke、2 小时容量、故障与 P5 备份恢复未运行。因此没有 P50/P95/P99、错误率、资源增长或生产 SLA 数值可发布。

灾难恢复沿用 P4 受控步骤：停止新请求、保留源卷、验证备份哈希、恢复到临时目标、升级至目标 head、核对业务哈希与 Secret 边界、经具名 Owner 确认后才可切换。P5 尚未运行该步骤，不能标为本轮 PASS。

## 机器证据哈希

| 证据 | SHA-256 |
|---|---|
| `environment-blockers.json` | `eccf60ad64b52653c8e891477e609258a3a212a6e61f1e1fe827c280b406679c` |
| `p5-external-gates.json` | `338ebcb8382a98c57c657dca64c8abfb24a0be7dc1cb32e3dcaf78f1cae693a4` |
| `p5-migration-and-data.json` | `4c817882b785efd6504cc982a4e8d1f2b3cb3761737f3dd71b0d6480ff5ba95d` |
| `p5-security-summary.json` | `da7c6c1ef39facfdaa7e7bb70b078f2380b13c3e69d8caacc5ccce31469965a0` |
| `p5-test-summary.json` | `74007017c9a920461847cbfb3455fcc5c7c7d608a15e9e41aa1a7a9f7abaafa8` |
| `rag-keyword-release.json` | `a59c871188aba4216a82281790a7bb1e3064ed0dc28f83e11fff144e35eccd8e` |

## 最终决策

`GO_NO_GO=NO_GO`，`PRODUCTION_ACCEPTANCE_READY=false`。未关闭的 BLOCKER、未完成的全镜像实际扫描和未通过的强制回归意味着当前不允许申请正式生产发布授权，不允许部署、切流或开启 SQLBot Canary。
