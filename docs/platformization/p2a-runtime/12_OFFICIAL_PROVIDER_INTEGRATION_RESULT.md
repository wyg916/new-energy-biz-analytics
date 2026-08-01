# P2A 官方 Provider 集成结果

更新时间：2026-08-01

## 1. 结论

- `Kimi`：官方直连三项全部通过，实际模型 `kimi-k2.6`。
- `DeepSeek`：官方直连三项全部通过，实际模型 `deepseek-v4-flash`。
- `MiMo`：`api-key` 鉴权成功，文本与 JSON 通过；SQL 输出在 256 completion token 上限处截断，因此三项合同总体未通过。
- SQLBot 主模型：`DeepSeek / deepseek-v4-flash`；第一备用为 `Kimi / kimi-k2.6`。
- Secret 来源仅为仓库外运行文件；本页和运行证据均未记录完整 Key。

## 2. 凭据解析

文件以 `UTF-8-sig` 解析，并执行 BOM、首尾空白、单层匹配引号、重复变量、空值、内部换行与不可见字符检查。

| 变量 | 存在 | 原始/清理长度 | 前缀 | SHA-256 前 12 位 | 请求/文件一致 | 不可见字符 |
|---|---:|---:|---|---|---:|---:|
| `KIMI_API_KEY` | 是 | 51/51 | `sk-` | `8de8aeb2b724` | 是 | 否 |
| `MIMO_API_KEY` | 是 | 51/51 | `sk-` | `a3176a0ce95f` | 是 | 否 |
| `DEEPSEEK_API_KEY` | 是 | 35/35 | `sk-` | `e1bf1d4615e9` | 是 | 否 |

重复变量 0、空值 0、内部换行 0；完整 Key 输出数 0。

## 3. 官方接口结果

| Provider | 模型发现/鉴权 | 实际模型 | 文本 | JSON | SQL | Token 合计 | 最终状态 |
|---|---|---|---:|---:|---:|---:|---|
| Kimi | `/v1/models` 200，2 个模型 | `kimi-k2.6` | 200 / 3271 ms / 72 | 200 / 4743 ms / 120 | 200 / 14237 ms / 450 | 642 | PASS |
| DeepSeek | `/models` 200，2 个模型 | `deepseek-v4-flash` | 200 / 1431 ms / 103 | 200 / 1986 ms / 212 | 200 / 2226 ms / 222 | 537 | PASS |
| MiMo | `api-key` chat 200；成功后未再尝试 Bearer | `mimo-v2.5-pro` | 200 / 2439 ms / 49 | 200 / 2040 ms / 53 | 200 / 8214 ms / 354，格式失败 | 456 | FAIL |

Kimi 发现模型为 `kimi-k2.7-code`、`kimi-k2.6`；DeepSeek 发现模型为 `deepseek-v4-flash`、`deepseek-v4-pro`。MiMo 按官方约定直接调用 chat/completions，不以 `/models` 作为认证门禁。

## 4. 分层诊断

1. 官方一次性直连：DeepSeek 200。
2. Model Gateway：真实 DeepSeek transport/auth 成功；严格“只回复 OK”内容断言不完全匹配。
3. API 容器：相同 Provider、域名、模型和指纹的真实请求成功。
4. SQLBot：真实请求可达 Provider，但平台最初把字符串组织 ID `org-alpha` 发送给 SQLBot 的整数 `oid` 字段。
5. 修复：Datasource 已绑定时不再发送 `oid`；SQLBot 之后能产生真实 SQL，首个差异从认证层收敛到 SQLBot 输出质量与平台 Guard 契约。

## 5. 主模型选择依据

DeepSeek 与 Kimi 均通过文本、JSON、SQL 三项。DeepSeek 三项延迟显著更低，SQL 格式遵循稳定，因此选为 SQLBot 主模型；Kimi 为第一备用。MiMo 鉴权可用，但本次 SQL 合同未通过，且 SQLBot v1.8.0 的 OpenAI 兼容配置不能表达其已验证的 `api-key` Header，暂不进入 SQLBot 配置。

## 6. 证据与真实性边界

- 本地忽略证据：`.cache/p2a-runtime/official-provider-validation.json`。
- 数据性质：模拟数据；Provider 调用是真实开发测试调用。
- 未连接企业生产数据库，未声明生产上线或真实经营收益。
- 运行证据不保存模型完整 prose、完整 Key 或会话 Token。
