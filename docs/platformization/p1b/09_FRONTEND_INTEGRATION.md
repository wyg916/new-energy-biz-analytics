# 自有 UI 双场景接入

更新时间：2026-07-30

## 实现结论

项目继续使用现有 React UI 和项目二后端 API。没有 iframe、没有嵌入 SQLBot
用户页面，浏览器不接触 SQLBot Token、账号、密码、internal chat_id 或原始
响应结构。

`GET /api/v1/chat/scenarios` 返回当前注册场景及 ACTIVE 状态；`POST
/api/v1/chat/query` 新增向后兼容的 `scenario_id`，默认仍为
`charging_ops`。前端切换场景时立即创建新的 conversation，不复用另一场景
会话。

## 插件分派

`ScenarioChatServiceRegistry` 以注册表映射：

- `charging_ops` → 现有 `ChatBIService`
- `sales_ops` → `SalesOpsChatService`

API 核心不包含 `if scenario == "sales_ops"` 业务分支。sales_ops 继续复用：

- IdentityContext
- ACTIVE Scenario/Dataset/Semantic 解析
- QueryContext
- QueryEngine
- EngineRouter
- SQLBotEngine Adapter
- RoutingEvidenceRepository
- 统一 QueryResult

`0012` 新增 `chat_scenario_session_binding`，把每个 conversation 固定绑定到
tenant、workspace、subject 和 scenario。跨用户或跨场景复用会话明确返回
403；没有通过前端重置替代服务端隔离。

## Response Composer

sales_ops 的用户答案由项目二 `SalesOpsChatService` 从结构化 QueryResult
组合，所有数字均来自 `rows` 和证据中的时间范围。SQLBot 原始自然语言回答
不会直接显示。回答明确标记：

- 模拟数据；
- 数据时间范围；
- ACTIVE sales_ops 数据集和语义版本；
- 项目平台数据来源。

无法明确指标或时间时返回稳定错误码，例如 `METRIC_AMBIGUOUS` 和
`TIME_RANGE_AMBIGUOUS`，UI 显示错误/拒答状态，不静默改问其他问题。

## UI 证据

AI 经营分析页面现在显示：

- 当前场景和 ACTIVE 状态；
- DatasetVersion；
- SemanticModelVersion；
- 当前引擎；
- SHADOW/CANARY 模式；
- 模拟数据和平台数据来源；
- 查询耗时；
- Query Plan；
- SQL 证据展开区；
- warnings；
- Query Guard / Answer Guard；
- analysis_run_id；
- route_decision / route_reason；
- 错误、拒答和澄清信息。

SQL 文本只有在当前引擎确实提供且角色有权时显示；SalesOps SQLAlchemy 受控
聚合没有伪造 SQL 字符串。收藏、导出和分享仍保持禁用并显示“未开放”，没有
假交互。

## 用户反馈

新增 `POST /api/v1/chat/feedback`。反馈前验证：

1. conversation 属于当前身份；
2. conversation 场景与反馈场景一致；
3. run_id 在当前 subject/scenario 的路由证据中存在。

通过后写入 `AuditLog(action=chat.feedback)`。UI 的“有帮助 / 需改进”按钮在
成功写入后禁用并显示“反馈已记录到审计日志”。

## 场景切换竞态

E2E 首轮发现快速切换场景时，旧场景慢响应可能覆盖新会话。前端已增加：

- 当前场景 ref；
- 单调请求序号；
- 只允许当前场景最新请求更新 result、conversation、error 和 loading。

后端跨场景拒绝保持不变。修复后快速切换和歧义拒答 E2E 通过。

## 测试证据

- 双场景 API、目录、隔离、反馈、拒答：`1/1 PASS`；
- Alembic：`base → 0012 → 0011 → 0012 PASS`；
- 前端 Vitest：`3/3 PASS`；
- 前端生产构建：PASS；
- 既有 AI 经营分析一屏 E2E：PASS；
- 双场景切换、反馈、歧义拒答、无 iframe E2E：PASS；
- 本工作包 E2E 合计：`2/2 PASS`；
- 当前 PostgreSQL：`0012 (head)`；
- charging_ops 事实：300,000；
- sales_ops 订单：50,000。

Playwright 缓存缺少锁定版本的 bundled Chromium，首次启动前失败；测试随后
通过仓库已支持的 `PLAYWRIGHT_EXECUTABLE_PATH` 使用本机 Chrome 执行。该
环境处理没有修改依赖或安装全局软件。

## 回滚

1. 配置 `QUERY_ENGINE_MODE=DETERMINISTIC_ONLY`；
2. 前端切回只显示 charging_ops 的上一提交；
3. 回滚本提交；
4. 如需回退会话绑定 Schema，执行 `alembic downgrade 0011`。

降级 `0012` 只删除跨场景会话绑定表，不删除 charging_ops 或 sales_ops
事实数据，不需要删除数据库卷。
