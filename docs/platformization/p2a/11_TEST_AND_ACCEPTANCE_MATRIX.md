# P2A 测试与验收矩阵

更新时间：2026-07-31

## 强制回归

| 项目 | 结果 | 证据边界 |
|---|---:|---|
| 后端全量 | 163/163 PASS | 四个隔离分片 54/32/42/35 |
| 最后源清单/API专项 | 5/5 PASS | 在全量后增补批准源断言 |
| Deterministic 固定评测 | 40/40 PASS | Query Plan/安全行为 |
| 双引擎离线合同 | 100/100 PASS | 非 SQLBot 运行准确率 |
| charging_ops 指标 | 15/15，differences={} | 固定冻结基线 |
| sales_ops 指标 | 12/12，differences={} | 固定 seed 模拟数据 |
| PostgreSQL DQ | 20/20 PASS | failures=[] |
| Alembic | base→0014→base→0014 PASS | 专用临时数据库已删除 |
| Docker smoke | 6/6 PASS | 主平台实际 Compose |
| SQLBot 只读角色 | PASS | 禁止操作成功数 0 |
| Model Gateway | 5/5 PASS | live provider 待完成 |
| Knowledge lifecycle | 4/4 PASS | SQLite 隔离合同 |
| Response Composer | 7/7 PASS | 四 Profile/JSON/拒答 |
| RAG Golden | 60 cases PASS | 关键词模式，非向量 |
| Vitest | 3/3 PASS | 前端格式 |
| 前端构建 | PASS | 41 modules |
| Playwright | 20/20 PASS | 实际 Web/API |
| npm audit | 0 vulnerabilities | 前端锁定依赖 |

后端全量运行先发现容器资源挂载不足，补齐 samples/scripts/deploy/evaluation
只读挂载后四分片全部通过；没有改弱断言或跳过用例。

## RAG 60 指标

- case_count=60
- Recall@10=0.8936
- MRR=0.9667
- rerank_hit_rate=1.0
- citation_accuracy=1.0
- citation_validity=1.0
- answer_faithfulness=1.0
- ungrounded_answer_rate=0.0
- refusal_accuracy=1.0
- p50=34 ms，p95=84 ms
- token_usage=0
- 所有越权/跨场景/失效版本/注入成功数=0

时延来自隔离 SQLite 关键词评测，不外推为生产或向量性能。

## SQLBot

- 固定容器 healthy，HTTP 200；
- 两个只读角色禁止写入/DDL/系统对象/跨场景；
- 实际模型、100 条运行评测、真实 Shadow：未通过；
- SBOM/漏洞扫描：10 分钟超时，PENDING。

## 工作区隔离说明

验收后段出现另一组并发未提交的 Dashboard、指标、前端和未跟踪 `0015`
修改。它们不属于 P2A 提交，未进入当前数据库和上述 P2A Git 提交；最终
工作区状态需单独报告。
