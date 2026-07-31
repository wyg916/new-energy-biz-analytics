# 项目二统一 Model Gateway

更新时间：2026-07-31

## 实现

`backend/app/ai/model_gateway/` 已实现 contracts、config、credentials、
registry、OpenAI-compatible client、router、usage、health、errors 和 runtime。

统一合同覆盖：

- provider、base_url、model_name、credential_ref、task_type；
- data_classification、timeout、max_tokens、temperature；
- 一次受控重试、fallback、熔断；
- Token/时延统计、标准错误和健康状态；
- 日志与返回值不携带 API Key。

Mock Provider 只在自动化合同测试中使用。Model Gateway 专项 `5/5 PASS`。

## 运行配置

三个候选 Provider 仅保存环境引用：

- `env://MODEL_GATEWAY_KIMI_API_KEY`
- `env://MODEL_GATEWAY_MIMO_API_KEY`
- `env://MODEL_GATEWAY_DEEPSEEK_API_KEY`

仓库、Compose、数据库、日志、前端和测试快照均没有明文模型秘密。用户提供了
运行凭据，但没有可验证的正式 base URL 与精确 model contract；因此未猜测
端点、未向未知服务发送请求，三个 Provider 默认 disabled。

实际状态：`MODEL_RUNTIME_PENDING`。实现合同通过但没有 live provider 调用，
所以：

`MODEL_GATEWAY = CONDITIONAL`

回滚方式是保持所有 provider disabled；不影响确定性查询、RAG 关键词检索或
Response Composer 的确定性路径。
