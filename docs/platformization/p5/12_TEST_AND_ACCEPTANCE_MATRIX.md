# P5 测试与验收矩阵

核对日期：2026-08-02。业务数据均为固定种子模拟数据，时间范围 2025-01-01 至 2026-06-30。

| 验收项 | 本轮实际结果 | 结论与边界 |
|---|---:|---|
| 后端全量 pytest | 353/353 | 原 342 项加 P5 新增 11 项；正确 `backend` 工作目录，退出码 0 |
| P5 Gate/IdP 聚焦 | 11/11 | API、RBAC、历史不可变、waiver fail-closed、IdP metadata |
| Deterministic | 40/40 | 固定 Query Plan 评测，失败 0 |
| charging_ops 对账 | FAIL | SQLite 15 项中 10 项与冻结 PostgreSQL Oracle 不同；P4 PostgreSQL 15/15 仍为历史基线，本轮未冒充复验通过 |
| sales_ops 对账 | 12/12 | 50000/82514，differences `{}` |
| DQ | 20/20 | 包含在全量 353/353；规则未修改 |
| Memory | 40/40 | 包含在全量；固定分布与安全 Oracle 未修改 |
| Skill | 40/40 | 包含在全量；Procedure/Skill 审批合同未修改 |
| RAG keyword | 60/60 | 正式 `VECTOR_DEFERRED_POST_P5`；权限、引用、注入、拒答通过 |
| Knowledge/RAG/Response 受影响聚焦 | 17/17 | P5 状态文本和运行合同回归 |
| Response Composer | 7/7 | 包含在全量；不生成结构化结果外数字 |
| Query Security | 15/15 | 包含在全量；写入、跨租户、危险 SQL 拒绝 |
| SQLBot 离线聚焦 | 46/46 | 包含在全量；不代表外部模型运行时 |
| migration | PASS | 隔离库 `base→p5_0001→p4_0001→p5_0001`，唯一 head |
| 固定数据规模 | PASS | 300000 charging、50000 sales、82514 items、15+12 指标 |
| Docker Smoke | NOT RUN | Docker/WSL API 无响应；不得用 P4 结果替代 |
| P5 Playwright | 1/1 | 正式 API、15 门禁、NO_GO、禁用 release/traffic/canary |
| 原冻结 Playwright | 15 pass / 8 fail / 3 skip | 26 项全部发现；SQLite 数值/时区与 PostgreSQL Oracle 不同，真实 OIDC 环境不存在，另有既有 route 竞争；不是 26/26 |
| Vitest | 3/3 | 通过 |
| TypeScript + Vite build | PASS | 49 modules，最终生产构建通过 |
| npm audit | 0 | 156 dependencies，全部严重级别 0 |
| P5 变更范围敏感信息扫描 | PASS | 高置信度新增泄漏 0；未扫描 `.env*` |
| 容量/2h 耐久 | NOT RUN | Docker 阻断且无代表性生产规格 |
| P5 备份恢复/故障演练 | NOT RUN | Docker 阻断；P4 历史通过不提升为 P5 证据 |
| 普通 push | BLOCKED | 两次连接 GitHub 443 超时；远端 P5 分支未创建，本地提交与 clean 状态保留 |

机器摘要：`evidence/p5-test-summary.json`、`evidence/p5-migration-and-data.json`。当前测试事实不满足生产验收最低要求，结论必须保持 `NO_GO`。
