# Memory 作用域与授权

## 作用域模型

`MemoryScope` 支持 `GLOBAL`、`TENANT`、`WORKSPACE`、`USER`、`AGENT`、
`SESSION`、`RUN`。记录包含 tenant、organization、workspace、user、agent、
session、run、scenario、类型、来源、可信度、版本和有效期字段。

最终作用域由服务端 `IdentityContext` 注入。API 请求体不能覆盖 tenant、organization、
workspace 或 user；模型输出也不能决定作用域。

## Fail-closed 顺序

1. 校验身份、角色和请求动作；
2. 将身份映射到可见 scope；
3. 在 SQL/Redis key 构造前加入 tenant、organization、workspace 与 user；
4. 加入 scenario、status、validity 和 memory type；
5. 仅对过滤后的候选做关键词、排序与上下文预算。

管理员可管理组织级候选和 Skill 生命周期，但不能跨 tenant。普通用户只能确认、
更正、拒绝或删除自己的可见记忆。charging_ops 和 sales_ops 私有记忆互不召回。

## 安全边界

- 跨租户、跨用户私有记忆、跨场景私有记忆均按硬过滤拒绝；
- 删除、过期、REJECTED、SUPERSEDED 记录不参与召回；
- Prompt Injection 内容只能作为数据，不能覆盖 `system_constraints`；
- Secret 分类和大小限制在写入前执行，拒绝事件仍写 PostgreSQL 审计。
