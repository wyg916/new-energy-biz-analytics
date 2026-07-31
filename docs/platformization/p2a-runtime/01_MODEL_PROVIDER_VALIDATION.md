# Model Provider 运行验证

更新时间：2026-07-31

## 1. 发现边界

本轮只检查 Provider 别名、合同字段是否存在、CredentialReference 是否存在、
启用状态、任务类型和允许的数据分类。未读取、打印、记录或提交任何 API Key、
Token 或秘密值，也未猜测未知端点或向未知外部服务发送请求。

| Provider 候选 | base URL | model name | CredentialReference | credential value | enabled |
|---|---|---|---|---|---|
| kimi | 未配置 | 未配置 | `env://MODEL_GATEWAY_KIMI_API_KEY` | 未注入 | false |
| mimo | 未配置 | 未配置 | `env://MODEL_GATEWAY_MIMO_API_KEY` | 未注入 | false |
| deepseek | 未配置 | 未配置 | `env://MODEL_GATEWAY_DEEPSEEK_API_KEY` | 未注入 | false |

三个候选的已实现合同任务类型为 `rag_answer_generation`，允许
`public`、`simulated` 数据分类。当前没有合同完整且已启用的
OpenAI-compatible Provider，不能选择主模型或备用模型。

## 2. 运行验证结果

- 配置完整性：NOT_PASS；
- DNS/网络：未执行，禁止向未知端点发请求；
- Provider health：未执行；
- `/models` 或最小 completion：未执行；
- Token/usage：无 live 记录；
- 超时、无效凭据脱敏、重试、主备和熔断：已有自动化合同测试，不计入 live
  Provider 结果；
- Mock：未用于本轮运行状态或准确率。

`HUMAN_MODEL_CONFIG_REQUIRED`

最小人工输入清单：

1. `provider`
2. `base_url`
3. `model_name`
4. `credential_ref`

具体 Secret 只能注入不跟踪运行时环境，不能写入 Git、普通日志、数据库业务
字段、前端构建或验收证据。

## 3. 结论

`MODEL_RUNTIME = NOT_PASS`

该状态阻止 SQLBot live NL2SQL、10 条 live Smoke、100 条运行 Golden Set 和
20 条真实 Shadow，但不阻止完成隔离数据库、Datasource、只读安全、Adapter
兼容、故障降级、pgvector 与供应链检查。

