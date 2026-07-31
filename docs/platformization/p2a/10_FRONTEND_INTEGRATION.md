# 自有 React UI 集成

更新时间：2026-07-31

## 新增能力

- 侧栏“企业知识库”入口；
- 批准知识源目录；
- ingest、版本状态、发布、撤回、回滚和逻辑删除；
- 检索测试、引用抽屉、section/score/version/chunk 展示；
- ChatBI 四种回答风格选择；
- 数据/知识/复合路由和引用；
- Model Gateway、SQLBot、RAG/vector 真实状态条；
- 警告、拒答、模拟数据、run_id/trace_id 与用户反馈。

浏览器不直接调用 SQLBot，也没有 iframe 嵌入 SQLBot UI。上传控件在通用文件
上传尚未实现时禁用并说明原因，只能从批准源目录入库。

## 兼容性

统一编排首次接入曾覆盖旧业务 run_id、ACTIVE 版本和 SHADOW 证据；修复后
保留底层 QueryResult/Query Plan/Guard/版本，同时继续展示复合编排和引用。
原 E2E 期望未修改。

## 验收

- Vitest：3/3 PASS
- TypeScript + Vite：PASS，41 modules
- npm audit：0 vulnerabilities
- 新增知识/回答 E2E：2/2 PASS
- Playwright 全量：20/20 PASS

所有经营页面仍显示模拟数据、数据时间、来源和运行证据。
