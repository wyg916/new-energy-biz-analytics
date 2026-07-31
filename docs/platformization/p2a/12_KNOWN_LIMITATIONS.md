# P2A 已知限制

更新时间：2026-07-31

1. P0 外部凭据撤销、轮换和访问日志核查仍无管理员确认。
2. SQLBot 容器健康，但尚无实际模型、模拟 datasource、实际 SQL/结果和运行
   100 条评测。
3. 真实 Shadow 未执行，Canary 不具备准入资格。
4. SQLBot 上游必须 privileged；只允许本地隔离验收。
5. SBOM 与 Critical/High 漏洞扫描均在 10 分钟超时，供应链状态 PENDING。
6. 三个模型仅有 CredentialReference，没有可验证的 base URL/model contract；
   Model Gateway live runtime PENDING。
7. 当前 PostgreSQL 没有 pgvector，只有关键词/全文检索和确定性 Rerank；
   不具备完整 hybrid retrieval。
8. Parser 只支持受控 Markdown/文本，不支持 OCR、图片知识库、复杂 PDF/Office。
9. 指定“最近30天”在当前日期超出模拟数据范围，系统返回澄清而不推算数据集
   最后 30 天；如需该语义必须新增经过批准的“相对数据截止日”合同。
10. RAG Prompt Injection 为规则检测，不代表对所有未知攻击完备。
11. 当前只支持 charging_ops 和 sales_ops，不含第三业务场景。
12. 不含长期偏好、情景/程序性记忆、自动反思、多 Agent、SSO、Kubernetes
   或生产发布。
13. 本轮后段出现并发未提交工作区修改和未跟踪 0015；P2A 未覆盖或提交它们。

所有数据仍为固定种子模拟数据，不得宣称真实客户、生产上线或经营收益。
