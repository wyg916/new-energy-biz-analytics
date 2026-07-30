# 平台化迁移路线

## P0：事实、合同与低风险修复（本工作包）

- 冻结七类合同和五项 ADR。
- 建立当前依赖/归属矩阵。
- 数据接入失败 fail closed，不显示跨域 fallback。
- 发布失败先回滚业务事务再记录失败审计。
- 元数据明确发布快照不等于语义激活。
- 删除或禁用伪组织、通知、负责人、处理时间线、报告历史/订阅、虚构节省额和无动作按钮。

退出门：合同/文档完整；相关回归通过；Docker/PostgreSQL、安全和凭据轮换阻塞清零。

## P1：平台内核与 charging_ops 场景解耦

1. 建立 `IdentityContext`、`QueryContext` 和场景 Provider 接口。
2. 将 Query Plan 形状、Guard、Answer Guard 抽为 platform query。
3. 将指标枚举、中文词典、SQL 绑定迁入 charging_ops 场景。
4. 建立 `SemanticModelVersion` 和兼容性测试。
5. 只做适配层迁移，保留现有 API 与模块化单体。

退出门：平台模块不反向依赖 charging_ops；15 项指标全量回归一致。

## P2：DatasetVersion 与原子激活

1. 新增通用 dataset/version/activation 表及可回滚迁移。
2. 把现有 `PublishedStationSnapshot` 包装为 charging dataset adapter。
3. 所有消费者改由 ACTIVE 指针解析版本。
4. 提供激活、回滚、并发冲突和失败审计测试。

退出门：看板、ChatBI、诊断、报告同一请求使用同一版本；无“各取最新”。

## P3：Connector SDK

- 抽取 CSV/XLSX、PostgreSQL、MySQL、REST 适配器。
- 增加发现、能力、schema fingerprint、游标、秘密引用和契约测试。
- charging_ops 字段映射留在场景包。

## P4：企业身份与治理

- tenant/org/workspace 模型、OIDC、行策略、列掩码、导出权限。
- 独立数据库只读查询账户、限流、并发配额和审计。

## P5：知识与记忆 Provider

- 先实现权限前置的 KnowledgeProvider 和引用。
- 再把 WorkingMemory 切到可替换 Provider。
- 长期记忆需单独 DoR，不保存全量聊天文本。

## P6：可选双引擎与产品完善

- SQLBot 只作为受控 Planner/非核心探索适配器。
- 补齐真实报告历史、订阅、通知和工单集成；在后端未实现前前端保持 Disabled。

## 回滚原则

每阶段独立迁移与提交；API 适配器至少保留一个阶段；数据库采用 expand/verify/switch/contract；回滚只能切回兼容的已发布版本，不删除证据。

