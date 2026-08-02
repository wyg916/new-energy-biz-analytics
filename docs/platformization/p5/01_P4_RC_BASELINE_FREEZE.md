# P4 RC 基线冻结核验

核验时间：2026-08-02，Asia/Shanghai。以下是接管时实际执行结果，不是目标描述。

## Git 与工作树

| 项目 | 实际结果 |
| --- | --- |
| 冻结 worktree | `E:\新能源企业经营分析智能平台-p4-rc` |
| 分支 | `feat/p4-preproduction-rc` |
| HEAD | `a28b92b5e83545bf8b0bb47bf2f3efa3c9d8d39d` |
| 远端 | `origin/feat/p4-preproduction-rc` |
| ahead/behind | `0/0` |
| Git 工作区 | clean |
| P5 worktree | `E:\新能源企业经营分析智能平台-p5-acceptance` |
| P5 分支 | `feat/p5-production-acceptance-gates` |
| P5 起始提交 | `a28b92b5e83545bf8b0bb47bf2f3efa3c9d8d39d` |

原始工作区位于 `E:\新能源企业经营分析智能平台`，分支为 `feat/p2a-sqlbot-runtime-rag-response`，存在用户自己的 ahead 提交和未跟踪文件；P5 不在该工作区实施，也不修改这些内容。

## Migration 核验

- 已在 `git fetch origin --prune` 后检查远端 P4 分支全部 migration 文件。
- 远端版本链包含 `0001` 至 `0015`、`p2b_0001`、`p3_merge_0001`、`p3_0001` 和 `p4_0001`。
- `alembic heads` 实际输出为 `p4_0001 (head)`，唯一 head。
- `alembic history` 显示 `p3_0001 -> p4_0001`；P5 新 revision 可使用 `p5_0001`，但不得改写任何历史 revision。
- 接管时 Docker Engine 不可用，无法从 P4 PostgreSQL 容器取得运行数据库 current；仓库默认 SQLite 未初始化，不能用它冒充 P4 运行 current。

## RC Manifest 完整性

| 文件 | 实际 SHA-256 | 固化值匹配 |
| --- | --- | --- |
| `p4_release_candidate_manifest.json` | `a2937a6a7766a072304460ab40b1e12c18f4f040cb04dfb8c62f9d9525fdb186` | 是 |
| `p4_security_scan_summary.json` | `2bfb04a2e78d463d4388fde4d89154db52e5d3cd32666e5e23d0f08c3f1053aa` | 是 |
| `p4_dependency_inventory.json` | `759433909216d5f02d0dedd9f1b0087e72809fed8e68addb895655fb53ba0283` | 是 |
| `12_TEST_AND_ACCEPTANCE_MATRIX.md` | `128ca8cd22cb79f9e88322b5253d518630cbec93386ba2a38c30ceed53074dc8` | 是 |
| `deploy/preproduction/compose.yaml` | `7eac848fdb1e6a57257205edf27e1f448ecd09c53419b9ddf1c5f72483ba9da8` | 是 |

唯一 RC 仍为 `4.0.0-rc.1` / `REL-8e18dac8-41d9-4d30-945e-8478637fb79e`，状态 `ACTIVE` 仅代表预生产候选；`production_release_authorized=false`。

## 备份与证据核验

仓库内冻结证据 `p4_backup_restore.json` 记录：dump SHA-256 为 `e5ccf0509d6bcd327fdc38a4796c4a87473ce0549d289dd0b50f850fd5ef5871`，恢复摘要相等、业务数据哈希 `a55192ad4704ff27870f2ba4da142051` 相等、临时恢复库已移除、源卷未删除、备份中未保存 Secret 值，状态 PASS。接管核验确认该证据文件与 RC Manifest 引用保持一致；Docker Engine 不可用时没有伪造新的恢复执行。

## 接管时运行态限制

`docker compose ps --all` 和后续 `docker version` 实际失败。Docker Desktop Service 为 Running，但 Linux Engine 报 `Wsl/Service/CreateInstance/HCS_E_CONNECTION_TIMEOUT`，Docker API 返回 no connected NIC/Internal Server Error。因此接管时以下项目尚未获得新的 P5 实测证据：容器健康、运行数据库 current、全镜像复扫、容量/耐久、故障和备份恢复回归。它们在获得实际运行证据前保持 OPEN 或 BLOCKED，不沿用 P4 历史结果冒充 P5 PASS。

## 基线结论

P4 Git、文档、Manifest 和冻结哈希与交接一致，可以进入 `P5_PRODUCTION_ACCEPTANCE_GATE_CLOSURE`；这不构成生产部署、切流或正式生产可用授权。
