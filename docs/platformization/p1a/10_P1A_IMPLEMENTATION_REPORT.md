# P1A 实施报告

更新时间：2026-07-30

## 结论

- `P1A_IMPLEMENTATION = PASS`
- `P0_ACCEPTANCE = CONDITIONAL`
- `P1B_ENTRY = NOT_ALLOWED`

P1A 的代码、迁移、PostgreSQL 运行、版本事务、语义/场景、Query Engine、前端和只读边界已完成并验证。P1B 不放行仅因为外部凭据撤销、轮换和访问日志核查仍为 `EXTERNAL_PENDING`。

## 完成内容

- 通用 Connector SDK 和 5 类插件；
- 8 个 Dataset Release/Activation 实体和 4 个服务；
- 11 类通用语义实体和 Registry；
- 12 文件 charging_ops 场景包；
- DeterministicEngine ACTIVE 版本路由和统一 QueryResult；
- 13 步真实前端治理闭环；
- PostgreSQL 只读角色 SQL、可选独立执行连接和负向验证；
- 冷安装迁移漂移、PostgreSQL flush 顺序、只读关系发现等运行缺陷修复。

## 迁移

- `0007`：DatasetVersion、审核、发布、激活、回滚；
- `0008`：通用语义模型；
- `0009`：场景包租户范围与生命周期。

完整 `base→head→base→head` 已通过，head 为 `0009`。

## 安全影响

- 无自由 SQL 入口；
- LLM 不直接生成/执行核心 SQL；
- 明文凭据字段被拒绝；
- 版本路由和只读独立连接均默认关闭；
- ACTIVE 缺失、发现失败、DQ 失败、激活失败均无 fallback；
- 只读负向验证拒绝写入、DDL、基础表和敏感系统对象。

## 限制

正式长期只读角色与真实外部 Connector 需等待凭据轮换；MySQL 数据读取、SQLBot、RAG、长期记忆和第二场景不属于 P1A。

## 回滚

1. 保持三个 P1 开关为 false，即继续使用 P0 稳定链路；
2. 使用 `RollbackService` 将 DatasetVersion 指针回到上一已发布版本；
3. Alembic 可由 0009 逐级降级；
4. 代码按独立提交逆序 `git revert`；
5. 正式只读角色若投用，先撤销 LOGIN，再执行 `DROP OWNED` 和角色清理。

## 下一阶段条件

只有外部管理员提供不含秘密值的撤销、轮换与日志核查证明，并复跑 smoke/E2E/只读门禁后，才允许把 `P0_ACCEPTANCE` 改为 PASS 并进入 P1B。
