# P4 测试与验收矩阵

核对日期：2026-08-02。数据均为固定种子模拟数据，期间 2025-01-01 至 2026-06-30，不是企业生产数据。

| 验收项 | 实际结果 | 结论与边界 |
| --- | ---: | --- |
| 后端全量 pytest | 342/342 | 三个并行桶收集 342 例；唯一 3 个失败来自错误的 docs mount，按正确源布局重跑对应文件 4/4，通过且未删除/弱化测试 |
| 最终身份/依赖聚焦 | 8/8 | 最终 API 镜像；LOCAL bearer 预生产入口返回 401 |
| Deterministic | 40/40 | 固定评测 |
| charging_ops 对账 | 15/15 | differences `{}` |
| sales_ops 对账 | 12/12 | differences `{}` |
| DQ | 20/20 | 数据质量规则 |
| Memory | 40/40 | 权限、生命周期与连续上下文 |
| Skill | 40/40 | 已批准 Skill/Procedure |
| RAG | 60/60 | 关键词受控检索；vector 仍 PENDING |
| Response Composer | 7/7 | 回答合同与引用 |
| Query Security | 15/15 | 写入、越权与 Guard 负向 |
| SQLBot focused | 46/46 | 离线合同，不代表外部运行时 |
| 故障单元套件 | 58/58 | Redis、RAG、SQLBot、Secret、Retention 等 |
| Docker Smoke | 6/6 | 原正式主链回归 |
| Vitest | 3/3 | 前端单元测试 |
| 原 Playwright | 23/23 | P3 冻结路径未退化 |
| P4 OIDC Playwright | 3/3 | 最终硬化栈，真实 Code + PKCE；未映射/禁用用户拒绝 |
| 前端生产构建 | PASS | TypeScript + Vite production build |
| npm audit | 0 vulnerabilities | 最终 package-lock 快照 |
| OIDC 60 秒容量 | PASS | 877 请求、并发 2、错误/超时 0 |
| OIDC 30 分钟耐久 | PASS | 31,140 请求、并发 6、1,800 秒；错误/超时/安全违规成功 0，无持续内存增长 |
| Redis/PostgreSQL/Vault 停机恢复 | PASS | readiness 503 后恢复 200，未删卷 |
| RAG/SQLBot/Secret 故障 | PASS | 受控降级或 fail-closed；确定性答案影响 0 |
| migration 循环 | PASS | `base→p4_0001→base→p4_0001`，唯一 head |
| 备份恢复 | PASS | 临时库摘要和业务数据哈希一致，临时库删除、源卷保留 |
| 数据源生命周期与负向 | PASS | v1 SUPERSEDED、v2 ROLLED_BACK、v3 ACTIVE；越权/写入成功 0 |
| 外部告警测试适配器 | PASS | 本地签名 webhook；真实企业消息 0 |
| SQLBot 外部 10/30/20 | CONDITIONAL | 无授权外部模型 CredentialReference；网络请求前退出，实际请求 0 |
| SQLBot 禁用 profile 镜像 | CONDITIONAL | registry digest 已固定；未进入运行栈、未执行镜像扫描，启用前仍需关闭门禁 |
| tracked Secret 扫描 | PASS | 高置信度命中 0，按约束排除 `.env*` |
| API/Web/PostgreSQL/Redis/Nginx 镜像 | PASS | Docker Scout 0 Critical / 0 High |
| Vault/Keycloak 镜像 | PRODUCTION GATE OPEN | Vault 0C/1H；Keycloak Trivy 0C/15H（12 unique）；不得授权生产 |

核心数据核对保持 charging sessions 300000、sales orders 50000、sales order items 82514；核心指标 15，发布指标结构 15+12 未改变。完整证据位于 `docs/platformization/p4/evidence/`；最终 30 分钟结果必须在 RC Manifest 前固化。
