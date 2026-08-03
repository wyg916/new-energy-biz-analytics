# Vault 镜像安全处置

## 结论

P5B 继续固定官方稳定版 `hashicorp/vault:2.0.3` 的不可变 digest。最终原始扫描为 `0 Critical / 3 High`，因此 `VAULT_SECURITY` 不得标记为 `PASSED`；本地 RC 可以依据“无未处置 Critical”继续收口，但该门禁保持 `BLOCKED_UPSTREAM_FIX_UNAVAILABLE`。

## 精确发现

- `CVE-2026-56852`：`golang.org/x/text` 0.37.0，扫描器修复版本 0.39.0；
- `GHSA-hrxh-6v49-42gf`：`google.golang.org/grpc` 1.81.0，扫描器修复版本 1.82.1；
- `CVE-2026-39822`：Go 标准库 1.26.4，扫描器修复版本 1.26.5。

## 已执行的整改尝试

使用 Vault 2.0.3 官方源码、Go 1.26.5、`x/text` 0.39.0 和 gRPC 1.82.1 完成了 354.8 MiB 可执行文件的编译与版本运行验证。Docker BuildKit 在二进制完成后的层收尾阶段持续无响应，镜像未成功落盘，因而该产物没有被冒充为最终镜像或用于门禁通过。为避免无限尝试，本轮回到官方固定 digest，并保留准确阻断结论。

## 功能边界

最终 P5B 栈仍需实际验证 file storage、初始化/解封、AppRole、KV v2、最小权限、audit、CredentialReference 轮换/禁用/撤回、缓存失效、重启加载、`VAULT_AUTH_FAILED` 与无明文 fallback。它只是本地预生产 Vault，不代表企业托管生产 Secret Manager。

## 回滚

Vault 使用与 P5A 相同的官方 2.0.3 数据格式与运行合同；回滚只切换镜像/配置，不删除或重新初始化 Vault 卷。
