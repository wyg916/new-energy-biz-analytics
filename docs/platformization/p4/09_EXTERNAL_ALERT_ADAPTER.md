# 外部告警测试适配器

## 范围与结果

P4 只实现可插拔的本地预生产测试 Webhook，不连接真实企业邮箱、IM 或生产告警平台。实际投递结果为 `DELIVERED`：HMAC 签名验证 PASS、payload 脱敏 PASS、同一 idempotency key 重放不重复投递、超时/失败写入治理审计、连续失败触发熔断，运行健康返回电路状态。

Payload 只含告警标识、规则、严重度、摘要、trace 与模拟数据边界，不含 Secret、Token、Cookie、数据库凭据或业务明细。签名引用 `preprod-webhook-signing` 已由 Vault v1 轮换到 ACTIVE v2，值未出现在证据。

适配器默认能力只在预生产显式配置时启用；生产发布与真实外部发送仍关闭。回滚为禁用 `EXTERNAL_ALERT_ENABLED` 或撤回适配器提交，站内安全告警继续保留，已写审计和幂等记录不删除。证据见 `evidence/p4_external_alert.json`。
