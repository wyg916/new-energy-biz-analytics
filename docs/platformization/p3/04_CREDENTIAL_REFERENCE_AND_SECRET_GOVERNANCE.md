# CredentialReference 与 Secret 治理

## 实现

`credential_reference` 只保存 provider、secret identifier、用途、tenant/workspace/scenario/environment 作用域、状态、版本、允许动作和非敏感元数据，不保存 Secret 值。`credential_usage_audit` 记录引用、主体、动作、结果、错误码和 `trace_id`，同样不记录 Secret 值。

`CredentialReferenceService` 支持创建引用、轮换新版本、禁用、撤回和解析使用。解析前校验统一授权、作用域、状态、允许动作和显式 provider allowlist；缺失 provider、缺失引用、缺失值、禁用或撤回均在外部请求前 fail-closed。错误信息经过固定错误码脱敏。

P3 配置不自动加载 `.env*`。环境变量 Provider 只接受 CredentialReference 明确指向且服务端允许的 identifier；SQLBot 外部评测脚本只接受 CredentialReference 参数，不接受明文用户名、密码或连接串参数。

## 验收事实

- 轮换、禁用、撤回、最小权限、缺失 provider 和使用审计测试通过。
- 新增明文 Secret：0。
- 日志 Secret 泄漏：0。
- 当前隔离数据库 `credential_reference`：0 行，`credential_usage_audit`：0 行。
- 无安全 CredentialReference 可用于真实外部 SQLBot，因此外部请求数为 0，复评结论保持 `CONDITIONAL`。

本轮未读取或扫描任何 `.env*` 文件，也未接入真实 Secret Manager。
