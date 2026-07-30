# P0 验收关闭记录

更新时间：2026-07-30

## 1. 验收状态

- `P0_IMPLEMENTATION = PASS`
- `P0_ACCEPTANCE = CONDITIONAL`
- `P1_DEVELOPMENT = CONDITIONAL_GO`
- 正式签署 P0 PASS：**不允许**。外部凭据撤销、轮换与访问日志核查尚未取得管理员确认。

`CONDITIONAL` 不代表 PostgreSQL 验收失败。当前代码、容器 PostgreSQL、迁移、数据质量、指标对账与 Docker smoke 已取得本轮运行证据；安全事件的仓库外处置仍为硬阻塞。

## 2. 已完成项目

| 项目 | 本轮结果 | 证据边界 |
| --- | --- | --- |
| WSL / Docker 有界诊断 | PASS | 一次 `wsl --shutdown` 后 Docker Desktop 恢复；未重装、未删除卷 |
| PostgreSQL 数据质量 | 20/20 PASS | Docker PostgreSQL 16.9，模拟数据 |
| Alembic 隔离 Schema 循环 | PASS | `0006 → 0005 → 0006`，临时 Schema 已清理 |
| 15 项指标对账 | 15/15 PASS | 与已提交 P0.5 基线逐项一致 |
| Docker smoke | 6/6 PASS | health、15 指标、ChatBI、诊断、报告、区域 403 |
| 全量容器 E2E | 14/14 PASS | 首轮发现 6 项 UI 文本/定位回归，修复后全量重跑通过 |
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

python scripts/verify_alembic_schema_cycle.py --schema v2_p0_6_release_verify ...
结果：0006 → 0005 → 0006 PASS；临时 Schema 删除。

python scripts/docker_smoke.py
结果：6/6 PASS。

容器 API 指标对账脚本
结果：15 项已检查，差异 {}。

npm.cmd run e2e -- --reporter=list
首轮结果：8 passed / 6 failed；均为 UI 可见文本/定位回归，不是数据 fallback。
修复后结果：14 passed / 0 failed。
```

凭据扫描使用历史和当前跟踪文件的类型规则，只输出计数或文件名；规则覆盖私钥块、常见前缀 Token、URL 内嵌凭据和 JWT 字面量。发现的 URL 命中仅位于测试/示例/编排文件，未把它们当作生产凭据；真实暴露源仍按安全事件由外部管理员处置。

## 5. 临时 Schema 与数据量

- 临时 Schema：`v2_p0_6_release_verify`
- 清理状态：已删除
- 验收前业务与治理总行数：`510265`
- P0 迁移循环后业务与治理总行数：`510265`
- 对账差异：`0`
- 当前 Alembic head：`0006`

## 6. 安全与真实性

- 未读取、打印、复制或提交用户源文档中的具体凭据；
- 未删除 Docker 卷，未新建独立数据库，未执行不可逆迁移；
- PostgreSQL 数据均为固定随机种子的模拟数据，不是企业真实经营数据；
- 外部凭据未完成轮换，因此不得宣称 P0 已正式安全验收。

## 7. 限制与回滚

本记录不修改数据库。UI 回归修复可通过其独立提交执行 `git revert <commit>` 回滚；回滚会恢复已知 E2E 失败，不建议在没有替代修复时执行。P0 验收状态只有在外部管理员提供轮换和访问日志核查确认、且最终 E2E 与只读角色负向门禁通过后，才可改为 `PASS`。
