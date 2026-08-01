# P2A SQLBot Canary 决策

> 当前有效决策：2026-08-01。下方旧决策中的 Provider 401 原因已失效，但 `NO_GO` 结论仍成立。

## 当前决策：NO_GO

```text
SQLBOT_CANARY_ELIGIBLE=false
QUERY_ENGINE_MODE=SHADOW
CANARY_DECISION=NO_GO
P2A_RUNTIME_CLOSEOUT=CONDITIONAL
P2B_ENTRY=ALLOWED_WITH_SQLBOT_REMAINING_SHADOW
```

安全门禁满足：只读角色写入、DDL、系统表、public 原表和跨场景成功数均为 0；运行 Golden 的 permission violation rate 为 0%。但质量门禁明显未满足：Smoke 全链路 1/10，Golden Guard pass 2%、拒答准确率 15%、幻觉字段率 8%，Execution Accuracy 与 Metric Value Accuracy 因缺少值 oracle 不能判定，Shadow 无 SQLBot result hash 可比较，且 Golden/Shadow trace 均包含恢复标记。

另有产品接入阻断：ACTIVE source binding 尚未发布 `sqlbot_datasource_id`，本轮运行器仅在验收时显式绑定已批准的 Datasource 1/2。修复前不得开启产品 Canary。

依据任务门槛，真实 Provider、真实 SQL、真实只读上游执行、20 条真实 Shadow 和安全成功数 0 已成立，因此允许以 `CONDITIONAL` 关闭 P2A 并进入 P2B；P2B 不得借此开启 Canary、替换确定性主路径或宣称生产可用。

---

## 旧决策快照（原因已取代）

更新时间：2026-07-31

## 1. 决策

```text
SQLBOT_CANARY_ELIGIBLE=false
QUERY_ENGINE_MODE=SHADOW
SQLBOT_CANARY=NOT_ELIGIBLE
```

当前不得把 SQLBot 放入用户可见主链、5% 流量或生产默认部署。该结论不是对
离线 100/100 的否定，而是因为 live 模型、实际 NL2SQL、执行准确率和真实
Shadow 均没有可验证证据。

## 2. 门禁对照

| 门禁 | 当前证据 | 结果 |
|---|---|---|
| 危险 SQL 成功数 | 只读角色实际负向验证为 0 | PASS |
| 越权/基础表成功数 | 实际负向验证为 0 | PASS |
| 跨场景成功数 | 实际负向验证为 0 | PASS |
| 核心指标值准确率 100% | live Golden 未执行 | NOT_AVAILABLE |
| Execution Accuracy >= 90% | live Golden 未执行 | NOT_AVAILABLE |
| 幻觉表率 <= 2% | live Golden 未执行 | NOT_AVAILABLE |
| 幻觉字段率 <= 2% | live Golden 未执行 | NOT_AVAILABLE |
| 拒答准确率 >= 95% | 只有离线合同结果 | NOT_AVAILABLE |
| 20 条真实 Shadow | 0/20；故障降级验证 20/20 不计入 | NOT_PASS |
| SQLBot 故障不影响主答案 | 隔离平台请求 20/20 | PASS |

只读角色安全结果不能替代模型运行安全指标，离线 Golden 也不能替代实际执行
准确率。未达到全部门禁，因此无权开启 Canary。

## 3. 当前允许范围

- SQLBot 独立容器和 Datasource 仅用于 `LOCAL_ACCEPTANCE_ONLY`；
- 平台主回答继续由 DeterministicEngine 产生；
- SQLBot 开关保持 fail-closed；
- 完整模型合同注入后，必须依次重新执行 10 条 Smoke、100 条运行 Golden 和
  20 条真实 Shadow，再重新作出 Canary 决策；本轮真实阻断码为
  `PROVIDER_AUTHENTICATION_FAILED`，不是缺少配置。

## 4. 回滚

即时运行回滚为：

```text
SQLBOT_ENGINE_ENABLED=false
SQLBOT_RUNTIME_VERIFIED=false
CHATBI_READONLY_EXECUTION_ENABLED=false
QUERY_ENGINE_MODE=DETERMINISTIC_ONLY
```

该回滚不删除 SQLBot 或 PostgreSQL 数据卷。
