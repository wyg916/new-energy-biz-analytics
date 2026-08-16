# Project2 清理报告

清理日期：2026-08-16（Asia/Shanghai）  
清理边界：仅处理 remote 为 `git@github.com:wyg916/new-energy-biz-analytics.git` 的 Git 对象，或由 Project2 Compose 标签、`renewable-*` 资源名和挂载关系共同确认的 Docker 对象。

## 1. Worktree

清理前 17，清理后 1。保留 `E:\新能源企业经营分析智能平台`；删除下列 16 个已注册 worktree：

| 路径 | Branch | 原 HEAD |
| --- | --- | --- |
| `E:\新能源企业经营分析智能平台-data-41` | `codex/data-open-source-41` | `75160df433bbf9273e10a87bae6a7aef29af9744` |
| `E:\新能源企业经营分析智能平台-integration-41-core` | `codex/knowledge-baseline-41` | `44265ede1244a1c3e7b46252edab7cd387cc8e51` |
| `E:\新能源企业经营分析智能平台-integration-41-full` | `codex/integration-4.1-full` | `db7a22499d8b55f77a32bf882a7adb85e6be24e2` |
| `E:\新能源企业经营分析智能平台-integration-41-full-rc-verify` | detached | `b6be894a7153f7ce8d31dfc65da7222bd7af1b5f` |
| `E:\新能源企业经营分析智能平台-memory-41` | `codex/memory-lifecycle-41` | `27b482df02b15c196ad1e52ced0646e69749d701` |
| `E:\新能源企业经营分析智能平台-p2a-runtime` | `feat/p2a-runtime-closeout` | `044a0b39920b64a81e8a2771569d69770929a1c6` |
| `E:\新能源企业经营分析智能平台-p2b-memory` | `feat/p2b-agent-memory-skills` | `7ea31fcc7c81106c5a0c169c5b06efdbc791e1d0` |
| `E:\新能源企业经营分析智能平台-p3-governance` | `feat/p3-enterprise-governance-readiness` | `36ad33810031c52869d88de7cf35dbdaaaa10446` |
| `E:\新能源企业经营分析智能平台-p4-rc` | `feat/p4-preproduction-rc` | `a28b92b5e83545bf8b0bb47bf2f3efa3c9d8d39d` |
| `E:\新能源企业经营分析智能平台-p5-acceptance` | `feat/p5-production-acceptance-gates` | `cf37a43c444515f2c92530aab050410efac4b544` |
| `E:\新能源企业经营分析智能平台-p5a-remediation` | `fix/p5a-production-gate-remediation` | `d8c077d7c5ee72ca8a7bf5f0dccc861b17253cea` |
| `E:\新能源企业经营分析智能平台-p5b-gate-closure` | `codex/p5c-baseline-convergence` | `5de9ea85d0472b98a9265c29623c5ceb1b1cf1b2` |
| `E:\新能源企业经营分析智能平台-p6-41` | `codex/p6-business-loop-41` | `45caada5c1d200c778488317241e9775c17e03f3` |
| `E:\新能源企业经营分析智能平台-rag-41` | `codex/rag-hybrid-41` | `81f0adadc992ae8be7897c491bc243131e52e610` |
| `E:\新能源企业经营分析智能平台-sqlbot-41` | `codex/sqlbot-open-nl2sql-41` | `8c2300532dc4c02d513df89ea8202c1aa519c6fb` |
| `E:\新能源企业经营分析智能平台-sqlbot-canary-41` | `codex/sqlbot-canary-41` | `feccc1e27a9f218287c231dd6da783aa189e10ef` |

RC worktree 的 43 项未提交内容均为 Playwright JSON/JPG 可再生输出。Git 已注销全部 16 个 worktree；暂存目录 `E:\新能源企业经营分析智能平台-integration-41-full` 的 0 字节空壳因 Windows 进程目录句柄暂时保留，但它没有 `.git`、文件、分支或工作树身份，不计为 repository/worktree，也不占项目数据空间。

