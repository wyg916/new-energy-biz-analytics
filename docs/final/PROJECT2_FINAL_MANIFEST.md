# Project2 最终冻结清单

冻结日期：2026-08-16（Asia/Shanghai）

```text
PROJECT=Project2
PRODUCT=ChatBI / NL2SQL
FINAL_BRANCH=codex/integration-4.1-full
FINAL_HEAD=project2-v1-final-20260816^{}
PRODUCT_BASELINE=b6be894a7153f7ce8d31dfc65da7222bd7af1b5f
FINAL_AUDIT_COMMIT=ce0764be9c92c7433fae54a62e247736708ea7e5
PRE_MANIFEST_CLOSURE_HEAD=db7a22499d8b55f77a32bf882a7adb85e6be24e2
FINAL_TAG=project2-v1-final-20260816
REMOTE=git@github.com:wyg916/new-energy-biz-analytics.git
CANONICAL_REPOSITORY=E:\新能源企业经营分析智能平台
WORKTREE_CLEAN=YES
TEST_STATUS=PASS
FINAL_CLOSURE=PASS
DATA_CLASSIFICATION=SIMULATED_AND_OPEN_SOURCE_DERIVED
```

`FINAL_HEAD` 使用不可变 Final Tag 的 peeled Git 引用表示，因为 Git commit 不能在自身内容中包含自己的对象 SHA。权威解析命令为：

```bash
git rev-parse project2-v1-final-20260816^{}
```

## 冻结边界

- `b6be894a...` 是冻结产品基线；`ce0764be...` 是其后的最终审计提交。
- 其后 `7e379...`、`81cdb...`、`50b6...` 是批准归档、一键启动浏览器行为和本地 OIDC 安全登录收口。
- `db7a224...` 归档冻结前独有资料，并修复最终回归容器漏装本地登录契约文件的问题。
- 本清单及同目录最终报告随 Final Tag 一并冻结。
- 本项目未声明企业生产上线、真实客户使用或真实经营收益；页面与数据链路使用固定种子模拟数据及公开来源衍生数据。

## 权威入口

- 启动：`一键启动.bat` 或 `scripts/release/start-project.ps1`
- 主站：`https://p5b.localhost:8446`
- 健康检查：`https://p5b.localhost:8446/api/v1/health/ready`
- 完整验收：`scripts/Run-Integration41FullAcceptance.ps1`
- 最终报告：`docs/final/PROJECT2_FINAL_CLOSURE_REPORT.md`
- 清理报告：`docs/final/PROJECT2_CLEANUP_REPORT.md`

