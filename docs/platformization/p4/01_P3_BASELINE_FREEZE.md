# P3 冻结基线

核对日期：2026-08-01（Asia/Shanghai）。

## Git

- P3 worktree：`E:\新能源企业经营分析智能平台-p3-governance`
- P3 branch：`feat/p3-enterprise-governance-readiness`
- P3 HEAD：`36ad33810031c52869d88de7cf35dbdaaaa10446`
- 远端 API 核对：`origin/feat/p3-enterprise-governance-readiness` 指向同一 SHA
- 本地远端跟踪差异：ahead/behind `0/0`
- P3 工作区：clean
- P4 worktree：`E:\新能源企业经营分析智能平台-p4-rc`
- P4 branch：`feat/p4-preproduction-rc`

初次 `git fetch origin --prune` 遇到 GitHub 连接重置；因此开始阶段通过已认证 GitHub API 核对远端精确 SHA，不将失败的 fetch 记为成功。提交和推送阶段必须重新执行标准 Git 网络核对。

## 数据库与运行

- Alembic current：`p3_0001 (head)`。
- Alembic heads：唯一 `p3_0001`。
- 本地与远端 migration 文件一致，没有未合并远端 revision。
- P3 PostgreSQL、Redis、API 均 healthy，Web 正常运行。
- API liveness、readiness 和 Web 均返回 200。

## 接受的 P3 事实

P3 的 Identity、RBAC/ABAC、CredentialReference、Legal Hold/Retention、Governance Audit、站内告警、Release Registry、React 治理 UI、故障与备份恢复结论保持冻结，不重复实现。稳定回归基线为后端 335、Deterministic 40、charging 15、sales 12、DQ 20、Memory 40、Skill 40、RAG 60、Response Composer 7、Query Security 15、SQLBot focused 46、Playwright 23。

## P4 接管结论

- `P3_IMPLEMENTATION=PASS`
- `P4_ENTRY=GO_WITH_EXTERNAL_GATES`
- `QUERY_ENGINE_MODE=SHADOW`
- `SQLBOT_ENGINE_ENABLED=false`
- `SQLBOT_RUNTIME_VERIFIED=false`
- `SQLBOT_CANARY_ELIGIBLE=false`
- `PRODUCTION_RELEASE_AUTHORIZED=false`
