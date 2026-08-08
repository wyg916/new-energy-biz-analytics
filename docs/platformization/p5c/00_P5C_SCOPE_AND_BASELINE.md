# P5C 事实基线、安全和发布真相收敛

## 目标

P5C 仅完成仓库事实裁决、范围冲突登记、版本真相、敏感信息扫描、一键启动修复、基础回归和冷启动验收。它不实现 DATA、RAG、Memory、SQLBot/NL2SQL 或 P6 功能。

## 起点与唯一主控

- P5B 已推送实现 SHA：`f173783dd5ba516e5cf7c376042dfc31da06a5a3`；
- P5B 本地治理证据 SHA：`6ee3ccc9e893960f11d4a147d676de1ba0b00e6f`；
- P5C 唯一起点：`6ee3ccc9e893960f11d4a147d676de1ba0b00e6f`；
- P5C 主控分支：`codex/p5c-baseline-convergence`；
- 目标 worktree：`E:\新能源企业经营分析智能平台-p5b-gate-closure`。

`6ee3ccc` 仅比 `f173783` 多 5 个 P5B 文档/机器证据文件，没有业务代码、迁移、配置或运行镜像差异。因此不得把它回退掉，也不得把它描述成新的运行时实现版本。

## 当前发布真相

- 当前可运行本地候选仍是 `4.0.0-rc.3`；
- 当前 Alembic head 是 `p5_0001`；
- DeterministicEngine 是该候选唯一正式 NL2SQL 主链；
- RAG 是 keyword-only；
- SQLBot runtime/Canary 不在 RC3；
- 数据为 2025-01-01 至 2026-06-30 的固定种子模拟数据；
- 本地预生产候选可验收，但生产发布授权、生产流量切换和 P6 生产准入均为 false。

`4.1.0` 只是后续开发目标流。在 DATA、SQLBot/NL2SQL、RAG/Memory、P6、前端/CI 和最终门禁完成前，不得标记为 RC 或发布版本。

## 非目标

- 不下载或接入公开业务数据；
- 不升级、启用或放量 SQLBot；
- 不新增开放式 NL2SQL、RAG、长期记忆、遗忘 Worker 或 P6 状态机；
- 不迁移真实数据，不删除卷，不修改生产系统；
- 不 push、不创建 tag、不改写历史。

## 数据库与安全影响

本阶段没有迁移和 Schema 变更。冷启动只复用项目专用 P5B 卷并执行幂等迁移/初始化；不得使用 `down -v`。敏感信息扫描不读取 `.env*` 内容，不在证据中记录秘密值。

## 回滚

对本阶段提交执行 `git revert <P5C_COMMIT>`。运行服务使用同一 Compose 项目执行 `docker compose ... stop`；不得删卷。回滚后根目录一键启动会恢复为旧 Alpha 启动入口，因此仅建议在需要恢复旧行为时执行。
