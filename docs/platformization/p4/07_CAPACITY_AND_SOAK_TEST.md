# P4 容量与耐久测试

## 边界与负载

本测试仅代表本机隔离预生产容量，不代表生产 SLA。业务数据是 PostgreSQL 中 2025-01-01 至 2026-06-30 的固定种子模拟数据。负载以服务端映射的 OIDC 会话鉴权，覆盖 Identity、Policy、Deterministic 查询、Memory、Skill、RAG、审计/发布/凭据读取、OIDC、P4 状态和 SQLBot 故障下确定性回退；SQLBot 外部调用数保持 0。

## 60 秒硬化栈复测

- run_id：`P4-SOAK-20260801T231436Z`
- 并发 2；持续 60 秒；877 请求；全部 HTTP 200。
- P50 63.693 ms；P95 667.714 ms；P99 1340.992 ms。
- 错误率 0；超时率 0；安全违规成功数 0；审计丢失 false；连接池耗尽 false。
- API RSS 151,715,840 → 153,190,400 bytes，增长 1,474,560 bytes，无持续增长。
- PostgreSQL 连接 9 → 10；库增长 819,200 bytes；Redis client 1 → 1。

证据：`evidence/p4_capacity_oidc_smoke_60.json`。

## 30 分钟最终耐久

- 状态：`PASS`；run_id `P4-SOAK-20260801T231547Z`。
- 并发 6；monotonic clock 持续 1,800 秒；31,140 请求；全部 HTTP 200。
- P50 190.937 ms；P95 1,577.665 ms；P99 2,460.809 ms；错误率 0；超时率 0。
- API RSS 152,113,152 → 155,824,128 bytes，增长 3,710,976 bytes，180 个样本未检测到持续增长。
- PostgreSQL 连接 9 → 12；库 261,020,695 → 288,103,447 bytes，增长 27,082,752 bytes；Governance Audit 4,581 → 6,588，无丢失。
- Redis connected clients 1 → 1；连接池耗尽 false；安全违规成功数 0；Secret 暴露 false；SQLBot 故障影响确定性答案 0。

完整证据：`evidence/p4_capacity_soak_1800.json`。

## 资源观测

资源值通过测试期间 `docker stats --no-stream` 稀疏采样，属于“观测样本峰值”，不是持续监控最大值：API 189.97% CPU / 243.4 MiB；PostgreSQL 94.52% / 251.8 MiB；Redis 4.39% / 16 MiB；OIDC 8.38% / 679.9 MiB；Vault 2.59% / 139.9 MiB。CPU 为多核口径。PostgreSQL 连接样本峰值 18；关键容器 restart count 均为 0。验收判定以脚本 180 个首尾/周期样本为准。

## 验收门槛与回滚

常规 API 错误率必须不高于 1%，安全违规成功数、超时、审计丢失、连接池耗尽、SQLBot 故障影响确定性答案均必须为 0；30 分钟不得检测到持续内存增长，所有关键容器重启数保持 0。失败时不创建 RC：停止负载、保留证据，按故障域回滚代码/配置，并先执行已验证备份恢复；不得删除卷。
