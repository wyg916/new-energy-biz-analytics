# 技术架构基线 v0.1（已批准）

> 批准日期：2026-07-22
> 批准人：项目负责人王迎港
> 状态：**架构方向和开发前合同已冻结；运行时具体版本在 Phase 1 实施卡中确认**
> 来源：v1.1 第 10、12—15 章、附录 B—E 和 DEC-01—DEC-10

## 1. 架构结论

首版采用**模块化单体**，不拆微服务。前端、后端、任务进程、数据库和缓存可以独立运行，但共享统一领域模型、权限策略、指标语义层、运行状态和审计契约。

核心可信路径必须固定为：

```text
自然语言问题
  -> 身份与数据权限解析
  -> 会话状态解析（仅当前有权上下文）
  -> Query Plan 生成与 Schema 校验
  -> 指标/维度/关系/权限白名单校验
  -> 确定性参数化 SQL 编译
  -> Query Guard（AST、资源、只读与权限）
  -> 数据库执行
  -> 结构化分析结果
  -> Answer Guard
  -> 回答、图表与证据面板
```

LLM 不得绕过 Query Plan 和 Query Guard 直接执行核心 SQL；不得生成结构化结果中不存在的业务数字。

## 2. 技术栈候选基线

| 层级 | 候选技术 | 当前状态 | 冻结前必须补充 |
|---|---|---|---|
| 前端 | React + TypeScript + Ant Design + ECharts | 方向已设计 | Node/包管理器/框架版本、构建命令、浏览器范围 |
| 后端 | FastAPI + Pydantic + SQLAlchemy | 方向已设计 | Python 版本、依赖管理、同步/异步策略、API 版本策略 |
| 数据库 | PostgreSQL + pgvector | 方向已设计 | PostgreSQL/扩展版本、Schema、时区、字符集、备份边界 |
| 缓存/任务 | Redis + Celery | 方向已设计 | 版本、broker/backend、队列、幂等、重试、死信和超时 |
| SQL 解析 | SQLGlot 或等价 AST 工具 | 候选未决 | 固定工具和版本、支持的 PostgreSQL 语法子集 |
| 迁移 | Alembic | 方向已设计 | 分支策略、升级/降级规则、数据迁移与 DDL 边界 |
| 部署 | Docker Compose | 方向已设计 | 服务拓扑、镜像版本、卷、网络、健康检查和启动顺序 |
| 测试 | pytest + Playwright + 前端单测 | 方向已设计 | 测试命令、隔离数据库、fixture、覆盖门槛和 CI |
| 模型网关 | 统一 Model Gateway | 概念设计 | 供应商接口、离线替身、超时/重试/熔断、脱敏和成本字段 |

具体运行时版本、包管理器和端口必须写入 Phase 1 实施卡并由项目负责人确认，不得由实现者静默决定。

## 3. 推荐仓库结构

```text
E:\新能源企业经营分析智能平台\
├─ AGENTS.md
├─ README.md
├─ .gitignore
├─ .env.example
├─ pyproject.toml
├─ docker-compose.yml
├─ docs/
│  ├─ source/
│  │  └─ 新能源企业经营分析智能平台_v1.1.docx
│  ├─ 00_PROJECT_FACT_BASELINE.md
│  ├─ project_scope_baseline.md
│  ├─ architecture_baseline.md
│  ├─ implementation_readiness_report.md
│  ├─ decision_log.md
│  ├─ phase_plan.md
│  ├─ missing_inputs.md
│  ├─ data_model.md
│  ├─ metric_dictionary.md
│  ├─ query_plan_spec.md
│  ├─ sql_security.md
│  ├─ test_evaluation.md
│  ├─ acceptance_criteria.md
│  └─ adr/
├─ backend/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ core/
│  │  ├─ domain/
│  │  ├─ application/
│  │  ├─ modules/
│  │  │  ├─ identity/
│  │  │  ├─ data_ingestion/
│  │  │  ├─ metric_registry/
│  │  │  ├─ query_planner/
│  │  │  ├─ sql_compiler/
│  │  │  ├─ query_guard/
│  │  │  ├─ analysis_engine/
│  │  │  ├─ rag_service/
│  │  │  ├─ answer_service/
│  │  │  ├─ memory/
│  │  │  ├─ report_service/
│  │  │  └─ audit_observability/
│  │  └─ infrastructure/
│  └─ tests/
├─ frontend/
│  ├─ src/
│  │  ├─ app/
│  │  ├─ pages/
│  │  ├─ features/
│  │  ├─ entities/
│  │  ├─ shared/
│  │  └─ api/
│  └─ tests/
├─ migrations/
├─ data/
│  ├─ samples/
│  ├─ generators/
│  ├─ quality/
│  └─ evaluation/
├─ tests/
│  ├─ contract/
│  ├─ integration/
│  ├─ e2e/
│  ├─ security/
│  ├─ data_quality/
│  └─ evaluation/
├─ scripts/
└─ artifacts/
   └─ .gitkeep
```

