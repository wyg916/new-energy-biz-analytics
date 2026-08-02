# Secret Provider 集成

## 实现与数据库影响

P4 在既有 Provider 抽象下接入 Vault 2.0.3 KV v2。数据库只保存 CredentialReference 的 provider、路径标识、版本、用途、允许动作、状态和审计，不保存 Secret 值。API 使用只读 AppRole；轮换使用独立最小权限 AppRole；Vault file storage、audit 和应用运行材料均位于 P4 独立卷。

实际 CredentialReference 共 9 条元数据：数据源引用从 v1、v2 轮换到 ACTIVE v3；Webhook 引用从 v1 轮换到 ACTIVE v2；禁用证明引用为 DISABLED；SQLBot username/password 引用仍为 ACTIVE v1，但没有被授权为外部模型 CredentialReference。

## 实际验收

- KV v2 Secret version 2 创建成功；CredentialReference 新版本建立、旧版本 SUPERSEDED、缓存失效后重新解析：PASS。
- 禁用引用解析被拒绝：PASS。
- Source Binding rotate、审批、激活与 rollback：PASS；回滚后连接仍只读。
- Vault 不可用/认证失败返回 `VAULT_AUTH_FAILED`，明文 fallback 使用数 0。
- 重启后 AppRole 重新登录并加载：PASS。
- root token 持久化数 0；恢复阶段临时 root 完成最小权限配置后已撤回且运行材料清空。
- API、前端、证据和日志中 Secret 值暴露数 0。

实际结果见 `evidence/p4_secret_rotation.json`。最终 `vault.hcl` 不包含未认证 generate-root 通道；Vault 2.0 恢复时需要显式授权的行为按官方 generate-root 流程处置，临时兼容配置未进入最终仓库配置。

## 安全与回滚

Secret 环境变量 allowlist 为空；不扫描 `.env*`。Provider 缺失或不可用时只拒绝，不回退到环境明文或历史结果。回滚 CredentialReference 时创建新的元数据版本指向已存在的历史 Vault version，保留审计链；不得在数据库或 Git 中复制 Secret，也不得删除 Vault 审计卷。
