# P0 验收关闭记录

更新时间：2026-07-30

## 1. 验收状态

- `P0_IMPLEMENTATION = PASS`
- `P0_ACCEPTANCE = CONDITIONAL`
- `P1_DEVELOPMENT = CONDITIONAL_GO`
- 正式签署 P0 PASS：**不允许**。外部凭据撤销、轮换与访问日志核查尚未取得管理员确认。

`CONDITIONAL` 不代表 PostgreSQL 验收失败。当前代码、容器 PostgreSQL、完整迁移循环、数据质量、指标对账、只读角色、Docker smoke 与 E2E 均取得本轮运行证据；安全事件的仓库外处置仍是唯一未关闭的正式签署阻塞。

## 2. 已完成项目

| 项目 | 本轮结果 | 证据边界 |
| --- | --- | --- |
| WSL / Docker 有界诊断 | PASS | 一次 `wsl --shutdown` 后 Docker Desktop 恢复；未重装、未删除卷 |
| PostgreSQL 数据质量 | 20/20 PASS | Docker PostgreSQL 16.9，模拟数据 |
| Alembic 隔离 Schema 循环 | PASS | `base → 0009 → base → 0009`，临时 Schema 已清理 |
| 15 项指标对账 | 15/15 PASS | 与已提交 P0.5 基线逐项一致 |
| Docker smoke | 6/6 PASS | health、15 指标、ChatBI、诊断、报告、区域 403 |
| 全量容器 E2E | 17/17 PASS | 使用仓库受控 Chromium；含 P1A 平台失败态与回滚 |
| 独立只读角色负向验证 | PASS | SELECT 语义视图允许；基础表、写入、DDL、敏感系统对象拒绝；超时生效；临时角色/Schema 已清理 |
| 凭据痕迹扫描 | 已执行 | 只检查规则命中类别与文件名，不读取或输出凭据值 |

## 3. 外部待办

状态：`EXTERNAL_PENDING`

仓库内没有权限替代外部管理员执行下列操作：

1. 在原数据库/API 系统撤销疑似暴露凭据；
2. 生成并部署新凭据；
3. 确认旧凭据不可用；
4. 核查暴露窗口内访问日志；
5. 由外部负责人提供不含秘密值的完成确认。

详见 `16_REDACTED_CREDENTIAL_ROTATION_CHECKLIST.md`。

## 4. 实际命令与结果

```text
docker compose up -d
结果：api/db/redis/web 均启动；api、db、redis healthy。

docker compose exec -T api python -m app.data.quality
结果：20/20 PASS。

python scripts/verify_alembic_schema_cycle.py
结果：base → 0009 → base → 0009 PASS；临时 Schema 删除。

docker compose run ... python scripts/docker_smoke.py
结果：6/6 PASS。

docker compose run ... python scripts/verify_p0_5_metric_reconciliation.py
结果：15 项已检查，差异 {}。

python scripts/verify_chatbi_readonly_role.py
结果：12 项只读边界检查全部 PASS；临时角色和 Schema 删除。

PLAYWRIGHT_EXECUTABLE_PATH=<仓库受控 Chromium> npx.cmd playwright test
结果：17 passed / 0 failed。
```

凭据扫描使用历史和当前跟踪文件的类型规则，只输出计数或文件名；规则覆盖私钥块、常见前缀 Token、URL 内嵌凭据和 JWT 字面量。发现的 URL 命中仅位于测试/示例/编排文件，未把它们当作生产凭据；真实暴露源仍按安全事件由外部管理员处置。

## 5. 临时 Schema 与数据量

- 临时 Schema：`v2_p0_6_release_verify`
- 清理状态：已删除
- P1A 迁移前业务与治理总行数：`510639`
- P1A 场景/语义/版本/审计记录落库后总行数：`510752`
- 增量：`113`，来自平台版本、语义、发布、激活、回滚和本轮审计记录
- 核心事实数据：`300000` 充电会话，DQ 业务计数与迁移前一致
- 当前 Alembic head：`0009`

## 6. 安全与真实性

- 未读取、打印、复制或提交用户源文档中的具体凭据；
- 未删除 Docker 卷，未新建独立数据库，未执行不可逆迁移；
- PostgreSQL 数据均为固定随机种子的模拟数据，不是企业真实经营数据；
- 外部凭据未完成轮换，因此不得宣称 P0 已正式安全验收。

## 7. 限制与回滚

P1A 数据结构迁移均有 Alembic downgrade，版本激活有 `RollbackService` 和 `rollback_record`；代码工作包可按独立提交逆序 `git revert`。P0 的运行门禁已满足，状态只有在外部管理员提供旧凭据撤销、轮换和访问日志核查确认后，才可从 `CONDITIONAL` 改为 `PASS`。
