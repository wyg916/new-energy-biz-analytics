# 数据库迁移与回滚

## 并发 head 处理

接管基线存在两个已提交 head：

- `p2b_0001`，来自 `0014` 的 Memory/Skill 迁移链。
- `0015`，revision 文件 `0015_frontend_data_lineage.py`，同样来自 `0014`。

P3 未删除或改写任一历史 migration。`p3_merge_0001_lineage_and_memory.py` 以 tuple `down_revision` 显式合并 `p2b_0001` 与 `0015`，随后 `p3_0001_enterprise_governance.py` 指向 merge revision。最终 `alembic heads` 只有 `p3_0001 (head)`。

## P3 Schema

`p3_0001` 新增 15 张表：

1. `identity_principal`
2. `identity_group`
3. `identity_group_membership`
4. `governance_role`
5. `governance_permission`
6. `governance_role_permission`
7. `governance_policy`
8. `governance_binding`
9. `credential_reference`
10. `credential_usage_audit`
11. `retention_policy`
12. `legal_hold`
13. `governance_audit_event`
14. `security_alert`
15. `platform_release`

各表包含作用域/状态查询索引；版本、角色权限、组成员、引用版本和发布版本使用唯一约束；Binding 使用主体与目标非空 CheckConstraint；跨表主体、组、角色、权限和 CredentialReference 使用外键。

## 验证与回滚

- 专用临时数据库 `base → head → base → head`：PASS。
- 最终 revision：`p3_0001`。
- 备份恢复后核对模拟 charging sessions 300000、sales orders 50000：PASS。
- 临时迁移库和恢复库在核对后移除，运行卷未删除。

代码回滚使用独立提交的 `git revert`。Schema 回滚使用 Alembic downgrade 到 `p3_merge_0001`；如需继续回到 base，应先备份并按历史迁移逐级执行。禁止修改既有 revision、删除生产历史或删除数据库卷。
