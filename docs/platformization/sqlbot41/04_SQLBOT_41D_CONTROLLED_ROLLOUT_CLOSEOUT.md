# SQLBot 4.1D 受控灰度与 Scoped Stable 收口

## 结论

- 状态：`PASS`
- 分支：`codex/sqlbot-canary-41`
- 基线：`8c2300532dc4c02d513df89ea8202c1aa519c6fb`
- 集成结论：允许进入 Full Integration；本结论只表示本工作包的受控验收门禁通过，不表示已执行 Full Integration、已上线生产、已有真实客户使用或产生真实经营收益。
- 数据边界：固定种子模拟数据与开源派生 DATA-4.1 验收数据；未把验收数据描述为企业生产数据。

## 严格放量顺序

| 阶段 | 请求与选中 | 关键指标 | 结论 |
| --- | ---: | --- | --- |
| Shadow（冻结证据） | 50 | 冻结门禁通过 | PASS |
| Canary 5% | 100 / 5 | Runtime、Guard、执行、语义、结果一致性均 100%；P95 5595ms；fallback 0 | PASS |
| Canary 20% | 200 / 40 | Runtime、Guard、执行、语义、结果一致性均 100%；P95 7307ms；fallback 2.5%，最终回答成功率 100% | PASS |
| Canary 20% 稳定窗口 | 1800.003 秒 / 120 | Runtime 健康率 98.33%；P95 8762ms；fallback 4.17%；5xx 与 timeout 为 0 | PASS |
| Scoped Stable | 40 / 40 | SQLBot 调用 20；Runtime、Guard、执行、语义、结果一致性均 100%；P95 7061ms；fallback 0 | PASS |

稳定窗口额外保留 82 个 SQLBot Runtime 资源样本：内存从 15.89% 到 15.92%，峰值 15.93%；Docker 多核口径 CPU 瞬时峰值为 370.88%，资源门禁为 `PASS`。CPU 旁路采样是在发现原包装器缺少 CPU 字段后启动，未覆盖完整 30 分钟窗口，这是保留限制。首个正式窗口因 P95 超过门禁且一次运行时健康探测超时而失败；第二个窗口在 735.624 秒时被外部中断。失败/中断证据均保留，未被当作成功窗口。

## 路由与能力边界

受控开放 NL2SQL 只有同时满足 tenant、workspace、user、scenario 四层 allowlist，且请求属于已注册 Schema Catalog 的低/中风险探索查询时，才可进入 SQLBot。以下请求固定走 Deterministic Engine 或 fail-closed：

- 核心财务指标、PII、系统治理与未发布 Schema；
- 未知 Join、不完整权限上下文、未知场景；
- 超高成本查询、Query Guard 高风险或只读边界不满足；
- 紧急开关 `SQLBOT_ENGINE_ENABLED=false` 或 `QUERY_ENGINE_MODE=DETERMINISTIC_ONLY` 生效时的全部新请求。

SQLBot 生成结果必须依次通过 Parser/AST、Schema validation、Join validation、Permission/PII validation、成本/超时/行数限制、Query Guard、只读执行、Result validation 与 Answer Guard。没有自由 SQL 管理入口，也不存在绕过 Query Guard、权限过滤或只读角色的执行路径。

## 自动回退与安全门禁

- 故障注入：10/10，自动回退成功率 100%。
- 紧急回退：新请求确定性路由率 100%。
- Canary/Scoped Stable 权限、PII、只读与 unguarded SQL 违规：0。
- Secret scan：`PASS`，新增泄漏发现 0。
- 当前只读真实查询：`PASS`；只读包装器负向：`PASS`。
- SQLBot 连接复用在应用 lifespan 结束时显式关闭，避免测试与长期运行累积客户端资源。

## 回归与验收

| 门禁 | 结果 |
| --- | ---: |
| 当前 PostgreSQL 全量 | 478/478 PASS，0 failure、0 error、0 skipped |
| 冻结 PostgreSQL | 453/453 PASS |
| DATA-4.1 PostgreSQL | 5/5 PASS |
| SQLBot 4.1D Focused | 158/158 PASS |
| NL2SQL Golden | 100/100 PASS |
| 冻结 Smoke | 20/20 PASS |
| 冻结 Shadow | 50 条，PASS |

首轮当前 PostgreSQL 回归为 305 tests、2 failures、1 collection error。根因分别是 legacy Shadow 警告合同未保留，以及新增 Canary 测试在隔离容器中无法导入当前 `scripts` 源码。修复后先执行定向 corrective 10/10，再执行四个隔离 tmpfs PostgreSQL 批次，最终收集并通过 478 项；原失败证据仍保留。

## 启动、迁移与例外修改

- 一键启动与冷启动均为 `PASS`，SQLBot Runtime 为 CE v1.10.0；默认启动模式仍为 Shadow，不是全局 Stable。
- 当前 Alembic 单头为 `sqlbot_41c2`；SQLBot 4.1D 没有新增业务 Schema 迁移。
- `backend/app/main.py` 仅增加 SQLBot 复用客户端的 lifespan 清理。
- 根 `一键启动.bat` 仅在既有项目启动后串联 SQLBot 4.1D 受控启动。
- `scripts/release/start-project.ps1` 增加迁移兼容性检查和基于已核实名命卷的容器 handoff；命名数据卷不删除。
- 未修改 `frontend/src`、最终 Compose、公共依赖或公共 API schema。

## 数据库与安全影响

- 无业务 Schema 迁移，无业务数据写入或回滚要求。
- 验收过程中只在隔离 tmpfs PostgreSQL 数据库执行全量回归；当前 DATA-4.1 数据库执行只读查询，并追加既有验收审计记录。
- 凭据继续通过 Vault/AppRole 与只读运行卷引用；证据不持久化或打印秘密值。
- Docker 重启后曾按仓库既有恢复脚本对已初始化 Vault 执行 unseal，没有重新初始化或输出密钥。

## 证据与回滚

最终机器清单为 `evidence/sqlbot41d-final-acceptance-summary.json`，其 `status=PASS`、`full_integration_allowed=true`，并包含全部必需工件 SHA-256。Canary 路由事件、稳定窗口、故障注入、紧急回退、启动、回归、只读和 secret scan 的原始证据位于同一 evidence 目录。

即时回滚：设置 `SQLBOT_ENGINE_ENABLED=false` 或 `QUERY_ENGINE_MODE=DETERMINISTIC_ONLY`。代码回滚：对本工作包提交执行 `git revert`。本轮没有业务迁移或业务数据变更，因此不需要数据库回滚。
