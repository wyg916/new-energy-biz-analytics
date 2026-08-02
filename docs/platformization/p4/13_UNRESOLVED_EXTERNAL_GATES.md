# 未关闭的外部门禁

截至 2026-08-02，P4 本地隔离代码与预生产验收不等于生产授权。以下门禁没有仓库内证据关闭：

| 门禁 | 当前状态 | 关闭所需证据 |
| --- | --- | --- |
| 真实企业 IdP | CONDITIONAL | 企业 metadata、管理员审批、证书/域名、组映射与禁用策略验收 |
| 外部模型/SQLBot 10/30/20 | CONDITIONAL | 授权模型 CredentialReference、0 泄漏、按顺序真实运行及门槛达成 |
| RAG vector | PENDING | 独立镜像/迁移、索引、权限前过滤和 60 条复验；当前仅 keyword 模式 |
| 真实客户数据 | NOT AUTHORIZED | 数据授权、脱敏、对账、分类、保留与删除审批 |
| 企业 Secret Manager | CONDITIONAL | 当前 Vault 隔离闭环通过；生产服务实例、HA/备份、管理员签署仍缺 |
| 企业告警系统 | NOT AUTHORIZED | 目标系统审批、测试租户、出站网络、重试/熔断和撤回演练 |
| 生产容量/SLA | NOT EXECUTED | 生产同构容量模型、资源配额、SLO、监控与负责人签署 |
| 生产变更窗口与切流 | NOT AUTHORIZED | 变更单、审批人、窗口、回滚责任人与现场验收 |
| 全镜像企业安全签署 | CONDITIONAL | 仓库内扫描报告、企业扫描器/镜像仓库策略和风险接受人签署 |
| Keycloak/Vault 上游镜像漏洞 | BLOCKED FOR PRODUCTION | Keycloak 0C/15H（12 unique）与 Vault 0C/1H 需升级至修复版本、重建复扫为通过，或取得有时限的企业风险接受；P4 隔离预生产 RC 可继续，生产切换不可继续 |
| SQLBot 禁用 profile 镜像签署 | CONDITIONAL | 已固定 `v1.8.0` registry digest，但本轮未启用且未扫描；任何启用、Canary 或生产验收前必须完成镜像扫描和授权凭据复评 |

保持 `QUERY_ENGINE_MODE=SHADOW`、`SQLBOT_ENGINE_ENABLED=false`、`SQLBOT_CANARY_ELIGIBLE=false`、`PRODUCTION_RELEASE_AUTHORIZED=false`。生产发布按钮与 Canary 开关保持禁用。允许形成 P4 Release Candidate 和进入正式生产验收准备，但不允许生产部署、切流或宣称正式生产可用。
