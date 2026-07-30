# P0 平台化实施报告

## 目标、范围与非目标

- 目标：建立当前事实、冻结平台合同、关闭低风险真实性与事务缺口。
- 范围：文档、Data Integration 错误事务、查询来源元数据、前端真实性状态、相关测试。
- 非目标：目录大重构、通用 Connector 实现、ACTIVE 数据版本、多租户、SQLBot、RAG、长期记忆、真实数据接入。

## 完成内容

1. 建立 15 份 P0 平台化文档和 5 份 ADR。
2. 将代码/数据/前端归类为 PLATFORM_CORE、CHARGING_OPS、MIXED、DEAD_OR_STALE。
3. 数据接入 overview/review 元数据显式返回预览来源、不可变发布范围、语义激活未实现和正式消费者边界。
4. 看板元数据显式区分 `platform_fact_tables` 与条件满足时的 `published_station_snapshot`。
5. Data Integration API 错误路径在写失败审计前回滚，避免提交失败操作中的脏状态。
6. MappingPage 接口失败时显示 Blocked；删除映射和场站预览 fallback。
7. 删除/禁用伪报告历史与订阅、伪负责人和处理记录、伪组织与通知、虚构节省/预计损失以及本轮识别的无动作按钮。

## 数据库与安全影响

- 本工作包无数据库 Schema 变更、无迁移、无真实数据写入。
- 发布事务行为更严格：错误路径显式回滚后再记录失败审计。
- 输入蓝图的疑似凭据未进入仓库；外部轮换仍是安全阻塞。

## 修改文件

最终清单以本分支提交为准，主要包括：

- `backend/app/api/data_integration.py`
- `backend/app/services/data_integration.py`
- `backend/app/services/dashboard.py`
- `backend/tests/test_data_integration.py`
- `backend/tests/test_dashboard.py`
- `frontend/src/overview.tsx`
- `docs/platformization/p0/*`
- `docs/adr/ADR-001` 至 `ADR-005`

## 测试与证据

最终命令和状态见 `12_ACCEPTANCE_TEST_MATRIX.md`。Docker/PostgreSQL 未运行的项目不得标记为本轮 PASS。

## 限制与未完成

- 所有消费者统一消费 ACTIVE DatasetVersion 未实现。
- 通用连接器、语义版本、场景包生命周期、租户模型、RAG/Memory Provider 未实现。
- Docker 依赖的迁移、DQ、对账和 E2E 需在引擎恢复后重跑。
- 明文凭据需要仓库外管理员轮换。

## 回滚

按三个独立工作包提交逆序执行 `git revert <commit>`；无需数据库降级。回滚真实性修复会恢复已知误导风险，不建议在无替代修复时执行。

## 阶段结论

只有验收矩阵全部必选项通过且 Critical/High 阻塞关闭后，才允许进入 P1。当前结论随本轮最终测试更新。

