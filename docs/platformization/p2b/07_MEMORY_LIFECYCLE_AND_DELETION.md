# Memory 生命周期与删除

## 生命周期

生命周期服务处理 TTL、有效期、衰减、归档、SUPERSEDED、冲突、撤回和软删除。
Legal Hold 字段为保留控制预留；处于 Hold 的记录不会被普通彻底删除流程绕过。

## 用户删除闭环

用户删除请求先按 IdentityContext 定位目标，然后执行 PostgreSQL 删除/匿名化策略、
Redis key 清理、派生检索索引清理和缓存失效。已删除记录的 status/deleted_at 会在召回
SQL 中被硬排除，不能依赖后置模型过滤。

系统保留最小 `memory_deletion_audit`：删除请求 ID、主体/作用域哈希、执行状态、策略、
时间和清理组件，不保留被删除的业务内容。删除和回放使用幂等键，重复请求不会重复生成
有效记录。

## 回滚边界

代码和 Schema 可回滚；已执行且不处于 Legal Hold 的用户彻底删除不可恢复。测试只删除
明确命名的临时数据库，不删除 Docker 卷。
