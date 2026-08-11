# 项目二知识基线包 v1.0.0｜落地说明

适配 Integration-Core SHA：

`0a2c776cd6ba47598a17286a793f3c570823cf77`

## 目标

解压到项目仓库根目录后，本包提供 9 类核心知识文档，并附：

- Approved Source allowlist 安装脚本；
- Governed Knowledge API 摄取/发布脚本；
- 发布后非空索引验证脚本；
- 机器可读 import plan；
- SHA-256 完整性清单。

## 文件放置

**请把压缩包内容直接解压到项目仓库根目录。**

解压后会出现：

- `docs/knowledge_baseline/v1/`
- `integration/`
- `scripts/install_knowledge_baseline_v1.py`
- `scripts/apply_knowledge_baseline_v1.py`
- `scripts/publish_knowledge_baseline_v1.py`
- `scripts/verify_knowledge_baseline_v1.py`
- `安装知识基线包.bat`
- `发布知识基线包.bat`

不会覆盖现有 `一键启动.bat`。

## 第一步：安装来源清单

在仓库根目录双击：

`安装知识基线包.bat`

它会：

1. 校验知识包 SHA-256；
2. 向 `backend/app/knowledge/approved_sources.py` 幂等增加本包知识路径；
3. 生成 `.bak` 备份；
4. 不保存、不读取任何密钥；
5. 不自动发布知识。

## 第二步：启动当前 Integration 项目

继续使用项目现有：

`一键启动.bat`

确认：

- API READY；
- PostgreSQL READY；
- Redis READY；
- 当前 migration 为 Integration 唯一 head；
- RAG runtime 可访问。

## 第三步：发布知识

Knowledge API 的发布动作要求有权限的真实管理员身份。自动治理角色只能做质量检查，不能替代发布身份。

在当前终端临时设置：

```bat
set KNOWLEDGE_ADMIN_TOKEN=<当前 analyst_admin 的 Bearer Token>
```

然后运行：

`发布知识基线包.bat`

Token 只从进程环境读取，不写入仓库。

本地 Integration 验收也可使用 `scripts/apply_knowledge_baseline_v1.py`：它通过真实
Authorization Code + PKCE 获取应用 Token，核验 `analyst_admin` 后再执行发布与验收。
密码与 Token 均只保留在进程内存中，不得写入仓库或 evidence。

该脚本会：

- 按 `integration/knowledge_import_plan.json` 摄取；
- 复用同一来源文档的已有 document_id，避免无意义重复文档；
- 发布 READY 版本；
- 最后检查 `/knowledge/runtime`；
- 要求 `published_chunk_count > 0`；
- 要求 `published_chunk_count == indexed_chunk_count`。

如果本机 TLS 证书不是受信任证书，bat 只在本地集成环境使用 `--insecure`。正式环境不得跳过 TLS 验证。

## 第四步：验收建议

`scripts/verify_knowledge_baseline_v1.py` 会自动执行 20 个固定业务问题，并核验
Citation 的 document/version/chunk/locator/score、Answer Guard、未认证访问、Prompt
Injection 与无证据拒答。以下问题也适合人工抽查：

至少问：

### charging_ops

1. “充电收入的定义是什么？”
2. “为什么当前不能给出设备在线率的数值？”
3. “度电成本怎么计算？”
4. “收入下降怎么做拆解？”
5. “哪些数据字段来自公开源，哪些是派生字段？”

### sales_ops

1. “UCI Online Retail 当前怎么接入？”
2. “销售成本为什么不是源字段？”
3. “CustomerID 如何处理？”
4. “sales_ops 支持哪些分析维度？”
5. “为什么不能把销售收入与充电收入直接相加？”

### 安全

1. “SQLBot 生成的 SQL 能直接执行吗？”
2. “可以查询 pg_catalog 吗？”
3. “用户请求其他区域数据时怎么处理？”

## 版本更新

以后以下情况必须发布新知识版本：

- 指标口径变化；
- DATA 数据源/映射变化；
- Schema Catalog 变化；
- SQL Policy 变化；
- RAG 检索/引用合同变化；
- SQLBot 进入新 Release 状态；
- P6 合并后功能使用说明发生变化。

不要直接覆盖历史已发布知识正文。
