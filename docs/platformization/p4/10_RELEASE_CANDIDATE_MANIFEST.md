# P4 Release Candidate Manifest

## 唯一候选版本

- 版本：`4.0.0-rc.1`
- 环境：`preproduction`
- Release ID：`REL-8e18dac8-41d9-4d30-945e-8478637fb79e`
- 状态：`ACTIVE`（仅指预生产 RC）
- 源 Git SHA：`aabdeed102b39d177cb4edecb2cc813b829c4d61`
- Manifest：`evidence/p4_release_candidate_manifest.json`
- Manifest SHA-256：`a2937a6a7766a072304460ab40b1e12c18f4f040cb04dfb8c62f9d9525fdb186`
- 唯一 RC 记录数：1
- 生产授权：`PRODUCTION_RELEASE_AUTHORIZED=false`

脚本先以无副作用模式返回 `VALIDATED`，再经显式 `--activate` 依次完成 DRAFT → REVIEW → APPROVED → ACTIVE；持久化 RC 验收为 PASS，evidence hash `55a72596146b8ed59f5332412d2701cb05f04ed94815bd5041b028fe801fc5ae`。RC 不等于正式生产发布。

## 构建与数据合同

Manifest 固化 API、Web、PostgreSQL、Redis、Nginx、Keycloak、Vault 以及禁用 SQLBot profile 的镜像/registry digest；migration head 为 `p4_0001`，Compose SHA-256 为 `7eac848fdb1e6a57257205edf27e1f448ecd09c53419b9ddf1c5f72483ba9da8`。

场景包为 charging_ops 1.0.0 ACTIVE、sales_ops 1.0.0 ACTIVE；语义模型为 charging_ops 0.1.0 ACTIVE、sales_ops 1.0.0 ACTIVE；Skill 8 个、Procedure 5 个，均为 1.0.0 ACTIVE；Policy Bundle `p3-platform-scope` v1 ACTIVE；SQLBot Source Binding 两场景均为 v1 ACTIVE。RAG 诚实登记为 keyword-only、vector PENDING、数据库 PUBLISHED 文档版本 0，不虚构 vector 发布。

依赖清单为 `evidence/p4_dependency_inventory.json`；安全扫描为 `evidence/p4_security_scan_summary.json`；测试矩阵为 `12_TEST_AND_ACCEPTANCE_MATRIX.md`。三者的 SHA-256 均写入不可变 Manifest。

## 已知风险与生产门禁

P4 隔离预生产实现和 RC 验收通过，但以下生产门禁仍为 false：企业 IdP、授权外部模型、SQLBot 禁用镜像安全签署、Keycloak/Vault 上游漏洞处置、RAG vector、真实客户数据、企业告警、生产容量/SLA、生产变更窗口。生产发布与 SQLBot Canary 按钮保持禁用。

允许进入正式生产验收准备，用于逐项关闭上述门禁；不允许生产部署、切流或声明正式生产可用。启动、验收和回滚步骤均在 JSON Manifest 中固化；回滚必须先备份、显式确认、不删除卷，并通过治理版本历史回滚配置、发布和 Source Binding。
