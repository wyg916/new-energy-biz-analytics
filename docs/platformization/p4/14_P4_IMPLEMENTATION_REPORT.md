# P4 实施报告

## 结论

- `P4_IMPLEMENTATION=PASS`
- `PREPRODUCTION_ACCEPTANCE=PASS`
- `RELEASE_CANDIDATE=PASS_WITH_EXTERNAL_PRODUCTION_GATES`
- `RELEASE_CANDIDATE_VERSION=4.0.0-rc.1`
- `QUERY_ENGINE_MODE=SHADOW`
- `SQLBOT_ENGINE_ENABLED=false`
- `SQLBOT_RUNTIME_VERIFIED=false`
- `SQLBOT_CANARY_ELIGIBLE=false`
- `PRODUCTION_RELEASE_AUTHORIZED=false`
- `NEXT_STEP=GO_TO_FORMAL_PRODUCTION_ACCEPTANCE_PREPARATION_WITH_GATES`

P4 已在独立工作树、分支、Compose project、网络、端口和数据卷中完成预生产集成与唯一 RC 验收；没有修改 P3 冻结工作树，没有接入真实客户数据、企业 IdP、外部模型或企业告警系统。这里的 PASS 不代表正式生产可用。

## 完成范围与非目标

已完成 Keycloak Authorization Code + PKCE/JWKS 标准闭环、服务端身份映射与拒绝路径；Vault KV v2/AppRole/CredentialReference 版本轮换与 fail-closed；数据源接入、审批、轮换、回滚、停用/归档；disabled-by-default 签名 Webhook；P4 React 管理页；隔离拓扑；容量/耐久、故障、迁移、备份恢复、安全负向、镜像扫描和 RC Manifest。

未启用 SQLBot 外部运行时或 Canary；没有自由 SQL、第三场景、前端 Mock、自动审批/发布/外部消息、真实客户数据或生产切流。DeterministicEngine 继续提供正式主答案。

## 数据库与数据影响

新增可回滚 migration `p4_0001`，最终唯一 head/current 均为 `p4_0001`。固定种子模拟数据仍为 charging sessions 300000、sales orders 50000、sales order items 82514，期间 2025-01-01 至 2026-06-30；核心指标 15、发布结构 15+12 未改变。

最终备份恢复同时证明：CredentialReference 9、数据源治理 3、权威 Memory 6527、Governance Audit 6594、Release Registry 8、P4 PlatformRelease 1、验收记录 18 在备份时源/恢复摘要一致；业务数据哈希 `a55192ad4704ff27870f2ba4da142051` 一致。最终 dump SHA-256 `e5ccf0509d6bcd327fdc38a4796c4a87473ce0549d289dd0b50f850fd5ef5871`，临时库已移除、源卷未删除、数据库未保存 Secret 值。

## 测试与验收

后端 342/342；最终身份/依赖聚焦 8/8；数据源/告警最终增量 2/2；Deterministic 40/40；charging 15/15；sales 12/12；DQ 20/20；Memory 40/40；Skill 40/40；RAG 60/60；Response Composer 7/7；Query Security 15/15；SQLBot offline 46/46；故障单元 58/58；Docker Smoke 6/6；Vitest 3/3；原 Playwright 23/23；最终 P4 OIDC Playwright 3/3；前端 build PASS；npm audit 0。

最终 OIDC 耐久为并发 6、1,800 秒、31,140 请求、全部 200，P50/P95/P99 分别为 190.937/1,577.665/2,460.809 ms，错误/超时/安全违规成功均为 0；180 个 API RSS 样本未检测到持续增长，连接池未耗尽、审计未丢失、关键容器重启为 0。该结果只代表本机隔离预生产容量，不是生产 SLA。

主要执行入口包括 `docker compose -p renewable-p4-rc -f deploy/preproduction/compose.yaml up -d --build`、`scripts/Run-P4OidcAcceptance.ps1`、`scripts/run_p4_capacity_soak.py --duration-seconds 1800 --concurrency 6`、`scripts/run_p4_fault_recovery.py`、`scripts/run_p4_backup_restore.py`、`scripts/run_p3_migration_acceptance.py`、后端 pytest/固定评测、`npm test`、`npm run build`、`npm audit` 和 Playwright。详细结果见 `12_TEST_AND_ACCEPTANCE_MATRIX.md` 与 `evidence/`。

## 安全影响与外部门禁

LOCAL bearer 在预生产拒绝；跨租户/工作区/场景、未审核数据源激活、SQL 写入/越权、Secret 明文和日志泄漏成功数均为 0；tracked 高置信度 Secret 扫描命中 0，按合同未扫描 `.env*`。API/Web/加固 PostgreSQL/Redis/Nginx 为 0 Critical / 0 High。

生产仍被以下证据缺口阻断：企业 IdP；授权外部模型与真实 SQLBot 10/30/20；禁用 SQLBot 镜像扫描；Keycloak 0C/15H（12 unique）与 Vault 0C/1H 上游项；RAG vector；真实客户数据；企业告警；生产容量/SLA；变更窗口和风险接受签署。不得把 RC `ACTIVE` 解读为生产授权。

## RC、限制与回滚

唯一 RC 为 `4.0.0-rc.1` / `REL-8e18dac8-41d9-4d30-945e-8478637fb79e`，Manifest SHA-256 `a2937a6a7766a072304460ab40b1e12c18f4f040cb04dfb8c62f9d9525fdb186`。预生产代码完成、验收完成、RC 审批门禁为 true；企业 IdP、外部模型、生产变更窗口和生产授权为 false；生产按钮与 SQLBot Canary 保持禁用。

回滚先运行验证备份，再停止 proxy/web/api/backup；按 P4 独立提交逆序 `git revert`，通过显式 `-ConfirmRollback` 才允许运行已验证 Alembic downgrade，并用治理版本历史回滚配置、RC 与 Source Binding。不得使用 `reset --hard`、force push，不能删除 PostgreSQL/Redis/Vault 卷或审计/发布历史。

允许进入正式生产验收准备以关闭外部门禁；在所有门禁有真实证据并由用户另行明确授权前，不允许生产部署、切流或宣称正式生产可用。
