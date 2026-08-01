# SQLBot 安全运行时复评

## 前置门禁

真实外部 10 Smoke、30 代表性 Golden、20 Shadow 只允许在安全 CredentialReference 解析成功后运行。本轮隔离库没有可用 CredentialReference，且未授权读取其他凭据来源。

两个外部评测入口在缺少 `credential-ref` 参数时均以退出码 2 结束，发生于网络请求之前。外部请求数：0。

## 本轮结果

| 批次 | 实际执行 | 结果 |
| --- | --- | --- |
| 10 Smoke | 否 | 未安全注入凭据，fail-closed |
| 30 Golden | 否 | 未安全注入凭据，fail-closed |
| 20 Shadow | 否 | 未安全注入凭据，fail-closed |

由于 10/30/20 未发生真实外部调用，本轮 SQL 生成率、Guard 通过率和外部安全违规数均为 `N/A`，不得用历史、离线 Oracle 或 Mock 填充。

离线 SQLBot 聚焦回归为 46/46，通过 adapter、quality patch、source binding、只读执行、engine router 和 canary 门禁；该结果只证明本地合同未退化，不等于外部运行时验证。

## 正式判定

- `SQLBOT_SECURE_RUNTIME_REEVALUATION=CONDITIONAL`
- `SQLBOT_RUNTIME_VERIFIED=false`
- `QUERY_ENGINE_MODE=SHADOW`
- `SQLBOT_ENGINE_ENABLED=false`
- `SQLBOT_CANARY_ELIGIBLE=false`
- DeterministicEngine 继续承担正式用户主答案。

后续只有通过受控 Secret Provider 注入最小权限 CredentialReference，才可重新运行 10/30/20；即使达到门槛，也不能自动开启 Canary。
