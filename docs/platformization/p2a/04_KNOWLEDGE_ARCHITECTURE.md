# Knowledge Service 架构

更新时间：2026-07-31

## 模块

`backend/app/knowledge/` 是模块化单体内的独立知识边界，包含：

- 显式批准源清单；
- parser、normalizer、chunker、ingestion；
- publication、authorization、retrieval、reranker；
- citation、security、API 和运行状态。

正式数据流：

```text
显式批准的跟踪文档
→ 解析/清理/切块
→ 版本校验
→ READY
→ 管理员发布
→ 权限与有效期 SQL 前置过滤
→ 关键词全文召回
→ 去重/Rerank
→ 固定版本引用
→ Response Composer
```

## 知识域与源

支持 metric_definition、data_dictionary、business_rule、
analysis_method、scenario_guide、security_rule、system_help。

首批源全部为仓库内已跟踪、已审阅、无秘密的 Markdown，包括指标字典、Query
Plan/RBAC/数据合同、场景/确定性引擎/权限 ADR、sales_ops 场景说明和经营预警
验收边界。没有自动目录扫描。

四份用户源文档不在批准清单，API 实测返回
`KNOWLEDGE_SOURCE_DENIED`；它们未被读取、解析、上传或索引。

## 当前运行量

真实 PostgreSQL 已发布 3 个 document/version、33 个 chunk；当前 Knowledge
API 为 READY，数据分类为 simulated。迁移见 `0013`。
