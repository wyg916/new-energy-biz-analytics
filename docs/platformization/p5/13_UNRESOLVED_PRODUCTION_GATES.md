# P5 未关闭生产门禁

截至 2026-08-02，以下事实仍未关闭：

1. 全部运行/禁用镜像实际扫描、SBOM 与摘要未完成；Keycloak 15 High 未修复/未正式例外，SQLBot 未实际扫描；
2. Docker/WSL 引擎不可用，阻断 Compose、镜像构建、Docker Smoke、P5 备份恢复、故障和容量实证；
3. 没有企业 IdP 测试租户；
4. 没有生产 Secret Manager 和外部模型 CredentialReference 授权；
5. SQLBot 10/30/20 未执行，Canary 不可申请；
6. 没有代表性生产规格和批准 SLA；
7. 没有企业告警接收端授权；
8. 没有真实生产数据范围、脱敏与访问批准；
9. 没有变更窗口、风险接受及业务/安全/运维负责人签署；
10. P5 head 的备份恢复和回滚演练尚无运行证据。

RAG Vector 不在此列表：P5 已正式冻结 keyword-only，Vector 属于后续独立版本。

以上外部条件缺失没有阻止允许范围内的门禁、IdP 契约、容量工具、RAG 合同、UI、测试与文档工作，但任何缺口均不得写成 PASS。
