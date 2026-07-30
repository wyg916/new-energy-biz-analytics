# 目标模块地图

该地图是 Phase 1 之后的演进目标，不表示目录已经重构完成。继续保持模块化单体。

```text
backend/app/
  platform/
    identity/          # IdentityContext、策略、审计
    connectors/        # Connector SDK 与注册
    datasets/          # 定义、版本、发布、激活、回滚
    semantic/          # 语义模型、指标、join graph
    query/             # Query Plan、编译器接口、Guard、执行
    knowledge/         # KnowledgeProvider 接口
    memory/            # MemoryProvider 接口
    scenarios/         # 场景包注册、校验、生命周期
    observability/
  scenarios/
    charging_ops/
      models/
      mappings/
      semantic/
      chatbi/
      diagnostics/
      reports/
      samples/
  api/
```

## 依赖方向

1. `platform/*` 不得导入 `scenarios/charging_ops/*`。
2. 场景实现只能依赖已版本化的平台接口。
3. API 层依赖应用服务，不直接依赖 ORM 业务表。
4. 看板、ChatBI、诊断和报告通过同一 `QueryContext` 解析 scenario、semantic 和 dataset ACTIVE 版本。
5. Provider 接口不强制微服务或外部基础设施，P0/P1 可在单体进程内实现。

## 当前路径到目标

| 当前路径 | 目标 |
| --- | --- |
| `app/chatbi/guard.py` | `platform/query/guard.py` |
| `app/chatbi/plan.py` 的通用形状 | `platform/query/plan.py` |
| `app/chatbi/parser.py`、`compiler.py` | `scenarios/charging_ops/chatbi/` |
| `app/services/metric_catalog.py` 框架 | `platform/semantic/registry.py` |
| charging 指标定义 | `scenarios/charging_ops/semantic/` |
| `app/services/data_integration.py` | 拆为 platform connector/dataset 服务与 charging adapter |
| `app/models/integration.py` | 平台版本表与 charging staging/snapshot 分离 |
| `app/scenarios/registry.py` | `platform/scenarios/registry.py` |

## 不做的重构

P0 不执行目录大搬迁、不拆数据库、不改变现有 API 路径；先用合同测试约束行为，随后按 `11_MIGRATION_ROADMAP.md` 渐进抽取。

