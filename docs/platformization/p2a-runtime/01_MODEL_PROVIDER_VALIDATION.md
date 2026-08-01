# Model Provider 运行验证

> 当前有效结果：2026-08-01。下方 2026-07-31 的 401 内容为修正官方调用方式之前的预运行快照，已由本节和 `12_OFFICIAL_PROVIDER_INTEGRATION_RESULT.md` 取代。

## 当前运行结论

| Provider | 官方认证方式 | 模型发现 | 实际模型 | 文本/JSON/SQL | 最终状态 |
|---|---|---|---|---|---|
| Kimi | `Authorization: Bearer` | `/v1/models` 200 | `kimi-k2.6` | 3/3 PASS | PASS |
| DeepSeek | `Authorization: Bearer` | `/models` 200 | `deepseek-v4-flash` | 3/3 PASS | PASS |
| MiMo | `api-key` | 直接 chat/completions 200 | `mimo-v2.5-pro` | 文本、JSON 通过；SQL 因 256 token 截断未通过 | FAIL |

凭据解析采用 `UTF-8-sig`，重复变量、空值、内部换行和不可见字符均为 0。文件值与请求值指纹一致：Kimi `8de8aeb2b724`、MiMo `a3176a0ce95f`、DeepSeek `e1bf1d4615e9`。完整 Key 输出数为 0。

DeepSeek 三项延迟为 1431/1986/2226 ms，Kimi 为 3271/4743/14237 ms，因此选择 DeepSeek 为 SQLBot 主模型、Kimi 为第一备用。MiMo Bearer 未执行：官方 `api-key` 首次即返回 200，按验收合同不应继续发送第二种认证。

---

## 预运行快照（已取代）

更新时间：2026-07-31

## 1. 配置与安全边界

用户授权从仓库外
`E:\新能源企业经营分析平台_runtime_secrets\p2-models.env` 将三家凭据只注入
当前验证进程。文件未复制进仓库，完整 Key 未输出、未写入 JSON/Markdown、未
传给前端，也未写入数据库。六个非秘密字段均存在：

| Provider | base URL | preferred model | auth |
|---|---|---|---|
| kimi | `https://api.moonshot.cn/v1` | `kimi-k2.6` | `Authorization: Bearer` |
| mimo | `https://api.xiaomimimo.com/v1` | `mimo-v2.5-pro` | Bearer 后复核 `api-key` |
| deepseek | `https://api.deepseek.com` | `deepseek-v4-flash` | `Authorization: Bearer` |

Kimi、MiMo、DeepSeek 指定官方文档页面均实际返回 HTTP 200。Kimi 文档正文确认
`/v1/models`、`/v1/chat/completions` 和 Bearer；MiMo、DeepSeek 采用用户指定的
官方地址和合同。最终以实际官方接口响应为准，不凭 Key 名猜模型 ID。

## 2. 真实直连矩阵

通过 `scripts/validate_live_model_providers.py` 串行执行 DNS 和 `/models`。只有
模型列表成功后才会执行中文、严格 JSON、只读 SQL、无效模型和超时检查；本次
三家均在认证门禁失败，因此没有继续向 completion 发送请求，也没有执行 SQL。

| provider | DNS | discovered models | selected model | models | model/JSON/SQL | latency | usage | error | final |
|---|---|---:|---|---|---|---:|---|---|---|
| kimi | PASS | 0 | 无 | HTTP 401 | 0/3 | 1709 ms | 无 | `invalid_authentication_error` | FAIL |
| mimo | PASS | 0 | 无 | Bearer 401；`api-key` 401 | 0/3 | 1186 ms（最终 Header） | 无 | `401` | FAIL |
| deepseek | PASS | 0 | 无 | HTTP 401 | 0/3 | 850 ms | 无 | `invalid_request_error` | FAIL |

可复现命令在当前进程注入外置文件后执行：

```powershell
python scripts\validate_live_model_providers.py `
  --output .cache\p2a-runtime\live-provider-validation.json
```

真实退出码为 2，摘要为 `usable_provider_count=0`、
`runtime_status=PROVIDER_AUTHENTICATION_FAILED`、
`secret_values_exposed=false`。Mock 未用于 live 结果。

## 3. 结论

`MODEL_RUNTIME = NOT_PASS`

阻断码从“缺少配置”更正为真实接口证据
`PROVIDER_AUTHENTICATION_FAILED`。三家均失败符合本轮指令中允许停止 live 主线
的唯一条件。401 可能来自凭据无效、撤销、权限或账户范围，现有脱敏响应不能再
细分；在至少一家 `/models` 和三类 Smoke 成功前，不配置 SQLBot 模型，也不
启动 10/100/20，避免制造不可审计费用或伪成功。
