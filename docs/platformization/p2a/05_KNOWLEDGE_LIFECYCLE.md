# 知识文档生命周期

更新时间：2026-07-31

## 状态机

实现状态：

```text
UPLOADED → PARSING → PARSED → CHUNKED → INDEXING
→ VALIDATING → READY → PUBLISHED → SUPERSEDED / RETIRED
```

失败进入 FAILED。逻辑删除保留审计事实并使版本不可召回。

## 版本与发布规则

- document 与 document_version 分离；
- 保存 source、SHA-256、tenant/workspace/scenario、权限与有效期；
- 原始批准源不被运行时代码改写；
- READY 前和 PUBLISHED 前均不可正式召回；
- 新版本发布后旧版本变为 SUPERSEDED；
- 默认仅召回当前有效 PUBLISHED 版本；
- 引用绑定 document_version_id 与 chunk_id；
- 支持 publish、retire、rollback 和逻辑删除。

真实 API 已完成 ingest→publish→retrieve，并用三份正式文档跑通；测试覆盖未
发布不可召回、替代、撤回、回滚、删除和越权。生命周期专项 `4/4 PASS`，
知识/复合 API 当前专项 `5/5 PASS`。

## 数据库

`0013_knowledge_lifecycle.py` 新增 6 张治理表，upgrade/downgrade 均可执行。
全迁移已在专用临时数据库完成 `base → 0014 → base → 0014`，临时数据库已
删除，业务数据库未升降级。
