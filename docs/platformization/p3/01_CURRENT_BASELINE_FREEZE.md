# P3 当前基线冻结

核对时间：2026-08-01（Asia/Shanghai）。

## Git 与工作现场

- P2B 冻结 worktree：`E:\新能源企业经营分析智能平台-p2b-memory`
- P2B 分支：`feat/p2b-agent-memory-skills`
- P2B HEAD：`7ea31fcc7c81106c5a0c169c5b06efdbc791e1d0`
- 本地远端跟踪引用：`origin/feat/p2b-agent-memory-skills` 同一提交，ahead/behind `0/0`
- P2B 工作区：clean
- P3 worktree：`E:\新能源企业经营分析智能平台-p3-governance`
- P3 分支：`feat/p3-enterprise-governance-readiness`

执行了 `git fetch origin --prune`，但 GitHub 443 连接超时，退出码为 128。因此本文只声明
本地远端跟踪引用的一致性，不把实时 fetch 误报为成功；提交与推送阶段必须再次重试网络
核对。

## 运行基线

- P2B API：`http://127.0.0.1:18000/api/v1/health` 返回 200。
- P2B Web 反向代理健康接口和首页：`http://127.0.0.1:8080` 返回 200。
- P2B PostgreSQL、Redis、API 容器健康；Web 容器运行。
- 运行库 Alembic：`p2b_0001 (head)`。
- 已接受 P2B 报告中的既有回归证据，不重复重跑 P0 至 P2B 的完整审计。

## 迁移并发事实

指定 P2B 基线的迁移链为 `0014 → p2b_0001`。另一本地已提交工作树包含
`0014 → 0015`，提交为 `ba732d9759d1a37642708af839992609224349a4`，revision 名为
`0015_frontend_data_lineage`。两者构成并发 head。

P3 必须保留两个既有 revision，不修改它们的 `down_revision`，并创建显式 merge revision
后再添加 P3 Schema revision。禁止通过删除 migration、覆盖文件或静默选择其中一个 head
解决冲突。

## 接管结论

- `P2B_IMPLEMENTATION=PASS`
- `P3_ENTER=GO`
- `QUERY_ENGINE_MODE=SHADOW`
- `SQLBOT_ENGINE_ENABLED=false`
- `SQLBOT_RUNTIME_VERIFIED=false`
- `SQLBOT_CANARY_ELIGIBLE=false`

SQLBot 外部复评仍为 Conditional；企业治理与本地生产就绪主线按本目录冻结范围继续实施。
