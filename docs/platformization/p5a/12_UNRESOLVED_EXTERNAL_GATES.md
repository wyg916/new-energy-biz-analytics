# P5A 未关闭的外部门禁

截至 2026-08-02，P5A 只处理当前独立预生产验收环境内可真实复验的事项。下列门禁依赖企业系统、真实授权、正式签署或生产同构环境，本轮不得以本地 Keycloak、Vault、告警接收器、模拟数据或无凭据 SQLBot 替代。

| 门禁 | 当前状态 | 关闭所需的外部证据 |
|---|---|---|
| `ENTERPRISE_IDP` | `OPEN` / UI `CONDITIONAL` | 企业测试租户、metadata、claims、禁用/撤权、JWKS 轮换与回滚 |
| `PRODUCTION_SECRET_MANAGER` | `OPEN` / UI `CONDITIONAL` | 获授权的托管实例、HA、备份、轮换、CredentialReference 与 fail-closed |
| `SECRET_MANAGER` | `OPEN` / UI `CONDITIONAL` | 生产托管 Secret Manager 的正式实例与责任人验收 |
| `SQLBOT_EXTERNAL_REVIEW` | `OPEN` / UI `CONDITIONAL` | 获授权 CredentialReference 下依序完成外部 10/30/20 复评且安全违规为 0 |
| `SQLBOT_EXTERNAL_RUNTIME` | `OPEN` / UI `CONDITIONAL` | 获授权外部模型凭据与固定版本运行时验收；此前 SQLBot 必须保持 disabled |
| `PRODUCTION_DATA_APPROVAL` | `OPEN` / UI `CONDITIONAL` | 数据分类、脱敏、最小只读权限、保留/删除、审计与断开连接审批 |
| `PRODUCTION_DATA` | `OPEN` / UI `CONDITIONAL` | 经批准的真实生产数据连接及全链路证据 |
| `PRODUCTION_CAPACITY` | `OPEN` / UI `CONDITIONAL` | 生产同构规格、正式 SLA、容量/耐久/故障/备份期间影响验收 |
| `MONITORING_ALERTING` | `OPEN` / UI `CONDITIONAL` | 企业监控与接收端的签名、重试、幂等、熔断、超时、脱敏、限流与恢复 |
| `ENTERPRISE_ALERT` | `OPEN` / UI `CONDITIONAL` | 经授权企业告警接收端的端到端证据 |
| `CHANGE_WINDOW` | `OPEN` / UI `CONDITIONAL` | 具名变更单、批准人、窗口、回滚责任人与现场记录 |
| `RISK_ACCEPTANCE` | `OPEN` / UI `CONDITIONAL` | 对残余风险的正式批准、依据、补偿控制、到期日与复核要求 |
| `BUSINESS_APPROVAL` | `OPEN` / UI `CONDITIONAL` | 业务负责人基于唯一验收包的明确签署 |
| `SECURITY_APPROVAL` | `OPEN` / UI `CONDITIONAL` | 安全负责人基于镜像、Secret、越权与残余风险证据的签署 |
| `OPERATIONS_APPROVAL` | `OPEN` / UI `CONDITIONAL` | 运维负责人基于容量、监控、备份、窗口与回滚证据的签署 |

本轮没有创建 waiver，也没有把任何批准人写成 `TBD`、`system` 或自动批准。外部门禁继续阻断 `production_acceptance_ready`；此外，本地镜像安全门禁因未清零的 Critical/High 仍为 `BLOCKED`。因此即使其他本地技术复验通过，结论仍为 `NO_GO`，`PRODUCTION_RELEASE_AUTHORIZED=false`，`PRODUCTION_TRAFFIC_SWITCHED=false`。
