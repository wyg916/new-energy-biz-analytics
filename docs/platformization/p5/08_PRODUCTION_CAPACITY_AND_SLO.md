# P5 代表性容量与 SLO

状态：`CONDITIONAL`，`PRODUCTION_CAPACITY_VERIFIED=false`。

已固化 `deploy/production-acceptance/capacity-scenario.v1.json` 和 `scripts/run_p5_capacity_acceptance.py`。场景建议 100 名具名用户、20 并发、7200 秒，使用固定种子模拟数据规模 300000 charging sessions、50000 sales orders、82514 items；请求覆盖 Deterministic dashboard/assistant、身份与策略、Memory、Skill、keyword RAG、治理门禁和 OIDC 状态。建议最低 SLO 仅为验收建议，不是批准的生产 SLA。

工具记录总请求、分布、P50/P95/P99、错误/超时、API CPU/RSS、数据库大小/连接/审计量、Redis 连接，以及 Memory、Skill、OIDC 等工作负载 P95；滚动重启、单实例故障和备份影响必须作为相关故障步骤关联记录。

本轮 Docker/WSL 不可用，且没有代表性生产规格，因此未执行新的 2 小时测试：并发、请求、延迟、资源增长均为 N/A。P4 30 分钟本地耐久结果没有被提升为生产 SLA。恢复后应在不删卷的验收环境执行 2 小时主负载，并分别注入滚动重启、单实例故障和备份；即使本地 PASS，未提供生产同构规格时 `PRODUCTION_CAPACITY_VERIFIED` 仍为 false。
