# P5A 测试与验收矩阵

本矩阵只列本轮真实执行结果。所有业务数据均为已落 PostgreSQL 的固定种子模拟数据，范围为 2025-01-01 至 2026-06-30；不得据此宣称生产 SLA、真实客户使用或生产收益。

| 范围 | 结果 | 当前证据 |
|---|---:|---|
| PostgreSQL 后端全量 pytest | 353/353 effective PASS，0 failed，0 skipped | `evidence/p5a-postgres-regression.json` |
| Deterministic 固定评测 | 40/40 | 同上 |
| 充电指标对账 | 15/15，差异 0 | 同上 |
| 销售指标对账 | 12/12，差异 0 | 同上 |
| Data Quality | 20/20 | 同上 |
| Memory | 40/40 | 同上 |
| Skill | 40/40 | 同上 |
| RAG keyword-only | 60/60；MRR 0.9667；Recall@10 0.8936；citation/faithfulness 1.0；越权与注入影响 0 | 同上、`evidence/postgres-fixed-rag-60.xml` |
| Response Composer | 7/7 | 同上 |
| Query Security | 15/15 | 同上 |
| SQLBot 离线聚焦 | 46/46 effective PASS；未声称外部运行时 | 同上、`evidence/postgres-fixed-sqlbot-46.xml` |
| 迁移循环 | base → `p5_0001` → `p4_0001` → `p5_0001` PASS；专用临时库已移除 | `evidence/p5a-migration-cycle.json` |
| Docker Smoke | 6/6 | `evidence/docker-smoke.json` |
| Playwright 原回归 | 23/23 | `evidence/playwright-original-23-final.xml` |
| Keycloak Authorization Code + PKCE | 3/3 | `evidence/playwright-p4-oidc-3.xml` |
| P5 Gate UI | 1/1 | `evidence/playwright-p5-gate-1-final.xml` |
| Playwright 合计 | 27/27 | `evidence/frontend-acceptance-summary.json` |
| Vitest | 3/3 | `evidence/vitest.xml` |
| TypeScript / Vite build | PASS | `evidence/frontend-build.txt` |
| npm audit | PASS，0 vulnerabilities；首次网络 `ECONNRESET` 后重试成功 | `evidence/npm-audit.json` |
| 镜像安全 | 11 个角色、9 个唯一 image ID；51 Critical / 848 High（按角色计）；0 waiver；门禁 BLOCKED；SQLBot 排除 RC | `evidence/container-security/container-security-summary.json` |
| 60 秒容量预检 | PASS，100 逻辑用户 / 并发 20 | `evidence/p5a-capacity-preflight.json` |
| 第一轮 7200 秒容量浸泡 | FAIL；3600 秒 OIDC 服务端会话到期后出现预期外 401，收尾未生成本轮 JSON；基础设施无 OOM/重启 | `07_TWO_HOUR_CAPACITY_AND_SOAK.md` 失败记录 |
| 会话轮换边界预检 | PASS；180 秒、100 用户、并发 20、200 次轮换、1089 请求、0 错误/超时 | `evidence/p5a-capacity-session-rotation-preflight.json` |
| 第二轮 7200 秒容量浸泡 | PASS；100 用户、并发 20、实际 7229.453 秒、35,246 请求、错误率 0.059581%、超时率 0.002837%、P50/P95/P99 2109.546/13311.483/20744.866 ms、越权/异常重启/连接池耗尽 0 | `evidence/p5a-capacity-soak.json`、`evidence/p5a-capacity-verification.json` |
| Redis/PostgreSQL/Keycloak/Vault 故障恢复 | PASS；逐项 readiness 503/liveness 200/恢复 200；RAG 0 伪造引用；Vault 无明文 fallback；SQLBot 0 容器且 Deterministic 主链完成 | `evidence/p5a-fault-recovery.json` |
| Vault 生命周期复验 | PASS；AppRole/KV v2/禁用/绑定修复/轮换/回滚/只读连接，audit +52,564 bytes | `evidence/p5a-vault-acceptance.json` |
| 新备份与隔离恢复 | PASS；28,222,229 bytes；源/恢复摘要和核心哈希一致；临时库已移除；Secret 明文禁止项 0 | `evidence/p5a-backup-restore.json` |

当前最终发布阻断不依赖上述本地 PASS：镜像 Critical/High 未清零且没有正式 waiver，15 个外部门禁也未关闭。因此当前推荐始终为 `NO_GO`。
