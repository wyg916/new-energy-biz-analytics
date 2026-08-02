# 数据源接入治理

## 生命周期实测

对 P4 PostgreSQL 固定种子模拟数据执行了创建 → CredentialReference → 连通性测试 → Schema 发现 → 画像 → 数据分类 → 权限绑定 → 提交审核 → 批准 → 发布 → 激活 → 轮换 → 回滚。当前版本链为 v1 `SUPERSEDED`、v2 `ROLLED_BACK`、v3 `ACTIVE`；全部为 `charging_ops`、`simulated`，未接入真实客户数据。

停用后归档分支在最终 API 镜像中聚焦回归通过；归档只改变治理状态并保留审计、凭据引用和历史版本，不删除业务事实。最终 `test_p4_datasource_alerts.py` 为 2/2 PASS。

数据量核对：charging sessions 300000、sales orders 50000、sales order items 82514；发布语义指标共 27（charging 15 + sales 12），结果差异均为 `{}`。

## 安全负向结果

- 未审核数据源 ACTIVE 成功数：0。
- Secret 缺失或 Vault 不可用连接成功数：0。
- 跨 tenant/workspace 与跨场景访问成功数：0。
- 列级敏感字段绕过成功数：0。
- SQL 写入、多语句、危险函数、未发布 source 和自由 SQL 绕过成功数：0。
- SQLBot 仅能引用 ACTIVE Source Binding 中的只读关系；Binding 回滚后仍只读。

所有前端数据源状态来自 PostgreSQL 经正式 API 和统一授权返回，未从 fixture/Mock 构造。凭据值从不进入 API payload。

## 数据库、安全与回滚

迁移 `p4_0001` 增加预生产数据源治理、验收和告警投递表；升级和 downgrade 已验证。停用/归档不删除业务事实或审计。Source Binding 回滚创建/激活受治理的历史指向并保留所有版本；禁止直接改写 ACTIVE 行或删除数据库卷。