该结构仅为规划，本轮不得据此创建业务代码或占位模块。

## 4. 目录职责

- `docs/source/`：保留不可改写的来源文档；执行基线使用版本化 Markdown。
- `docs/adr/`：记录已批准、不可静默改变的架构决定。
- `backend/app/domain/`：纯业务实体、值对象和领域规则，不依赖 FastAPI、数据库或模型 SDK。
- `backend/app/application/`：用例编排和端口；协调领域、权限、查询和审计。
- `backend/app/modules/`：按业务能力封装实现，模块之间通过显式接口交互。
- `backend/app/infrastructure/`：数据库、Redis、Celery、模型供应商和文件系统适配器。
- `frontend/src/features/`：按用户能力组织 UI，不直接复制后端领域逻辑。
- `migrations/`：唯一 Schema 变更来源，所有迁移必须可回滚或明确不可逆审批。
- `data/generators/`：只生成可复现模拟数据；不得包含真实企业数据或密钥。
- `tests/`：跨模块契约、集成、E2E、安全、质量和 AI 固定评测。
- `artifacts/`：本地运行证据输出；默认不提交大文件和敏感结果。

## 5. 依赖方向

### 5.1 后端

```text
API adapters -> application use cases -> domain/contracts
infrastructure adapters ----------------^ (implements ports)
```

规则：

- `domain` 不依赖 FastAPI、SQLAlchemy、Redis、Celery 或任何 LLM SDK；
- `application` 依赖领域契约和端口，不依赖具体供应商；
- `infrastructure` 实现端口，不反向定义业务规则；
- `query_planner` 只能产生待验证计划，不能持有数据库执行权限；
- `sql_compiler` 只接受已验证语义对象和权限范围；
- `query_guard` 的拒绝不可由调用方绕过；
- `answer_service` 只接收结构化结果和已授权证据；
- `memory_router` 在召回前必须先应用租户、组织、区域和对象权限硬过滤；
- 所有外部副作用通过 `analysis_run`/审计事件关联。

### 5.2 前端

- 页面只能通过版本化 API 客户端访问后端；
- 指标公式、权限判断、数据来源真值和 SQL 安全不得只存在于前端；
- 来源标签、数据时间、降级状态和 `run_id` 是结果契约的一部分，不是装饰字段；
- 图表只渲染后端返回的结构化数据与图表规格，不解析模型自然语言提取数字。

## 6. 模块契约基线

| 模块 | 输入 | 输出 | 关键不变量 |
|---|---|---|---|
| identity/policy | 用户、角色、组织、资源 | 授权上下文/拒绝原因 | 默认拒绝；权限先于数据与记忆召回 |
| metric_registry | 指标/维度/关系版本 | 已发布语义元数据 | 只有已发布版本可进入核心查询 |
| query_planner | 问题、授权上下文、会话状态 | Query Plan 或澄清 | 不输出可执行 SQL |
| sql_compiler | 已验证计划、语义关系 | 参数化 SQL、参数、hash | 同一输入确定性输出 |
| query_guard | SQL AST、参数、策略 | allow/reject | 拒绝不可绕过；单条只读 SELECT |
| analysis_engine | 数据集、分析类型 | 结构化趋势/比较/贡献/异常 | 贡献合计与总变化满足容差 |
| rag_service | 授权主题与元数据 | 知识证据 | 知识不提供当前业务数字 |
| answer_service | 结构化结果、证据、限制 | 回答与引用 | 业务数字来自结构化结果 |
| memory_router | 用户、作用域、意图、实体 | 授权记忆上下文 | 当前事实和明确指令优先 |
| report_service | 已验证运行结果 | 报告草稿/版本 | 不重新计算或编造数字 |
| audit_observability | 全链路事件 | 可追溯记录 | 状态真实、错误不泄密 |

