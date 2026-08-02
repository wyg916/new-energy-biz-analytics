# SQLBot 安全外部复评

## 门禁结果

`SQLBOT_EXTERNAL=CONDITIONAL`，不是 PASS。Vault 与 CredentialReference 闭环已通过，但本轮未提供经授权的外部模型 CredentialReference，因此脚本在网络请求前退出：实际外部请求 0、成功响应 0、SQL 生成 0、Guard 通过 0、超时 0、provider error 0、安全违规 0。

| 集合 | 请求 | 状态 |
| --- | ---: | --- |
| Smoke 10 | 0 | NOT_EXECUTED |
| 代表性 Golden 30 | 0 | NOT_EXECUTED |
| Shadow 20 | 0 | NOT_EXECUTED |

SQL 生成率、Structured Output 解析率、Guard 通过率、字段/表幻觉、P50/P95、Token 和费用均为 N/A，不用离线、历史、Mock 或缓存值填充。完整证据见 `evidence/p4_sqlbot_external_gate.json`。

## 保持不变的安全状态

- `QUERY_ENGINE_MODE=SHADOW`
- `SQLBOT_ENGINE_ENABLED=false`
- `SQLBOT_RUNTIME_VERIFIED=false`
- `SQLBOT_CANARY_ELIGIBLE=false`
- 正式主答案仍为 DeterministicEngine
- Source Binding：charging_ops v1 ACTIVE、sales_ops v1 ACTIVE；P4 数据源轮换/回滚另有受控版本链

离线 SQLBot 聚焦合同回归已包含在后端全量套件中，但不代表外部运行时。要关闭本门禁，必须由外部负责人提供授权的模型配置与轮换凭据，再严格按 10 → 30 → 20 执行；只有 SQL 生成率 ≥80%、Guard 通过率 ≥70% 且安全违规 0 才能考虑后续 100 条 Golden，仍不得自动开启 Canary。
