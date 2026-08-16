# Project2 清理前资产清单

盘点时间：2026-08-16（Asia/Shanghai）  
盘点范围：`wyg916/new-energy-biz-analytics`、其已注册 worktree、同 remote 候选副本，以及通过 Docker Compose 标签、资源名称和工作目录能够确认属于 Project2 的资源。  
真实性边界：本项目使用固定种子模拟数据和公开数据样本，不代表企业生产数据、真实客户使用或真实经营收益。

## 1. 盘点结论

```text
FEATURE_FREEZE=TRUE
PROJECT2_TOTAL_SIZE_BEFORE_BYTES=10338324557
PROJECT2_TOTAL_SIZE_BEFORE_GIB=9.628
PROJECT2_REPOSITORY_COUNT=1
PROJECT2_DUPLICATE_CLONE_COUNT=0
PROJECT2_WORKTREE_COUNT=17
PROJECT2_LOCAL_BRANCH_COUNT=24
PROJECT2_REMOTE_BRANCH_COUNT=24
PROJECT2_TAG_COUNT=4
PROJECT2_DOCKER_CONTAINER_COUNT=82
PROJECT2_DOCKER_CONTAINER_WRITABLE_BYTES=218130095
PROJECT2_DOCKER_IMAGE_COUNT_LOGICAL=53
PROJECT2_DOCKER_IMAGE_UNIQUE_BYTES_LOGICAL=8491774922
PROJECT2_DOCKER_VOLUME_COUNT=129
PROJECT2_DOCKER_VOLUME_BYTES=15430886088
PROJECT2_DOCKER_NETWORK_COUNT=13
PROJECT2_BUILD_CACHE_SIZE=UNATTRIBUTABLE_WITHOUT_CROSS_PROJECT_RISK
GLOBAL_BUILD_CACHE_BYTES_OBSERVED=26776822200
EXPLICIT_CACHE_AND_ARTIFACT_BYTES=8381146401
```

`PROJECT2_TOTAL_SIZE_BEFORE_*` 是 17 个本地 worktree/共同 Git 仓库在 NTFS 上的实测文件字节数。Docker 大小单列，避免把共享镜像层重复计入文件系统大小。BuildKit cache 没有可靠的 repository/Compose 标签，因此不能在不影响其他项目的前提下精确归属；禁止执行全局 `docker builder prune`。

## 2. Git repository 与 worktree

共同 remote：`git@github.com:wyg916/new-energy-biz-analytics.git`  
候选最终分支：`codex/integration-4.1-full`  
候选最终 HEAD：`50b6b43d60ff0c45fe3051fdd643b670a97f3b9b`  
冻结产品基线：`b6be894a7153f7ce8d31dfc65da7222bd7af1b5f`  
最终审计提交：`ce0764be9c92c7433fae54a62e247736708ea7e5`

