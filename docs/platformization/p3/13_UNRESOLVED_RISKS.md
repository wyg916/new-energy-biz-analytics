# P3 未解决风险

1. **真实企业 SSO**：本轮完成 Provider 抽象与签名测试闭环，尚未对接企业 IdP、目录同步、MFA 或企业注销流程。
2. **真实 Secret Manager**：CredentialReference 和受控 Provider 已实现，但未接入企业 Vault/KMS，也没有任何真实外部 SQLBot 凭据。
3. **SQLBot 外部运行时**：10/30/20 未执行，SQL 生成率和 Guard 通过率为 N/A；状态保持 `CONDITIONAL`、Shadow 和 Canary false。
4. **生产容量与 SLA**：P50/P95 来自单机隔离测试，不能外推为生产容量、稳定性或 SLA。
5. **生产发布**：真实生产激活固定禁用；Release Registry 只验证本地/预发布状态机。
6. **外部告警联动**：仅有站内审计与告警，邮件、工单、Webhook 和 SIEM 对接均未实施。
7. **真实客户数据**：本轮只使用固定种子模拟数据，没有验证真实数据分类、驻留、跨境、脱敏或客户对账。
8. **备份运营化**：已完成单次本地演练，但尚未建立企业备份计划、密钥托管、异地副本、RPO/RTO 和定期恢复演练。
9. **数据库厂商扩展**：生产链路以 PostgreSQL 验收；MySQL/CSV/Excel 的完整企业级凭据与生产治理不在本轮证明范围内。
10. **实时远端同步**：接管阶段 `git fetch origin --prune` 曾因 GitHub 443 超时失败；最终远端状态必须以成功 push 后重新核对为准。

这些风险不否定 P3 本地治理主线的实现结论，但阻止宣称企业生产上线、真实客户使用、真实经营收益或 SQLBot Canary 就绪。
