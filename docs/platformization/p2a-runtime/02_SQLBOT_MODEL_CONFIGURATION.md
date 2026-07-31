# SQLBot 模型配置

更新时间：2026-07-31

## 1. 固定运行时

- 上游：SQLBot `v1.8.0` / `b2de038`
- 镜像 ID：`sha256:5065baf17703cfad0407261c16d15c0aecb237877011e1603f59fb70a1f58abf`
- 原实例：`renewable-sqlbot-v1-8-0`，保持 running/healthy，未重建、未修改卷
- 独立验收实例：`renewable-sqlbot-p2a-runtime-v1-8-0`
- 独立验收端口：仅绑定 `127.0.0.1:18081`
- 用途：`LOCAL_ACCEPTANCE_ONLY`

原实例持久化管理员哈希与当前 bootstrap 运行时引用不一致。为避免读取旧凭据、
直接改写 SQLBot 内部数据库或破坏原卷，本轮创建新容器和新卷。新卷首次恢复
超过上游固定 120 秒等待窗口，使用仓库中的有界本地验收启动脚本等待内置
PostgreSQL 就绪；稳定后容器 running、HTTP 200、restart_count=0。

新实例通过 SQLBot 正式 API 将公开镜像初始管理员状态立即轮换到运行时引用。
脚本不复制、输出或提交初始值和新值。管理 UI 未嵌入产品 UI。

## 2. 模型配置事实

三家合同字段和运行时引用已完整，但真实 `/models` 均返回 HTTP 401，因此没有
可用 live Provider，未向 SQLBot 提交无效模型配置：

| 项目 | 结果 |
|---|---|
| provider | kimi/mimo/deepseek 均认证失败 |
| model_name | 未配置 |
| model configuration id | 未产生 |
| configuration method | 未执行 |
| provider health | DNS PASS；`/models` 3/3 HTTP 401 |
| configured_at | 无 |
| live non-Mock response | 无 |
| token/latency | 无 |

使用运行时管理员引用完成认证后，通过 v1.8.0 正式
`GET /api/v1/system/aimodel` 接口只读取安全摘要：认证 HTTP 200、列表 HTTP
200、模型配置数量 0。查询过程没有输出管理员密码、访问 Token、模型响应或
Datasource configuration。这证明当前并非“平台未发现 SQLBot 内已有模型”，
而是固定验收实例确实尚未配置模型。

SQLBot 的 `/system/aimodel` 正式接口和实际数据模型已从固定容器源码核验。
本轮不是缺少人工配置，而是实际认证失败；不把 preferred model 当作已发现
model ID，不向 SQLBot 写入无法验证的 supplier/protocol，也不使用 Mock 冒充。

## 3. Adapter 兼容修复

实际 v1.8.0 路由为：

```text
/api/v1/mcp/mcp_start
/api/v1/mcp/mcp_question
/openapi.json
```

原客户端对 MCP 使用绝对路径，实际会丢失 `/api/v1`。本轮改为保留 API 前缀
的相对路径。固定镜像的根路径 `/` 返回 200，并由容器 Healthcheck 使用；
`/openapi.json` 实际返回 401，因此 Adapter 健康探针改为独立解析根路径，
避免将健康实例误报为 unavailable。专项测试同时断言三个实际路径。

## 4. 安全与回滚

- 模型 Key、Token 和完整响应进入 Git 的数量为 0；
- Provider 未配置时返回真实 Pending，不伪造模型结果；
- 原健康 SQLBot 容器和卷未变更；
- 验收实例可停止但保留新卷；
- 应用保持 `SQLBOT_ENGINE_ENABLED=false`、
  `SQLBOT_RUNTIME_VERIFIED=false`。

`SQLBOT_MODEL_CONFIGURATION = BLOCKED_BY_PROVIDER_AUTHENTICATION`
