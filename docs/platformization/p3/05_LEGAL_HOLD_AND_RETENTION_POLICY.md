# Legal Hold 与保留策略

## 模型与状态

`legal_hold` 支持 tenant、workspace、resource type/id、user 和 memory type 作用域，状态为 ACTIVE 或 RELEASED，并保存创建/解除主体、原因和时间。`retention_policy` 支持相同作用域下的保留天数、归档时点、删除模式、版本和审批状态。

只有具有 `legal_hold.manage` 或 `retention.manage` 权限的主体可以创建、解除或激活规则。普通业务用户不能解除 Hold 或绕过保留策略。

## 冲突决策

删除前按以下顺序评估：

1. 任一 ACTIVE Legal Hold 命中时，删除和自动过期均被阻止。
2. 无 Hold 时，选择所有匹配 ACTIVE Retention Policy 中保留期最长者。
3. 资源尚在最严格保留期内时拒绝删除。
4. 均不命中时才允许沿用原 Memory 删除流程。

Hold 或 Retention 阻止删除会写入治理审计；Memory 删除流程仍生成原删除审计，因此决策与动作均可追溯。

## 验收事实

- Hold 下删除成功数：0。
- 普通用户解除 Hold 成功数：0。
- Hold 解除后按权限和保留策略重新判定通过。
- 多策略冲突按最长保留期处理通过。
- 当前隔离运行基线：`legal_hold` 0 行，`retention_policy` 1 行。

本轮不接入真实法律系统，且不会自动执行外部归档或不可逆删除。
