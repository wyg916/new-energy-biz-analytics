# P0 风险登记

| ID | 风险 | 等级 | 当前控制 | 退出条件 |
| --- | --- | --- | --- | --- |
| R-01 | 输入蓝图含疑似明文数据库/API 凭据 | Critical | 不复制、不提交、不在日志复述 | 原系统撤销/轮换，检查访问日志，提供外部完成证明 |
| R-02 | 发布快照被误述为全消费者激活 | High | API/UI 增加 activation/formal consumer 元数据 | 实现 ActivationPointer，并完成全消费者一致性测试 |
| R-03 | 发布失败审计提交脏事务 | High | API 错误路径先 `rollback()`，增加回归 | 指定测试与后端全量通过 |
| R-04 | 接入 API 失败时前端显示看板 fallback | High | 删除 fallback，显示 Blocked | 前端构建、单测和 E2E 503 负向通过 |
| R-05 | Query Executor 未证明独立数据库只读角色 | High | 应用 Query Guard、私有网络 | 建立 read-only role 并用写 SQL/权限 SQL 负向证明 |
| R-06 | 单客户 RBAC 被误称多租户 | High | 合同和页面使用“单客户工作区” | tenant/org/workspace 迁移与隔离测试 |
| R-07 | Docker Engine 不可用，关键验收无法重跑 | High | 明确标记当前未验证 | 容器启动，迁移/DQ/E2E/对账重跑 |
| R-08 | 全量后端 SQLite 测试耗时长且共享 `data/test.db` | Medium | 串行执行，不并发；数据库文件被 gitignore | 将测试 DB fixture 改为明确隔离路径/事务策略并稳定完成 |
| R-09 | `main.tsx` 存在未挂载旧 UI | Medium | 入口事实已记录 | P1 证明无引用后安全删除，更新测试 |
| R-10 | E2E 写入跟踪证据目录 | Medium | 本轮改为测试输出或内存截图 | `git status` 证明 E2E 无工作区副作用 |
| R-11 | Redis 编排存在但会话工作记忆未使用 | Medium | 不宣称 Redis memory | MemoryProvider 落地与 TTL/隔离测试 |
| R-12 | 用户未跟踪接手报告与当前代码冲突 | Low | 当前运行/Schema/提交优先 | 用户另行更新或归档该文档 |

## 决策

R-01、R-02、R-05、R-07 未关闭前只能进入“继续 P0 修复/验证”，不能宣布通用企业级平台或生产就绪。

