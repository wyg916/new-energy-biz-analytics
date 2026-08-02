# P5 Production Gate Registry

## 结论

P5 新增数据库落库、API 输出和前端只读展示三层一致的生产门禁登记册。登记册含 15 项门禁，初始总体建议为 `NO_GO`；`PRODUCTION_RELEASE_AUTHORIZED=false`、`PRODUCTION_TRAFFIC_SWITCHED=false`、`SQLBOT_CANARY_ELIGIBLE=false` 均为不可由登记册决策接口改写的运行合同。

## 状态与证据规则

允许状态只有 `OPEN`、`IN_PROGRESS`、`PASSED`、`WAIVED`、`BLOCKED`、`EXPIRED`。所有门禁包含 Owner、证据、阻断级别、过期时间、最后验证时间、复核要求和版本。`PASSED` 与 `WAIVED` 必须有受控证据引用；`WAIVED` 还必须有非占位批准人、风险依据，以及与 `approval://` 证据一致的 SHA-256。无批准证据时接口 fail-closed。

历史记录只追加，ORM 层禁止更新或删除；每次决策同时写入治理审计。租户和 workspace 来自可信身份，不能由请求体选择。普通业务用户仅有 `production_gate.view`，管理员才有 `production_gate.manage`。

## 初始状态

- `RAG_MODE=PASSED`：实际冻结 keyword-only，证据见 `evidence/rag-keyword-release.json`。
- `IMAGE_SECURITY=BLOCKED`：镜像未完成全量实际复扫且 Keycloak 仍有 High。
- 其余 13 项为 `OPEN`；涉及外部授权的 OPEN 在 UI/API 显示为 `CONDITIONAL`。

迁移为 `p5_0001`，只新增 `production_gate_registry` 和 `production_gate_history`，可降级回 `p4_0001`。

## 回滚

回滚应用提交并执行 `alembic downgrade p4_0001`。这会移除 P5 门禁表；执行前必须导出门禁历史，且不得把回滚理解为生产授权。