## 2. 本地 Branch

清理前 24，清理后 1。删除 23 个已审计旧分支：

```text
codex/data-open-source-41@75160df  codex/integration-4.1-core@0a2c776
codex/knowledge-baseline-41@44265ed  codex/memory-lifecycle-41@27b482d
codex/p5c-baseline-convergence@5de9ea8  codex/p6-business-loop-41@45caada
codex/rag-hybrid-41@81f0ada  codex/sqlbot-canary-41@feccc1e
codex/sqlbot-open-nl2sql-41@8c23005  develop/alpha-fast-track@1f6f2dc
feat/p1a-platform-foundation@d469888  feat/p1b-dual-engine-sales-ops@e34ae08
feat/p2a-runtime-closeout@044a0b3  feat/p2a-sqlbot-runtime-rag-response@ba732d9
feat/p2b-agent-memory-skills@7ea31fc  feat/p3-enterprise-governance-readiness@36ad338
feat/p4-preproduction-rc@a28b92b  feat/p5-production-acceptance-gates@cf37a43
feature/v2-productization@1a01b96  fix/p5a-production-gate-remediation@d8c077d
fix/p5b-local-gate-closure@6ee3ccc  main@2f1e573
refactor/chatbi-platformization-p0@04349de
```

## 3. 远端 Branch 与 Tag

Final Tag 推送并校验后，默认分支切换为 `codex/integration-4.1-full`。删除 23 个远端旧分支：

```text
agent/database-integration-backup@401f61a
codex/data-open-source-41@75160df  codex/integration-4.1-core@0a2c776
codex/knowledge-baseline-41@44265ed  codex/memory-lifecycle-41@27b482d
codex/p5c-baseline-convergence@5de9ea8  codex/p6-business-loop-41@45caada
codex/rag-hybrid-41@81f0ada  codex/sqlbot-canary-41@feccc1e
codex/sqlbot-open-nl2sql-41@8c23005  develop/alpha-fast-track@1f6f2dc
feat/p1a-platform-foundation@d469888  feat/p1b-dual-engine-sales-ops@e34ae08
feat/p2a-runtime-closeout@044a0b3  feat/p2a-sqlbot-runtime-rag-response@ba732d9
feat/p2b-agent-memory-skills@7ea31fc  feat/p3-enterprise-governance-readiness@36ad338
feat/p4-preproduction-rc@a28b92b  feat/p5-production-acceptance-gates@cf37a43
feature/v2-productization@afb1ee1  fix/p5a-production-gate-remediation@d8c077d
fix/p5b-local-gate-closure@f173783  refactor/chatbi-platformization-p0@04349de
```

删除旧标签 `alpha-v1.0.0`、`data41-baseline-20260808`、`final-rc-v4.1.0-integration-full.1`、`p5c-baseline-20260808`；只保留 `project2-v1-final-20260816`。

## 4. 重复仓库与未跟踪资料

- 重复独立 clone：未发现，删除数 0；所有同名候选目录原本都是同一 common Git directory 的 worktree。
- 4 份独有历史资料已归档到 `docs/archive/project2-pre-freeze/` 并纳入 Final。
- 1 个可重建 `.lnk` 快捷方式已删除。

## 5. 缓存

最终主仓库按 45 个显式路径清除至少 1,991,403,505 bytes：`.cache`、`.pytest_cache`、根及后端 `.venv`、全部 `__pycache__`、前端 `node_modules`/浏览器缓存/`dist`、Playwright 报告、临时 runtime、覆盖率/tsbuildinfo，以及 6 个临时 SQLite 数据库。旧 worktree 内的同类缓存随 worktree 一并删除。

保留 `.env`、`deploy/private/runtime` 和 `.git/codex-ssh`，原因是它们属于最终本地启动/SSH 发布配置且正文未被读取；它们未加入 Git。所有缓存可通过依赖锁文件和测试/启动脚本重建。