## 7. 开发前必须冻结的接口

以下接口未冻结前，不允许多个实现线程并行修改基础模块：

1. 身份、租户、角色、组织/区域数据范围与导出权限；
2. 字段级数据模型、主外键、时区、金额精度和数据批次；
3. 指标定义 Schema、版本、状态和 15 项 P0 清单；
4. 维度、Join、基数和可用指标关系；
5. Query Plan JSON Schema、枚举、版本和澄清响应；
6. SQL Guard 白名单、资源阈值、拒绝码和审计字段；
7. 结构化查询结果、图表规格和证据面板契约；
8. `analysis_run` 状态机、错误码、幂等键和重放边界；
9. 来源标签和“模拟/公共/真实/缓存/降级/AI 生成”枚举；
10. P0 `session_state`、覆盖优先级、TTL 和并发版本；
11. API 版本策略、分页、时间/金额格式和统一错误信封；
12. 配置键、密钥注入、fail-closed 和日志脱敏规则。

## 8. 允许的后续并行开发

只有在上述契约冻结后，才可考虑：

- 前端基于已冻结 OpenAPI/样例数据开发，同时后端实现接口；
- 数据生成器与数据质量测试并行，但必须共享同一字段级模型；
- 指标公式测试与指标服务实现并行，但字典版本不可漂移；
- Query Plan 正/负样例与 Compiler 实现并行；
- SQL Guard 负向语料与 Guard 实现并行；
- 文档、测试和相对独立的 UI 状态可以并行；
- 报告模板设计可在结构化结果与证据契约冻结后并行。

## 9. 禁止同时推进的工作

- 数据模型仍在变更时，同时开发迁移、数据生成器、指标服务和页面；
- 指标清单/公式未冻结时，同时开发驾驶舱、ChatBI 和归因；
- 权限模型未冻结时，同时开发查询、记忆召回和导出；
- Query Plan Schema 未冻结时，同时开发 Planner、Compiler 和前端证据面板；
- `analysis_run` 状态与证据契约未冻结时，同时开发报告和历史案例记忆；
- 将 P1 长期记忆、Agent 或自由 SQL 与 P0 基础链路同时开发。

## 10. 数据与记忆边界

权威优先级建议冻结为：

```text
当前明确指令
> 当前已验证 Query Plan
> 组织强制规则
> 最新成功业务数据与已发布指标版本
> 用户长期偏好
> 已确认历史案例
> 模型临时推断
```

权限过滤必须发生在向量检索和关键词检索之前。任何被拒绝的记忆不得泄露标题、摘要、命中数量或存在性。

## 11. 运行、部署与回滚原则

- 配置缺失、权限不明或安全策略加载失败时拒绝启动；
- 数据刷新失败不得覆盖最近成功数据；
- 迁移先备份/验证，再升级；每个迁移提供 downgrade 或审批过的替代恢复方案；
- 测试使用隔离数据库/临时目录，不连接生产；
- Compose 服务必须有健康检查和明确启动依赖；
- 模型不可用时保留结构化结果并明确降级；
- 报告、缓存和异步任务必须可由 `run_id` 重放或判定幂等；
- 任何回滚都不得回滚或伪造审计事实。

## 12. 已冻结的开发前合同

- `docs/data_contract_v0.1.md`；
- `docs/metric_dictionary_v0.1.md`；
- `docs/query_plan_contract_v0.1.md`；
- `docs/rbac_and_sql_security_contract_v0.1.md`；
- `docs/memory_contract_v0.1.md`；
- `tests/evaluation/chatbi_evaluation_set_v0.1.json`；
- `docs/prototypes/index.html`。

上述产物是 Phase 1—后续阶段的设计输入，不代表实现或测试完成。破坏性字段、指标、Query Plan、权限或记忆变更必须升级合同版本并执行 DoR 复审。
