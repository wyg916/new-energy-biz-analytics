# P5A 两小时容量与耐久验收

## 边界与负载

- 环境：独立 `renewable-p5a-remediation` 预生产验收栈，不是生产环境，不形成生产 SLA。
- 数据：PostgreSQL 中固定种子模拟数据，2025-01-01 至 2026-06-30。
- 固定参数：100 个逻辑用户、并发 20、正式持续 7200 秒。
- 请求覆盖：5 类经营驾驶舱查询、4 类受控助手查询、身份/策略、负向权限、Memory、Skill、RAG keyword-only、Production Gate 与 OIDC 状态；治理 snapshot 实际读取 scoped CredentialReference、Release Registry 和最近 Audit events，不是仅检查健康状态。
- 正向请求使用服务端 OIDC 会话；负向请求使用已有 LOCAL 区域主体签发的凭据并确认预生产 OIDC 边界拒绝，未创建伪造 OIDC 映射。
- 监控：API、PostgreSQL、Redis、Keycloak、Vault 的 CPU、RSS、PID、RestartCount；数据库大小/连接/治理审计；Redis 客户端；连接池耗尽日志。

## 预检与真实修复

预检真实暴露并修复了以下问题，未降低并发、持续时间、错误阈值或 Query Guard：

1. 容器内生成器不能访问宿主 `p5a.localhost:8445`：改为连接 Compose `https://proxy`，同时保留公开 `Host: p5a.localhost`。
2. 连接地址与 HTTP Host 未分离导致 400：增加显式 `--request-host`。
3. PostgreSQL 默认连接池最大 15，小于并发 20：增加可校验的 `DATABASE_POOL_SIZE=20`、`DATABASE_MAX_OVERFLOW=10`；Shadow 审计表检查复用当前 Session 连接，不再额外 checkout。
4. 越权样例误用具有管理员角色的 analyst：改用已有 LOCAL regional 主体，预生产边界稳定返回 401。
5. 趋势请求缺少 metric、跨场景复用 conversation、响应档案拼写错误：按冻结固定评测合同修正样例和会话键；未修改业务解析器。
6. 工作负载启动失败时可能读取旧容器证据：每次使用唯一 `/tmp` 输出路径，文件不存在即安全失败。
7. 第一轮 7200 秒在服务端 OIDC 会话 TTL（3600 秒）之后出现大量预期外 401：JWT 虽每 300 秒刷新，但复用了已过期的服务端会话。修复为在 TTL 前 120 秒轮换 analyst 与负向权限会话，不延长系统会话 TTL、不放宽鉴权。
8. 第一轮收尾撤销已自然过期会话时抛出异常，导致内层没有写出 FAIL JSON：修复为将自然过期视为已清理，捕获 worker/cleanup 错误并强制纳入 FAIL 判定；外层若仍收不到本轮文件，也会写出不含原始输出内容的 host failure diagnostic。

最终 60 秒预检：`run_id=P5-CAP-20260802T153000Z`，实际 73.14 秒，299 请求，p50 2467.396 ms、p95 11184.255 ms、p99 17307.702 ms，错误率 0、超时率 0、越权成功 0、连接池耗尽 0、异常重启 0、治理审计增长 74，状态 `PASS`。证据为 `evidence/p5a-capacity-preflight.json`。

会话轮换边界预检使用仅作用于测试子进程的 180 秒会话 TTL，运行 180 秒、100 个逻辑用户、并发 20；实际完成 200 次会话轮换、1089 请求，错误率 0、超时率 0、worker/sample error 0、越权成功 0，状态 `PASS`。`run_id=P5-CAP-20260802T173414Z`，证据为 `evidence/p5a-capacity-session-rotation-preflight.json`。该覆盖只缩短预检子进程的 TTL，没有修改运行栈的 3600 秒配置。

## 第一轮正式运行失败记录

- 启动：2026-08-02 23:31:24 +08:00；收尾：2026-08-03 01:31 左右 +08:00。
- 基础设施取证：API、PostgreSQL、Redis、Keycloak、Vault 均为 `healthy`，`OOMKilled=false`、`RestartCount=0`。
- 失败表现：API 日志在会话 TTL 后出现大量预期外 401；外层以 `workload failed before writing current-run evidence` 安全失败，没有生成或复用成功 JSON。
- 判定：该轮为 `FAIL`，不得计入两小时容量通过；失败根因为测试客户端会话生命周期处理缺陷，不是系统鉴权阈值问题。
- 处置：实施上述会话轮换与失败证据修复，完成 180 秒边界预检后，按原参数重新执行完整 7200 秒。第一轮事实不会被第二轮成功结果覆盖。

## 7200 秒正式运行

第二轮按原参数完成并通过：100 个逻辑用户、并发 20、配置时长 7200 秒，宿主实际监控 7229.453 秒。运行标识为 `P5-CAP-20260802T173756Z`，共完成 35,246 个请求，其中成功 35,225、错误 21、超时 1；错误率 0.059581%，超时率 0.002837%。P50/P95/P99 分别为 2109.546/13311.483/20744.866 ms。

安全与稳定性不变量均满足：越权成功 0、异常重启 0、连接池耗尽 0、SQLBot 不可用影响确定性主答案 0、worker/resource sample error 0；OIDC 会话按原 3600 秒 TTL 在到期前完成 200 次轮换。治理审计从 3306 增长到 10022，新增 6716 条且未检测到丢失；PostgreSQL 数据库增长 82,788,352 字节。

宿主资源观测覆盖 API、PostgreSQL、Redis、Keycloak 和 Vault。API/PostgreSQL RSS 分别增长 89,128,960/124,465,971 字节，Keycloak/Redis/Vault 分别增长 1,258,291/626,000/335,545 字节；581 个宿主样本未检测到持续无法解释的增长。该结果只代表当前单机隔离预生产环境，不形成正式生产容量或 SLA 承诺。

原始证据 `evidence/p5a-capacity-soak.json` 状态为 PASS，SHA-256 为 `44977aac406a3e7c2630ab90f640dded3e1811b0ea50a0f89a1b8ec215a4db44`。独立验证器逐项复核持续时间、请求记账、源文件哈希、会话轮换、权限、审计、资源、重启和连接池不变量，失败检查 0；`evidence/p5a-capacity-verification.json` 状态为 PASS，SHA-256 为 `2f63f706337d09849c651425ebc5445d36d7dacbd14a1d03f357baff778762e3`。

因此本地 `CAPACITY_SOAK` 具备 PASSED 证据。`PRODUCTION_CAPACITY` 仍依赖生产同构规格与正式 SLA，保持外部 `OPEN/CONDITIONAL`；本地结果不授权生产发布或切流。
