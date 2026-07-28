# V2-P0.0 Alpha 证据索引

> 采集日期：2026-07-28
>
> 数据边界：固定种子模拟数据、本地 Docker Compose
>
> 证据用途：Alpha 封存与 V2 执行基线，不构成生产上线证明。

## 机器证据

- `git_baseline.json`：分支、提交、标签、远程和采集时工作树。
- `docker_compose_status.json`：四个 Compose 服务的状态、健康和端口。
- `health_status.json`：API 与 Web HTTP 结果。
- `alembic_status.json`：业务 schema 当前 revision 与 head。
- `environment_versions.json`：Python、Node、npm、Docker、Git 和 GitHub CLI。
- `api/openapi.json`：运行中 API 导出的 OpenAPI。
- `api/openapi.sha256.json`：OpenAPI SHA-256 与路径数量。
- `tests/test_run_summary.json`：本轮所有测试的命令、时间、耗时、计数和退出码。
- `tests/data_quality.json`：当前 30 万会话批次的 DQ-001—DQ-020。
- `tests/alembic_cycle.json`：专用 schema 的迁移循环。
- `v2_p0_0_acceptance.json`：P0.0 机器可读总验收。

## 页面证据

`screenshots/manifest.json` 记录截图时间、1440×900 分辨率、模拟数据分类、数据库来源以及 9 张真实页面截图。当前 Alpha 没有系统/审计前端路由，因此未伪造该页面；缺失事实已写入 manifest。

## 参考输入状态

- V2 产品化优化 v1.0 Word 文件：存在于仓库根目录。
- 开发前准备与立项设计 v1.1 Word 文件：存在于仓库根目录。
- “产品功能架构与界面优化”Markdown：未在仓库或本轮附件目录找到，作为非阻塞缺失记录。
- 本机缺少 LibreOffice/soffice，Word 文件采用完整段落/表格结构化提取读取，未执行 Word 版式视觉复核。
