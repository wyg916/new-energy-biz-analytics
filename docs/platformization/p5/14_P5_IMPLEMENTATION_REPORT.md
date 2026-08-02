# P5 实施报告

## 结论

`P5_IMPLEMENTATION=PASS_WITH_BLOCKED_ACCEPTANCE_GATES`。允许范围内的代码、测试、证据和文档已完成；`PRODUCTION_ACCEPTANCE_READY=false`，Go/No-Go 建议为 `NO_GO`。本轮没有生产部署、切流、Canary、真实数据或未授权外部调用。

## 目标、范围与非目标

目标是关闭可由仓库实现的生产验收控制缺口，并把外部条件和安全阻断做成不可伪造的证据。范围包括门禁 Registry、企业 IdP 配置契约、RAG 正式决策、容量工具、治理 UI、测试与验收包。非目标是重做 P0—P4、接入真实客户数据、寻找旧 Key、自由 SQL、第三业务场景、多 Agent、生产部署或自动批准。

## 实现

1. 新增 15 项数据库门禁、受控 API、严格状态集合、证据哈希、到期、Owner/阻断级别/复核要求、只追加历史和治理审计；
2. `PASSED/WAIVED` 无证据即拒绝，WAIVED 必须有非占位批准人、依据及匹配 `approval://` 哈希；
3. 新增 `p5_0001` 可逆迁移和 `production_gate.view/manage` RBAC；
4. 新增唯一 issuer、Metadata/PKCE/claims/revocation/clock skew/JWKS 配置契约，未冒充真实企业 IdP；
5. 正式冻结 keyword-only，API/UI/测试一致为 `VECTOR_DEFERRED_POST_P5`；
6. 新增容量场景 v1 与两小时工具，但因运行环境阻断未生成容量结果；
7. 新增 P5 管理 UI，全部读取正式 API，展示 NO_GO、证据、阻断和 waiver，release/traffic/canary 按钮继续禁用；
8. 完成文档、机器证据、敏感信息扫描和逻辑提交。

## 数据库、安全与真实性影响

数据库只新增两张门禁表；迁移可降级至 `p4_0001`。业务事实表、15+12 指标和模拟数据规则未修改。P5 E2E 数据由固定种子写入隔离数据库后经 API 读取，未使用前端 Mock/fixture 兜底。

Keycloak 实际复扫仍为 0 Critical/15 High；SQLBot 与其余镜像没有完成 P5 全量实际扫描。没有风险接受文件，waiver 数为 0。P5 变更范围高置信度 Secret 命中 0，`.env*` 未被扫描；未提供外部模型 CredentialReference，SQLBot 外部请求为 0。

## 测试与证据

后端 353/353、Deterministic 40/40、sales 12/12、RAG 60/60、P5 聚焦 11/11、Vitest 3/3、P5 Playwright 1/1、build PASS、npm audit 0、迁移往返 PASS。charging PostgreSQL 对账、Docker Smoke、原 26 条 Playwright、2 小时耐久、P5 备份恢复和故障演练未达到 P5 通过条件，详见 `12_TEST_AND_ACCEPTANCE_MATRIX.md`。

## 修改范围

- 后端：`backend/app/production_acceptance/`、路由/bootstrap/RBAC/OIDC 配置、模型导出、P5 测试；
- 数据库：`backend/alembic/versions/p5_0001_production_acceptance_gates.py`；
- RAG：knowledge runtime/index/retrieval 及对应测试；
- 前端：P5 门禁页、治理入口、知识/RAG 状态、E2E 和完整 HTML shell；
- 工具/配置：IdP 模板、容量场景与 `run_p5_capacity_acceptance.py`；
- 文档/证据：`docs/platformization/p5/`。

## 限制、风险与回滚

主要风险是镜像 High、SQLBot 未扫描/未实测、缺少企业 IdP/Secret Manager/告警/数据/生产规格授权、P5 容量与恢复未运行，以及本地 SQLite 无法替代 PostgreSQL 冻结 Oracle。回滚代码提交后执行 `alembic downgrade p4_0001`，恢复前端和 keyword 状态；先导出门禁历史，禁止删卷。RAG 后续 Vector 发布必须走独立版本和评测。

当前不允许进入生产部署或切流阶段；只允许继续关闭列明门禁并在证据齐全后提交新的生产授权评审。
