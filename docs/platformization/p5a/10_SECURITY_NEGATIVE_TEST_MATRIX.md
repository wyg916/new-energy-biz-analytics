# P5A 安全负向测试矩阵

## 结论边界

本矩阵只记录 P5A 已实际运行的本地验收结果。企业 IdP、托管生产 Secret Manager、外部模型 CredentialReference、企业告警接收端、真实客户数据、生产变更窗口和三方审批未获授权，未执行且不计为通过。数据为固定种子模拟数据，时间范围为 2025-01-01 至 2026-06-30；运行标识位于各证据文件。

## 已执行矩阵

| 负向边界 | 本轮实际结果 | 证据 |
|---|---|---|
| 未映射 OIDC 用户 | 服务端 callback 拒绝，未写入本地令牌 | `evidence/playwright-p4-oidc-3.xml`，3/3 中第 2 条 |
| Keycloak 禁用用户 | 无法取得授权码 | `evidence/playwright-p4-oidc-3.xml`，3/3 中第 3 条 |
| PKCE 降级 | 登录路径实际校验 `code_challenge_method=S256` 与 challenge | `evidence/playwright-p4-oidc-3.xml`、`evidence/playwright-p5-gate-1-final.xml` |
| 本地登录绕过 | P5A 主栈 `LOCAL_AUTH_ENABLED=false`；区域本地主体负向请求返回 401 | `evidence/docker-smoke.json` |
| 区域越权 | 区域负向请求未取得业务结果 | `evidence/docker-smoke.json` |
| 普通用户治理越权 | 浏览器明确显示 Forbidden 且无虚构 fallback | `evidence/playwright-original-23-final.xml` |
| Unauthorized/Forbidden 前端降级 | 清除会话或展示 Blocked，不跨域、不用 Mock 兜底 | `evidence/playwright-original-23-final.xml` |
| 空 Schema、字段发现、连接和 DQ 失败 | 前端显式呈现失败，不静默拼装业务值 | `evidence/playwright-original-23-final.xml` |
| Query Guard 与只读边界 | PostgreSQL Query Security 15/15、后端全量有效 353/353 | `evidence/postgres-fixed-memory-response-query.xml`、`evidence/p5a-postgres-regression.json` |
| SQLBot 安全聚焦 | 离线聚焦有效 46/46；SQLBot 主链禁用 | `evidence/postgres-fixed-sqlbot-46.xml`、`evidence/postgres-sqlbot-import-rerun.xml` |
| RAG 未授权与注入 | 60/60；未授权召回 0、注入影响 0 | `evidence/postgres-fixed-rag-60.xml`、`evidence/p5a-postgres-regression.json` |
| Production Gate 伪 PASS/WAIVED | 无证据的 PASSED/WAIVED、伪批准人、哈希不匹配均拒绝 | `evidence/p5a-postgres-regression.json` 及 P5 Gate 聚焦测试 |
| SQLBot Canary/生产发布/生产切流 | UI 按钮禁用，API 运行合同均为 false | `evidence/playwright-p5-gate-1-final.xml` |
| OIDC 服务端会话过期 | 第一轮两小时测试在 3600 秒 TTL 后真实返回 401，证明过期会话 fail-closed；测试客户端随后改为 TTL 前轮换，没有延长系统 TTL | `07_TWO_HOUR_CAPACITY_AND_SOAK.md`、`evidence/p5a-capacity-session-rotation-preflight.json` |
| 运行数据库凭据诊断暴露处置 | 临时 pytest 连接失败曾把运行连接参数渲染到仓库外诊断输出；未提交、未写入证据，按已暴露处理并再次轮换，最终 Vault datasource version 3，API/Keycloak/backup 恢复 | `evidence/p5a-runtime-credential-rotation.json` |
| Redis 依赖故障 | readiness 503、liveness 200，恢复后 healthy/readiness 200 | `evidence/p5a-fault-recovery.json` |
| PostgreSQL/RAG 故障 | readiness fail-closed；RAG 请求 HTTP 500、引用数 0、未伪造引用 | `evidence/p5a-fault-recovery.json` |
| Vault/CredentialReference 故障 | `VAULT_AUTH_FAILED`，明文 fallback false；解封后 KV v2/readiness 恢复 | `evidence/p5a-fault-recovery.json`、`evidence/p5a-vault-acceptance.json` |
| Keycloak/OIDC 故障 | provider 显式 `UNAVAILABLE`，readiness 503；恢复后 provider/readiness 200 | `evidence/p5a-fault-recovery.json` |
| SQLBot 不可用 | 容器数 0、runtime/canary false；Deterministic 主链仍完成且 HTTP 200 | `evidence/p5a-fault-recovery.json` |

## 尚待本轮后续证据

最终 P5A 新增行敏感信息扫描将在所有证据和文档完成后执行；在 `evidence/p5a-secret-scan.json` 生成前，不宣称“新增泄漏 0”。扫描不得读取 `.env*`，命中证据不得复制 Secret 值。

## 安全影响

没有开放自由 SQL、没有降低 Query Guard、Memory Guard 或 RAG 防线，没有允许模型决定权限，没有自动审批、生产发布、切流或 SQLBot Canary。镜像 High 在没有正式 waiver 时保持安全门禁阻断。