| 类型 | 路径/名称 | Branch | HEAD | 大小（bytes） | 独有提交/未提交数据 | 是否保留 | 处理方式 |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| canonical repository（当前主工作树） | `E:\新能源企业经营分析智能平台` | `feat/p2a-sqlbot-runtime-rag-response` | `ba732d9759d1a37642708af839992609224349a4` | 2,088,583,932 | 分支独有提交 0；有 4 份独有历史文档和 1 个可重建快捷方式 | 保留仓库路径 | 文档归档到最终分支；快捷方式删除；最终切换到权威分支 |
| worktree | `E:\新能源企业经营分析智能平台-data-41` | `codex/data-open-source-41` | `75160df433bbf9273e10a87bae6a7aef29af9744` | 192,856,108 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-integration-41-core` | `codex/knowledge-baseline-41` | `44265ede1244a1c3e7b46252edab7cd387cc8e51` | 367,488,336 | 独有提交 0 | 否 | Gate 后删除 |
| final candidate worktree | `E:\新能源企业经营分析智能平台-integration-41-full` | `codex/integration-4.1-full` | `50b6b43d60ff0c45fe3051fdd643b670a97f3b9b` | 846,584,013 | 候选权威版本；工作树初始 clean | 临时保留 | 完成 Gate/文档/提交后迁回 canonical 路径 |
| worktree | `E:\新能源企业经营分析智能平台-integration-41-full-rc-verify` | detached | `b6be894a7153f7ce8d31dfc65da7222bd7af1b5f` | 171,978,581 | 无代码改动；43 个未提交的 Playwright JSON/JPG 运行产物 | 否 | 作为临时 evidence 删除 |
| worktree | `E:\新能源企业经营分析智能平台-memory-41` | `codex/memory-lifecycle-41` | `27b482df02b15c196ad1e52ced0646e69749d701` | 191,500,805 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-p2a-runtime` | `feat/p2a-runtime-closeout` | `044a0b39920b64a81e8a2771569d69770929a1c6` | 271,111,053 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-p2b-memory` | `feat/p2b-agent-memory-skills` | `7ea31fcc7c81106c5a0c169c5b06efdbc791e1d0` | 890,372,588 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-p3-governance` | `feat/p3-enterprise-governance-readiness` | `36ad33810031c52869d88de7cf35dbdaaaa10446` | 107,888,756 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-p4-rc` | `feat/p4-preproduction-rc` | `a28b92b5e83545bf8b0bb47bf2f3efa3c9d8d39d` | 110,877,794 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-p5-acceptance` | `feat/p5-production-acceptance-gates` | `cf37a43c444515f2c92530aab050410efac4b544` | 3,605,065,955 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-p5a-remediation` | `fix/p5a-production-gate-remediation` | `d8c077d7c5ee72ca8a7bf5f0dccc861b17253cea` | 61,052,620 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-p5b-gate-closure` | `codex/p5c-baseline-convergence` | `5de9ea85d0472b98a9265c29623c5ceb1b1cf1b2` | 59,536,774 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-p6-41` | `codex/p6-business-loop-41` | `45caada5c1d200c778488317241e9775c17e03f3` | 926,296,783 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-rag-41` | `codex/rag-hybrid-41` | `81f0adadc992ae8be7897c491bc243131e52e610` | 198,888,063 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-sqlbot-41` | `codex/sqlbot-open-nl2sql-41` | `8c2300532dc4c02d513df89ea8202c1aa519c6fb` | 172,644,598 | 独有提交 0 | 否 | Gate 后删除 |
| worktree | `E:\新能源企业经营分析智能平台-sqlbot-canary-41` | `codex/sqlbot-canary-41` | `feccc1e27a9f218287c231dd6da783aa189e10ef` | 75,597,798 | 独有提交 0 | 否 | Gate 后删除 |

仓库身份扫描结论：上述 17 个目录全部由同一个 Git common directory 注册；E: 根目录未发现同 remote 的第二个独立 clone。对 E:、D: 的无界递归配置扫描因耗时过长终止，没有据此删除任何对象；重复仓库判定以 Git worktree 注册表、E: 根目录 Git root 和 remote URL 三重证据为准。

## 3. Branch Reachability Audit

以候选 `50b6b43d60ff0c45fe3051fdd643b670a97f3b9b` 为 Final 比较基准：

- 24/24 本地分支均为候选最终 HEAD 的祖先，`git rev-list FINAL..BRANCH` 全部为 0，分类为 `SAFE_TO_DELETE`（最终分支除外）。
- 23/24 远端旧分支均为候选最终 HEAD 的祖先，分类为 `SAFE_TO_DELETE`。
- `origin/agent/database-integration-backup` 有 6 个拓扑独有提交；其 tip `401f61adc7e96da637bfcbec465fcaa659f1a982` 与正式历史 `1a01b9691fa607237e49fb7d89259c827e4a1cd6` 的 tree object 均为 `e9acc8092584fc354f02712be342c18a76215290`，而 `1a01b96` 已是 Final 候选祖先。因此分类为 `OBSOLETE_UNIQUE_COMMITS`、`SAFE_TO_DELETE`。
- `UNIQUE_REQUIRED_COMMIT_COUNT=0`。

本地旧分支：

```text
codex/data-open-source-41
codex/integration-4.1-core
codex/knowledge-baseline-41
codex/memory-lifecycle-41
codex/p5c-baseline-convergence
codex/p6-business-loop-41
codex/rag-hybrid-41
codex/sqlbot-canary-41
codex/sqlbot-open-nl2sql-41
develop/alpha-fast-track
feat/p1a-platform-foundation
feat/p1b-dual-engine-sales-ops
feat/p2a-runtime-closeout
feat/p2a-sqlbot-runtime-rag-response
feat/p2b-agent-memory-skills
feat/p3-enterprise-governance-readiness
feat/p4-preproduction-rc
feat/p5-production-acceptance-gates
feature/v2-productization
fix/p5a-production-gate-remediation
fix/p5b-local-gate-closure
main
refactor/chatbi-platformization-p0
```

远端旧分支在上述集合基础上以 `origin/agent/database-integration-backup` 代替本地 `main`；最终候选分支 `codex/integration-4.1-full` 不在删除集合。

## 4. Tag

清理前 tag 共 4 个：

```text
alpha-v1.0.0
data41-baseline-20260808
final-rc-v4.1.0-integration-full.1
p5c-baseline-20260808
```

它们指向的提交全部可从最终候选历史到达。建立并验证唯一 Final Tag 后，旧 tag 才允许删除。

## 5. 未提交与 ignored 资产

主工作树有 5 个未跟踪文件：

- `RAG企业知识库_知识体系与企业级开发实施指南_v1.0.docx`（1,163,103 bytes）—独有文档，归档并纳入 Final；
- `企业级Agent记忆系统开发规范与实施指南_v1.0.docx`（321,455 bytes）—独有文档，归档并纳入 Final；
- `项目二_ChatBI_NL2SQL_二次开发优化与落地实施蓝图_v1.0.docx`（1,443,226 bytes）—独有项目文档，归档并纳入 Final；
- `项目当前状态与二次开发接手报告.md`（38,384 bytes）—2026-07-29 历史审计/接手报告，归档并明确其为历史快照；
- `一键启动.bat - 快捷方式.lnk`（1,016 bytes）—仅指向同目录 `一键启动.bat`，可重建，删除。

主要 ignored/可再生资源实测合计 8,381,146,401 bytes（其中包含 34,339,011 bytes 的最终 RC source archive，后者保留）：多个 `.venv`、`backend/.venv`、`frontend/node_modules`、`dist`、`.pytest_cache`、`.cache`、`runtime`、Playwright `test-results`/`playwright-report`。最终 canonical repository 的依赖和运行缓存将在 Gate 后删除；发布 archive 按现有 release manifest 保留。

## 6. Docker 资产与删除边界

通过资源名、Compose project 标签和 worktree 配置路径确认的 Project2 资源：

| 类型 | 数量 | 实测大小 | 是否保留 | 处理方式 |
| --- | ---: | ---: | --- | --- |
| containers | 82 | writable layer 218,130,095 bytes | 否 | Final Gate 后删除 |
| images | 53（逻辑集合） | unique size 8,491,774,922 bytes | 仅保留被其他项目使用的通用基础镜像 | 删除 Project2 专用 tag/镜像；共享基础镜像不动 |
| volumes | 129 | 15,430,886,088 bytes | 否 | 固定种子模拟数据、公开样本、migration 和 seed 可重建；Final Gate 后删除 |
| networks | 13 | 不适用 | 否 | 删除 Project2 专用 network |
| BuildKit cache | 全局 922 条 | 全局 26,776,822,200 bytes | 保留 | 无项目标签，禁止跨项目 prune |

Docker volume 中没有真实客户或不可重建业务数据的证据；当前数据来源为固定种子模拟数据、公开样本和可重复 migration/seed/bootstrap。删除前仍须完成本轮 migration 与两轮一键启动 Gate。

## 7. 清理前 Gate 条件

```text
FINAL_CANDIDATE_HEAD=50b6b43d60ff0c45fe3051fdd643b670a97f3b9b
PRODUCT_BASELINE=b6be894a7153f7ce8d31dfc65da7222bd7af1b5f
FINAL_AUDIT_COMMIT=ce0764be9c92c7433fae54a62e247736708ea7e5
BASELINE_IS_ANCESTOR_OF_AUDIT=YES
AUDIT_IS_ANCESTOR_OF_FINAL_CANDIDATE=YES
UNIQUE_REQUIRED_COMMIT_COUNT=0
DELETE_STARTED=NO
FINAL_GATE=PENDING
```

只有 Backend、Frontend、Final RC Playwright、Migration 和两轮一键启动全部 PASS，且 Final branch 已推送验证后，才允许开始本地批量删除；远端旧引用清理和 Git GC 还必须等待 Final Tag 推送验证。
