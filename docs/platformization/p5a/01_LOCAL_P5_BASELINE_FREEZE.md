# 本地 P5 基线冻结

核验时间：2026-08-02T08:56:05Z。

## Git 基线

- P5 worktree：`E:\新能源企业经营分析智能平台-p5-acceptance`。
- P5 branch：`feat/p5-production-acceptance-gates`。
- P5 HEAD：`cf37a43c444515f2c92530aab050410efac4b544`。
- 初始工作区：clean。
- 相对 `origin/feat/p4-preproduction-rc`：behind 0 / ahead 6。
- `git fsck --full`：退出码 0；未发现损坏或缺失对象，仅报告历史 dangling tree/blob。

以下六个对象均经 `git cat-file -t` 验证为 commit，并按顺序连续位于 P4 基线之上：

1. `8dcf2af68f2069c9246dc9f777263b794f8570bf`
2. `158bfcc0cb8761ada836e1cfce2cace8733cbeeb`
3. `1e9fdd60c2f3befab8a7e365bc64e79169ee987a`
4. `36abd996b5104d83339d9bc525570298134bee47`
5. `cbc7804a7054e9cd8b761850322da61256d8f2f4`
6. `cf37a43c444515f2c92530aab050410efac4b544`

## 迁移基线

- 初始 `alembic current`：`p5_0001 (head)`；该次命令使用本地默认 SQLite，仅用于对象/修订核验，不作为业务验收。
- `alembic heads`：唯一 head 为 `p5_0001`。
- 历史链：`p4_0001 -> p5_0001`，未发现额外本地或远端 migration。
- P5A 尚无数据库模型变更，因此未创建 migration。

## P5A 隔离

P5A worktree 从精确冻结 SHA 创建，未修改冻结 P5 工作树。独立分支创建后初始工作区 clean。P4/P5 既有容器卷保留不动，后续标准环境使用独立 Compose project 与独立卷。
