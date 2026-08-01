# P3 测试与验收矩阵

核对日期：2026-08-01。业务数据均为固定种子模拟数据，期间 2025-01-01 至 2026-06-30，不是企业生产数据。

| 验收项 | 结果 | 说明 |
| --- | ---: | --- |
| 后端全量 pytest | 335/335 | 全量收集与执行通过 |
| P3 focused + Skill 回归 | 11/11 | 身份、授权、治理、Skill 修复 |
| API 合同修复聚焦 | 4/4 | 未支持场景继续返回原 404 合同 |
| Deterministic | 40/40 | 固定评测 |
| charging_ops 对账 | 15/15 | differences `{}` |
| sales_ops 对账 | 12/12 | differences `{}` |
| DQ | 20/20 | 数据质量规则 |
| Memory | 40/40 | 权限、生命周期与连续上下文 |
| Skill | 40/40 | 5 个正式 Skill/场景复用 |
| RAG | 60/60 | 1 个 golden 测试节点验证 60 例 |
| Response Composer | 7/7 | 回答合同与引用 |
| Query Security | 15/15 | 安全负向 |
| SQLBot focused | 46/46 | 离线合同，不代表外部运行时 |
| 故障单元套件 | 41/41 | Redis、RAG、SQLBot、Secret、Retention 等 |
| Docker Smoke | 6/6 | 使用允许的 `Host: localhost` |
| Vitest | 3/3 | 前端单元测试 |
| Playwright | 23/23 | 原 20 条 + 合并数据治理 1 条 + P3 2 条 |
| 前端生产构建 | PASS | Vite production build |
| npm audit | 0 vulnerabilities | 156 个依赖，审计时快照 |
| 容量并发 | PASS | 40 请求、并发 4、错误 0；详见 08 |
| Redis/PostgreSQL 停机恢复 | PASS | readiness 503 后恢复 200 |
| API 重启幂等 | PASS | 核心治理与业务行数不变 |
| 迁移循环 | PASS | `base→head→base→head` |
| 备份恢复 | PASS | 行数和 dump hash 核对 |
| SQLBot 外部 10/30/20 | CONDITIONAL | 无安全 CredentialReference，0 外部请求 |

Docker 初次用不受信任 `Host: api` 直接请求返回 400，证明 TrustedHost 生效；改用允许的 `Host: localhost` 后 6/6 通过，不是对失败的绕过或弱化。

核心模拟数据仍为 charging sessions 300000、sales orders 50000、sales order items 82514；charging 指标 15、sales 指标 12，未改变冻结结果。
