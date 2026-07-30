# SQLBot 固定版本与隔离部署

更新时间：2026-07-30

## 版本结论

- 上游仓库：`dataease/SQLBot`
- 固定版本：`v1.8.0`
- 上游发布页显示的提交：`b2de038`
- 固定镜像引用：`dataease/sqlbot:v1.8.0`
- 当前实际运行状态：`SQLBOT_RUNTIME_PENDING`

上游 `v1.8.0` 是本轮核对到的最新稳定发布，发布于 2026-04-30，并包含权限提升与提示词注入漏洞修复。版本来源：

- https://github.com/dataease/SQLBot/releases/tag/v1.8.0
- https://github.com/dataease/SQLBot/commit/b2de038

本机访问 Docker Registry 超时，尚未成功取得镜像 manifest。因此本轮只把明确版本作为部署合同固定，不能声称镜像已拉取、容器已启动或真实 SQLBot 健康检查已通过。

## 许可证边界

SQLBot 使用带附加条件的 GPLv3：

- 不得删除或修改 SQLBot 前端 Logo 和版权信息；
- 衍生代码承担 GPLv3 开源义务；
- 详细条款以固定版本原始许可证为准。

许可证来源：https://github.com/dataease/SQLBot/blob/v1.8.0/LICENSE

本项目不复制或修改 SQLBot 源码，不嵌入其用户 UI，仅通过独立容器和后端 Adapter 使用上游能力。`deploy/sqlbot/UPSTREAM_LICENSE.md` 保留上游版权和许可证边界。

## 生成与执行分离核对

固定版本源码存在内部枚举 `ChatFinishStep.GENERATE_SQL`，内部 `question_answer_inner` 也接受 `finish_step`。但公开 MCP `mcp_question` 请求合同没有 `finish_step` 字段，公开实现调用默认问数流程，未提供受支持的执行前 Hook 或自定义执行器注入点：

- https://github.com/dataease/SQLBot/blob/v1.8.0/backend/apps/chat/models/chat_model.py
- https://github.com/dataease/SQLBot/blob/v1.8.0/backend/apps/chat/api/chat.py
- https://github.com/dataease/SQLBot/blob/v1.8.0/backend/apps/mcp/mcp.py

因此当前不能把上游公开 API 宣称为“可靠的仅生成 SQL 接口”。平台 Adapter 支持解析并审计上游返回的 SQL，但 SQLBot 实际运行只能在以下条件全部满足后进入 Shadow：

1. 独立只读角色；
2. 只开放场景专用 semantic schema/view；
3. 事务只读和 statement timeout；
4. 表、字段、行数与并发限制；
5. 当前 ACTIVE DatasetVersion、SemanticModelVersion 和 ScenarioVersion 绑定；
6. 项目 Query Guard 对实际 SQL 的独立校验；
7. SQLBot 故障不影响 DeterministicEngine。

在上述运行验收完成前，SQLBot 不进入 Canary 或用户可见链路。

## 部署隔离

部署文件位于 `deploy/sqlbot/`：

- 固定 `dataease/sqlbot:v1.8.0`，不使用 `main/latest`；
- 独立 Compose 项目、容器、卷和内部网络；
- 管理 UI 只绑定 `127.0.0.1:18080`；
- 平台后端通过私有 `renewable-sqlbot-proxy` 网络调用；
- 必需秘密只能从未跟踪的本地环境注入；
- 浏览器不接触 SQLBot Token、账号、密码或内部 chat_id；
- 不使用平台可写数据库账号，不连接真实外部企业数据。

固定上游镜像仍要求 `privileged` 本地容器运行，这是当前已知安全限制，只允许隔离本地评测，不满足生产部署条件。

## 验收状态

- 版本和许可证核对：`PASS`
- Compose 静态合同：待配置校验
- 镜像 manifest：`PENDING`，Docker Registry 网络超时
- 容器启动：`PENDING`
- 真实 SQLBot 健康检查：`PENDING`
- 模拟数据源真实调用：`PENDING`
- 总状态：`SQLBOT_RUNTIME_PENDING`

Mock Server 仅用于 Adapter 合同、错误映射、超时、熔断和会话隔离测试，不作为上述真实运行证据。
