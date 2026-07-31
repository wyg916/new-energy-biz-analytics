# P2A Runtime、RAG 与 Response 范围及基线

更新时间：2026-07-31

## 状态

- 工作包：`P1B-RUNTIME-CLOSEOUT + P2A-RAG-RESPONSE`
- 分支：`feat/p2a-sqlbot-runtime-rag-response`
- 基线分支：`feat/p1b-dual-engine-sales-ops`
- 基线提交：`e34ae08399a4ad6d288fe3794e580be3b2e92d47`
- `P0_EXTERNAL_SECURITY = PENDING`
- `P1B_IMPLEMENTATION = PASS`
- `MULTI_SCENARIO = PASS`
- `SQLBOT_ADAPTER = PASS`
- `SQLBOT_RUNTIME = PENDING`
- `SQLBOT_CANARY_ELIGIBLE = false`

本轮开始时 GitHub 实时 fetch 不可达，缓存远端 P1B 引用与本地基线差异
`0/0`，状态记为 `REMOTE_RUNTIME_UNVERIFIED`。Docker Desktop 初始停止，已从
本机 D 盘安装位置启动；现有 Compose 使用原数据卷恢复，未删除或重建卷。

## 当前运行基线

- API、PostgreSQL、Redis：healthy；
- Web：running；
- Alembic：`0012 (head)`；
- 表：56；
- 总行数：653046；
- charging_ops 充电会话：300000；
- sales_ops 订单：50000；
- sales_ops 订单行：82514；
- `PLATFORM_VERSION_ROUTING_ENABLED` 有效值：development 为 true；
- `SQLBOT_ENGINE_ENABLED=false`；
- `SQLBOT_RUNTIME_VERIFIED=false`；
- `CHATBI_READONLY_EXECUTION_ENABLED=false`。

总行数较 P1B 收口增加 17 行，来自既有运行中的审计、路由或反馈类记录；
charging_ops 和 sales_ops 核心事实计数未改变。

## 轨道 A：P1B Runtime Closeout

1. 固定 SQLBot `v1.8.0` / `b2de038` 的实际镜像、容器和健康证据；
2. 建立 charging_ops、sales_ops 专用 semantic schema/view；
3. 建立独立只读 LOGIN 角色和 CredentialReference；
4. 完成写入、系统表、跨场景、版本、字段、超时和大结果负向测试；
5. 通过 Model Gateway 配置实际模型；
6. 真实执行 SQLBot 100 条 Golden Set 和 Shadow 比较；
7. 仅在阈值通过后允许开发环境 5% Canary。

SQLBot 镜像、模型或网络不可用时必须记录 PENDING，不能使用 Mock 冒充真实
Runtime、实际准确率或真实 Shadow。

## 轨道 B：P2A RAG 与 Response

1. 项目二统一 Model Gateway；
2. Knowledge Service 与文档/版本/Chunk 生命周期；
3. 发布、撤回、替代和回滚；
4. 关键词与向量混合检索、元数据硬过滤、融合、去重和 Rerank；
5. 引用、Claim 绑定、过期拒绝和 RAG Prompt Injection 防护；
6. 四种 Response Profile 和统一最终回答合同；
7. 数据问题、知识问题、数据加制度复合问题编排；
8. 自有 React UI 的知识管理、检索证据、引用和回答风格；
9. 60 条 RAG Golden Set 与安全验收。

## 模型秘密边界

用户已提供三组模型运行凭据，但仓库规则继续生效：

- 只通过环境变量或 CredentialReference 解析；
- 不写入 Git、Compose、数据库明文字段、日志、测试快照或前端；
- 不在文档和验收输出中复述；
- 当前约定的三个模型环境引用尚未注入运行进程；
- 在环境引用和官方 base URL/model contract 可验证前，实际模型状态保持
  `MODEL_RUNTIME_PENDING`。

Mock Provider 只用于自动化合同测试，不计入实际模型、SQLBot 或 RAG 运行
准确率。

## RAG 知识源边界

首批知识源只允许仓库内已跟踪、无秘密、已批准的正式文档。四份用户源文档
必须继续保持：

- 未跟踪；
- 未修改；
- 未删除；
- 未提交；
- 未自动发现；
- 未进入 Knowledge Service 或任何索引。

## 非目标

- 长期用户偏好、情景记忆、程序性记忆；
- 自动反思和多 Agent；
- 第三个业务场景；
- OCR、图像知识库和复杂 PDF 表格；
- 完整知识图谱；
- Kubernetes、完整 SSO 和生产发布；
- 真实外部企业数据；
- 生产 Canary 或大规模 UI 重设计。

## 安全与真实性

- 核心指标仍来自已发布语义层；
- LLM 不直接生成并执行核心 SQL；
- 权限过滤必须在 SQL 执行和知识召回前完成；
- Query Guard 和 RAG 安全拒绝不可绕过；
- SQLBot 原始回答和 RAG 原始 Chunk 不直接返回用户；
- 页面、答案和证据继续显示模拟数据、数据时间、来源和 run_id；
- 不宣称生产上线、真实客户、真实数据或真实经营收益。

## 迁移与回滚

新增迁移编号必须从当前 `0012` head 现场产生并支持 downgrade。禁止不可逆
迁移、删除数据库卷或覆盖 P1B 证据。

即时逻辑回退：

```text
PLATFORM_VERSION_ROUTING_ENABLED=false
QUERY_ENGINE_MODE=DETERMINISTIC_ONLY
SQLBOT_ENGINE_ENABLED=false
```

每个工作包独立提交并可使用 `git revert` 回滚。
