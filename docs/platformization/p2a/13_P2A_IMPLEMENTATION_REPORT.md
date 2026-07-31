# P2A 实施报告

更新时间：2026-07-31

## 完成内容

- 固定 SQLBot v1.8.0 隔离 Compose、镜像、健康和故障隔离；
- charging_ops/sales_ops SQLBot 语义 Schema/View 与独立只读角色；
- 统一 Model Gateway 合同、路由、主备、重试、熔断、统计和脱敏；
- Knowledge Service、版本生命周期、发布/撤回/回滚和权限前置；
- 关键词检索、去重/Rerank、引用、注入检测和审计；
- 四 Profile Response Composer；
- 数据、知识、数据加制度三路编排；
- 自有 React 知识库、回答风格、状态、引用和反馈；
- 60 条 RAG Golden Set 与全量回归；
- 多 Schema Alembic 全循环验收器改为专用临时数据库。

## 迁移与数据

- `0013`：6 张 Knowledge 生命周期/检索表；
- `0014`：两个 SQLBot 语义 Schema、9 个受控 View；
- 当前业务数据库：0014、62 张 public base table、653905 行；
- knowledge：3 documents、3 versions、33 chunks；
- charging sessions=300000；
- sales orders=50000；
- sales order items=82514。

行数增量来自审计、查询路由、反馈、知识和检索事件；两场景核心事实未改变。
并发出现的未跟踪 0015 不属于本报告且未进入数据库。

## 测试

后端 163/163、DQ 20/20、charging 15/15、sales 12/12、Deterministic
40/40、离线双引擎 100/100、Docker smoke 6/6、迁移全循环 PASS、只读禁止
操作成功数 0、Vitest 3/3、Playwright 20/20、npm audit 0。

SQLBot 实际模型/查询/Shadow 和完整向量检索没有通过，未使用 Mock 或关键词
指标冒充。

## 最终状态

- `P0_EXTERNAL_SECURITY = PENDING`
- `SQLBOT_RUNTIME = CONDITIONAL`
- `SQLBOT_SHADOW = NOT PASS`
- `MODEL_GATEWAY = CONDITIONAL`
- `RAG_FOUNDATION = CONDITIONAL`
- `RESPONSE_COMPOSER = PASS`
- `P2A_IMPLEMENTATION = CONDITIONAL`
- `SQLBOT_CANARY_ELIGIBLE = false`
- `P2B_ENTRY = NOT_ALLOWED`

P2B 暂不允许进入：SQLBot 仍未完成真实模型和至少一条实际 NL2SQL/执行证据，
完整 Shadow、运行阈值与向量检索也未关闭。P0 外部安全未关闭时继续禁止真实
外部数据、生产发布和生产 Canary。

## 回滚

应用即时回退：

```text
SQLBOT_ENGINE_ENABLED=false
SQLBOT_RUNTIME_VERIFIED=false
CHATBI_READONLY_EXECUTION_ENABLED=false
QUERY_ENGINE_MODE=DETERMINISTIC_ONLY
```

SQLBot 可停止并删除容器但保留独立卷；知识版本可 retire/rollback；数据库可
依次 downgrade 0014/0013；代码按本报告提交列表逆序 `git revert`。不得删除
业务数据库卷。