## 6. Docker

```text
PROJECT2_CONTAINERS_BEFORE=82
PROJECT2_CONTAINERS_AFTER=0
PROJECT2_VOLUMES_BEFORE=129
PROJECT2_VOLUMES_AFTER=0
PROJECT2_NETWORKS_BEFORE=13
PROJECT2_NETWORKS_AFTER=0
PROJECT2_CUSTOM_IMAGE_TAGS_REMOVED=51
PROJECT2_CUSTOM_IMAGE_TAGS_AFTER=0
OTHER_PROJECT_CONTAINERS_BEFORE=13
OTHER_PROJECT_CONTAINERS_AFTER=13
```

删除的容器覆盖 `renewable-integration41-full` 冷停机栈，以及 `renewable-operations-alpha`、`renewable-p2a-runtime`、`renewable-p2b-memory`、`renewable-p3-governance`、`renewable-p4-rc`、`renewable-p5a-e2e`、`renewable-p5a-remediation`、`renewable-sqlbot` 和 12 个具有 `renewable-*` 名称的无 Compose 标签历史容器。

删除的卷来自 `renewable-data41*`、`renewable-final-rc-clean*`、`renewable-integration41-*`、`renewable-operations-alpha*`、`renewable-p2a-*`、`renewable-p2b-*`、`renewable-p3-*`、`renewable-p4-*`、`renewable-p5*`、`renewable-p6-*`、`renewable-rc-*`、`renewable-sqlbot*`，以及仅被上述项目二容器挂载的匿名卷；共享卷=0。它们只含 migration、seed、固定种子模拟数据、公开样本、索引、测试证据和可重建缓存。

删除 51 个专用镜像标签，覆盖 `renewable-*` 应用镜像、`dataease/sqlbot:v1.8.0` 和 `registry.cn-qingdao.aliyuncs.com/dataease/sqlbot:v1.10.0`，另删除 3 个仅由项目二容器引用的悬空镜像；通用基础镜像保留。删除 13 个 Project2 专用网络；共享网络=0。

全局 BuildKit cache 在清理前为 26.86 GB、930 条，缺少项目归属标签，未执行跨项目 prune：`BUILD_CACHE_CLEANUP=SKIPPED_UNATTRIBUTABLE_CROSS_PROJECT`。

## 7. 空间

以下为同一逻辑口径的实际盘点字节数，BuildKit 全局缓存不计入：清理前 17 个 worktree/common Git 实测 10,338,324,557 bytes，Project2 容器 writable layer 218,130,095 bytes，项目镜像逻辑集合 8,491,774,922 bytes，Project2 卷 15,430,886,088 bytes；清理后只剩 canonical repository 实测约 160.7 MB，Project2 专属 Docker 对象为 0。

```text
DISK_USAGE_BEFORE_GB=34.48
DISK_USAGE_AFTER_GB=0.16
DISK_SPACE_FREED_GB=34.32
```

镜像值使用清理前 Docker 归属盘点的逻辑集合，避免把全局 BuildKit cache 或其他项目资源算作 Project2。Docker 全局 `system df` 同期从 images 20.60 GB / containers 217.9 MB / volumes 30.18 GB 降至 images 11.01 GB / containers 0 B / volumes 14.69 GB；宿主 Docker VHD 未承诺立即压缩。

## 8. 保留对象

```text
CANONICAL_REPOSITORY=E:\新能源企业经营分析智能平台
CANONICAL_BRANCH=codex/integration-4.1-full
CANONICAL_HEAD=project2-v1-final-20260816^{}
FINAL_TAG=project2-v1-final-20260816
REPOSITORY_COUNT=1
WORKTREE_COUNT=1
LOCAL_BRANCH_COUNT=1
REMOTE_BRANCH_COUNT=1
TAG_COUNT=1
WORKTREE_CLEAN=YES
OTHER_PROJECTS_TOUCHED=0
```

