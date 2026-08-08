# DATA-4.1 开源真实数据基线与业务数据链路收口实施报告

## 1. 结论

本地工程与运行验收结论：`PASS`。

`DATASET_IMPORT=PASS`、`DATA_QUALITY=PASS`、`DATA_LINEAGE=PASS`、`DB_API_UI=PASS`、`DETERMINISTIC_CHATBI=PASS`、`ONE_CLICK_START=PASS`。

本结论表示 DATA-4.1 的公开数据样本基线已实现、测试和验证，不表示生产发布获批、生产流量切换、真实企业经营收益或真实客户上线。SQLBot 在本阶段仍禁用。

## 2. 目标、范围与非目标

- 目标：把可验证公开数据按 `raw -> staging -> core -> semantic -> API -> UI/ChatBI` 落入现有模块化单体，并保持 15 项核心指标及治理链路。
- 范围：ACN-Data charging_ops、UCI Online Retail sales_ops、血缘/质量/版本、受认证 API、全局数据真相、一键启动与验收证据。
- 非目标：不开发正式 SQLBot，不接生产客户数据，不创建自由 SQL 入口，不伪造 ACN 未提供的设备状态，不自动邮件/工单/跨系统执行。

## 3. 完成内容与修改文件

- 数据与血缘：`data/open_source/`、`backend/app/data/open_source.py`、`backend/app/data/truth.py`、`backend/app/models/open_data.py`。
- 数据库：可逆迁移 `backend/alembic/versions/data_0001_open_source_lineage.py`，新增 source/snapshot/ingestion/quality/raw/staging 表。
- API 与业务链路：更新 Dashboard、Revenue、Diagnostics、Reports、Data Integration、ChatBI、Assistant/Response Composer；新增 `backend/app/api/open_data.py`。
- 前端：统一全局状态显示“公开数据样本”、来源、时间与 analysis run_id；无前端业务造数或静态 fallback。
- 启动：原位更新 `scripts/release/start-project.ps1`；根目录 `一键启动.bat` 继续调用该脚本，没有新增阶段启动文件。
- 文档与目录：`docs/data/OPEN_SOURCE_DATA_MAPPING.md`、映射 JSON、Schema Catalog v2（13 表/141 字段/19 关系）。
- 测试与证据：`backend/tests/test_data41_open_source.py`、`frontend/e2e/data41-open-source-live.spec.ts`、`docs/platformization/data41/evidence/`。

## 4. 数据源、转换与真实性边界

| 场景 | 来源 | License | 源记录 | 提交快照 | 时间范围 | 活动 run_id |
|---|---|---|---:|---:|---|---|
| charging_ops | ACN-Data，经 ORNL OpenEnergyDataPortal 分发 | CC BY 4.0 | 26 | 26 | 2020-05-09 至 2020-06-09 | `DATA41-ACN-ORNL-26-V1` |
| sales_ops | UCI Machine Learning Repository Online Retail | CC BY 4.0 | 541,909 | 27,095（原工作簿每第 20 行的确定性全周期样本） | 2010-12-01 至 2011-12-09 | `DATA41-UCI-ONLINE-RETAIL-352-V1` |

- ACN 充电金额按公开费率/电价假设派生，原始字段与派生字段在映射 JSON 中分开记录。
- UCI 成本使用明确的 70% 场景假设，不宣称为企业真实成本。
- ACN 无设备状态字段，因此设备在线率/故障率返回数据不足，不生成虚构状态事件。
- 固定种子旧数据只保留为自动化 fixture/regression dataset，不作为 4.1 活动业务数据集。

## 5. 数据库影响、安全影响与版本

- Migration head：`data_0001`，down revision 为 `p5_0001`。
- charging_ops DatasetVersion：2 ACTIVE；sales_ops DatasetVersion：2 ACTIVE。
- 入库：ACN raw/staging/core 26 条；UCI raw/staging 27,095 条，core 13,665 个订单。
- 质量：ACN 13/13、UCI 15/15，总计 28/28 PASS；旧 DQ-001 至 DQ-020 未删除或弱化。
- 权限：业务数据仍经 OIDC、身份映射、ABAC/区域过滤、正式 API 和发布语义层读取。
- Query Guard 拒绝不可绕过；Answer Composer 使用当前数据库真相，不再固定写“模拟数据”。
- 秘密：没有提交 `.env`、密码、Token、真实连接串；最终新增行秘密扫描命中 0。

