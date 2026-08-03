# P5A 实施报告

## 范围与真实性边界

P5A 只修复当前独立预生产验收环境内可关闭的门禁，不进入 P6、不增加普通业务功能、不申请生产发布、不切流、不启动 SQLBot Canary。数据为 PostgreSQL 中固定种子模拟数据，范围 2025-01-01 至 2026-06-30；结果不是生产 SLA、真实客户使用或真实经营收益。

## 已完成并有证据的事项

- 冻结 P5 六个提交完整，原 P5 worktree 保持 clean；原 P5 分支已普通推送，远端 SHA 等于 `cf37a43c444515f2c92530aab050410efac4b544`，ahead/behind 0/0。
- 独立 P5A worktree/branch 已建立，没有修改 P4/P5 冻结工作树。
- Docker Desktop/WSL Linux Engine 恢复后，独立 `renewable-p5a-remediation` 栈完成 API、Web、PostgreSQL、Redis、Nginx、Keycloak、Vault、告警接收端、migration 和 backup 验证；liveness/readiness 通过，卷删除 0。
- Alembic 唯一 head `p5_0001`；隔离库完成 `base → p5_0001 → p4_0001 → p5_0001`。
- PostgreSQL 16.14 权威回归有效 353/353；Deterministic 40/40、charging 15/15、sales 12/12、DQ 20/20、Memory 40/40、Skill 40/40、RAG 60/60、Response 7/7、Query Security 15/15、SQLBot offline 46/46。
- Docker Smoke 6/6、Playwright 27/27、Vitest 3/3、TypeScript/Vite build PASS、npm audit 0。
- Trivy 0.70.0 对 11 个运行/禁用角色、8 个唯一 image ID 完成全量扫描；按角色累计 51 Critical/847 High，waiver 0，`IMAGE_SECURITY` 及相关门禁保持 BLOCKED。Keycloak 0C/15H、Vault 0C/3H、SQLBot 49C/801H；SQLBot 保持 disabled。
- 连接池预检暴露最大连接不足，已增加受控 PostgreSQL pool 配置并复用 Shadow 当前事务连接；60 秒预检 299 请求、错误/超时 0。
- 第一轮 7200 秒真实暴露 OIDC 服务端会话 TTL 处理缺陷：TTL 后预期外 401，结果判 FAIL，未生成或复用成功 JSON。修复后 180 秒边界预检完成 200 次轮换、1089 请求、错误/超时 0。
- 第二轮按原参数完成 7200 秒容量验收：实际 7229.453 秒、35,246 请求、错误率 0.059581%、超时率 0.002837%，P50/P95/P99 为 2109.546/13311.483/20744.866 ms；越权成功、异常重启、连接池耗尽均为 0。原始证据和独立验证均为 PASS。
- 临时 PostgreSQL 测试诊断曾在仓库外输出运行连接参数；未提交、未写入证据，按暴露处理并再次轮换，Vault datasource version 3 后 API/Keycloak/backup 恢复。本轮 Vault 复验又以不输出 Secret 的方式生成同值新版本并完成有效绑定、轮换和回滚，最终验收版本为 6。
- Redis/PostgreSQL/Vault/Keycloak 串行故障注入最终 PASS；readiness 均 fail-closed、liveness 保持 200，RAG 不可用时 0 伪造引用，Vault 无明文 fallback，SQLBot 0 容器且 Deterministic 主链不受影响。
- Vault P5A run `P5A-VAULT-20260803T101306Z` PASS，audit 增长 52,564 bytes；新备份 28,222,229 bytes，隔离恢复摘要和核心哈希一致，临时库已移除，原卷未删除。

## 当前仍未完成、不得提前记为通过

- 当前 API 重建镜像的补充 Trivy 扫描尚待容量结束后执行；
- P5A 新增行敏感信息扫描尚待所有文件收口后执行；
- Production Gate 本轮证据更新、最终文档提交、P5A 普通 push 和远端 0/0 尚待完成。

## 当前安全与发布结论

无论上述本地待项最终是否通过，镜像仍存在无修复或正式 waiver 的 Critical/High，15 个企业/生产/三方外部门禁也未获授权关闭。因此当前及最终可预见边界均为：

- `PRODUCTION_ACCEPTANCE_READY=false`
- `PRODUCTION_RELEASE_AUTHORIZED=false`
- `PRODUCTION_TRAFFIC_SWITCHED=false`
- `GO_NO_GO=NO_GO`
- 不允许提交生产发布授权申请。

最终完成状态、命令、测试、证据、修改文件、限制、风险和提交哈希将在所有本地可执行项实际结束后补全；本页当前不把待执行项写成 PASS。
