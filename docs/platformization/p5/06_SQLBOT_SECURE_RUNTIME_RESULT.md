# P5 SQLBot 外部安全复评

状态：`CONDITIONAL`；运行模式保持 `SHADOW`，`SQLBOT_ENGINE_ENABLED=false`，`SQLBOT_RUNTIME_VERIFIED=false`，`SQLBOT_CANARY_ELIGIBLE=false`。

本轮没有收到经授权外部模型 CredentialReference，因此按强制顺序没有执行 Smoke 10、Golden 30、Shadow 20，也没有发起任何外部模型请求。

| 项目 | 实际值 |
|---|---:|
| 请求数 | 0 |
| 成功数 | 0 |
| SQL 生成数 | 0 |
| Structured Output 解析率 | N/A |
| Guard 通过数/率 | 0 / N/A |
| 字段幻觉数 | N/A |
| 表幻觉数 | N/A |
| 安全违规数 | 0（无请求，不代表模型验证通过） |
| 超时/Provider 错误 | 0 / 0 |
| P50/P95/P99 | N/A |
| Token/费用 | 0 / 0 |

不得将 0 请求解释为达到 SQL 生成率 80% 或 Guard 通过率 70%。完整 100 Golden 未运行，Canary 未开启；DeterministicEngine 没有受影响。SQLBot 镜像 P5 实际扫描也因 Docker/远端拉取阻断尚未完成。