## 6. 执行命令

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\release\start-project.ps1 -NoBrowser -TimeoutSeconds 1200 -EvidencePath docs/platformization/data41/evidence/data41-cold-start.json
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\release\start-project.ps1 -NoBrowser -TimeoutSeconds 600 -EvidencePath docs/platformization/data41/evidence/data41-warm-start.json
python scripts/run_p5a_full_postgres_regression.py --expected-tests 368 ...
python scripts/verify_alembic_schema_cycle.py --runtime-bootstrap --output docs/platformization/data41/evidence/data41-migration-cycle.json
npm.cmd test -- --run
npm.cmd run build
npx.cmd playwright test e2e/data41-open-source-live.spec.ts --reporter=junit
npx.cmd playwright test e2e/p4-preproduction-oidc.spec.ts --reporter=junit
python scripts/run_p5a_secret_scan.py --baseline 5de9ea85d0472b98a9265c29623c5ceb1b1cf1b2 --scope DATA-4.1 ...
python scripts/verify_data41_frontend_truth.py --output docs/platformization/data41/evidence/data41-frontend-truth-scan.json
```

实际 Python 使用 Codex 工作区捆绑运行时；依赖仅在当前工作树/容器中安装，没有全局安装。

## 7. 测试结果与验收证据

| 门禁 | 结果 | 证据 |
|---|---:|---|
| 冷启动与一键启动 | PASS | `evidence/data41-cold-start.json` |
| 热启动幂等复用 | PASS；两源 `reused=true`，启动下载 false | `evidence/data41-warm-start.json` |
| PostgreSQL 完整回归 | 368/368，0 fail/error/skip | `evidence/data41-postgres-full-final-rerun.json` |
| DATA/Catalog 隔离验收 | 5/5 | `evidence/data41-catalog-focused.json` |
| live DB→API→UI/ChatBI | 1/1 | `evidence/data41-playwright-live.xml` |
| OIDC live/负向 | 3/3 | `evidence/data41-playwright-oidc.xml` |
| Alembic 全链循环 | upgrade/downgrade/re-upgrade PASS，验证库已删除 | `evidence/data41-migration-cycle.json` |
| 前端造数禁令扫描 | 0 finding | `evidence/data41-frontend-truth-scan.json` |
| 敏感信息扫描 | 0 finding | `evidence/data41-secret-scan.json` |
| 总门禁 | PASS | `evidence/data41-acceptance-summary.json` |

失败尝试 XML 被保留：日期右开区间断言和 Playwright 初始化请求竞态均已修正；另有一轮 368 回归因新增单测 run_id 夹具不一致而 367/368，修正后完整复跑 368/368。没有删除失败证据。

## 8. 未完成事项与限制

- SQLBot 仅准备 Schema Catalog，运行时仍禁用；正式开放式 NL2SQL 属下一阶段。
- AFDC 因验收环境官方 API 主机解析不稳定仅列候选；PJM 因官方再分发限制未提交快照。
- ACN 发现副本仅 26 条，适合建立真实链路基线，不代表企业规模或生产容量。
- `npm audit` 报告基线依赖中 1 个 high severity 项，未自动执行可能改变锁文件的 `npm audit fix`；下一阶段应在独立依赖升级工作包处置。
- Git 远端推送状态不属于本地运行门禁，最终交付消息单独报告。

## 9. 风险与回滚方式

- 数据解释风险：派生价格/成本必须继续显示为派生假设，不可改写成源字段或企业实绩。
- 样本代表性风险：UCI 为确定性抽样，分析只可表述为公开样本结果。
- 代码回滚：对 DATA 独立提交执行 `git revert <DATA_COMMIT>`，不得改写历史。
- Schema 回滚：先备份并停止 DATA 写入，再执行 `alembic downgrade p5_0001`；迁移循环已验证。不得删除正式卷或审计历史。
- 业务数据回退：重新激活原模拟 DatasetVersion/场景批次；公开数据行均可按 run_id/batch_id 识别。不要手工删除事实行。
- 运行时回退：停止 `renewable-data41` Compose 项目并用原 P5B Compose 启动；P5B 卷在交接时被保留。

## 10. 是否允许进入下一阶段

允许。建议下一阶段以已发布 Schema Catalog v2 和两个 ACTIVE DatasetVersion 为输入，实施受控开放式 NL2SQL/SQLBot 评测；继续保持 Query Guard、只读执行、权限前置、Answer Guard 和 SQLBot 失败不影响确定性主链路。
