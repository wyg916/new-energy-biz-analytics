# 作品证据与表述边界

## 可展示能力

1. 数据库驱动的 15 指标经营驾驶舱与场站专题；
2. Query Plan、确定性 SQL、Query Guard、Answer Guard 和证据面板构成的可信 ChatBI；
3. 有限多轮上下文、显式覆盖、跨用户/跨会话隔离和 analysis_run；
4. 异常检测、同群比较、收入/毛利桥接与场站贡献；
5. 带来源、版本、批次和 run_id 的周报/月报草稿与导出；
6. 33 个后端测试、40 题固定评测、20 项数据质量规则和 Docker/Playwright 验收。

## 推荐作品集表述

“独立实现新能源经营分析产品级 Alpha：以 30 万条固定 seed 模拟充电会话为数据底座，构建 15 项指标语义层、经营驾驶舱、受控 ChatBI、有限多轮记忆、异常拆解与可追溯报告；在本地 Docker Compose 环境完成 33 个后端测试、40/40 固定评测、20/20 数据质量规则和核心浏览器 E2E。”

## 禁止夸大

不得写成已接入真实企业数据、已生产上线、真实客户在用、真实降本增收、支持任意自然语言/任意 SQL、生产级多租户或高可用。截图、页面和报告中的业务数字全部是模拟数据。

## 证据索引

- 页面截图：`docs/evidence/screenshots/01-login.png` 至 `05-report.png`；
- 测试与评测：`docs/test_and_evaluation_report.md`；
- 机器结果：`tests/evaluation/output/`；
- 实现架构：`docs/architecture_alpha.md`；
- Alpha 验收：`docs/phase_8_acceptance.md`。
