# P5A Production Gate Delta

## 注册表结构变化

P5 原有 15 个 Production Gate 不删除、不改写不可变历史。P5A 为用户明确要求的可验证边界新增 13 个 gate code：

1. `REMOTE_PUSH`
2. `DOCKER_RUNTIME`
3. `POSTGRES_CANONICAL_REGRESSION`
4. `FRONTEND_E2E`
5. `KEYCLOAK_SECURITY`
6. `VAULT_SECURITY`
7. `SQLBOT_IMAGE_SECURITY`
8. `CAPACITY_SOAK`
9. `BACKUP_RECOVERY`
10. `PRODUCTION_SECRET_MANAGER`
11. `SQLBOT_EXTERNAL_RUNTIME`
12. `PRODUCTION_DATA`
13. `ENTERPRISE_ALERT`

注册表代码总数因此从 15 增至 28。每项都有 owner、blocker level、external condition、expires_at 和 review requirement；新增本地 gate 默认 `BLOCKED`，新增外部 gate 默认 `OPEN`，不得因安装基线自动通过。

## 状态更新原则

- `PASSED` 只通过受控 API 写入，并带实际文件/registry 证据、SHA-256、observed_at、未来 expires_at；
- API 强制 PASSED/WAIVED 必须有证据，WAIVED 还必须有正式批准人与匹配 approval hash；
- 每次决策写不可变 `production_gate_history` 和治理审计；
- 无正式 waiver，本轮不写任何 `WAIVED`；
- 外部 gate 不调用企业端点、不读取旧凭据，保持 `OPEN` / UI `CONDITIONAL`；
- `production_release_authorized`、`production_traffic_switched` 和 `sqlbot_canary_eligible` 始终为 false。

## 待本轮证据完成后的实际快照

两小时容量原始证据和独立验证均已 PASS，`CAPACITY_SOAK` 可以通过受控 API 写入 PASSED。故障、备份、API 补扫、敏感信息扫描和最终远端推送尚未全部完成，因此本节当前仍不列“已关闭本地门禁”最终数量。完成后将记录实际 PASSED/BLOCKED/OPEN 计数、每个本地 gate 的版本与证据哈希、外部未关闭清单以及 `NO_GO` 摘要。

`REMOTE_PUSH` 有特殊时序：最终本地提交产生前必须保持 BLOCKED；普通 push 后只有在远端 SHA 等于最终本地 HEAD 且 ahead/behind 0/0 时，才通过 API 写 PASSED。该动态数据库证据不得提前写入提交文档冒充已推送。
