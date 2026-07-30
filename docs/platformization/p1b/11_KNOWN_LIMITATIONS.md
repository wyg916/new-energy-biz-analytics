# P1B 已知限制

更新时间：2026-07-31

## 1. 外部安全闭环仍未完成

`P0_EXTERNAL_SECURITY=PENDING`。外部数据库/API 凭据的撤销、轮换和访问日志
核查仍需仓库外管理员确认。本轮没有读取、输出、复述、猜测或使用具体凭据，
也没有连接相关外部系统。

这是仓库外阻塞，不能用代码、Mock 或本地测试关闭。

## 2. SQLBot Runtime 尚不可用

固定镜像 `dataease/sqlbot:v1.8.0` 尚未取得到本机，本轮没有 SQLBot 容器、
真实模型健康检查或模拟 datasource 的实际上游调用。平台保持：

```text
SQLBOT_ENGINE_ENABLED=false
SQLBOT_RUNTIME_VERIFIED=false
SQLBOT_MODE=SHADOW
```

平台健康检查为 `DISABLED`，上游真实健康为 `PENDING`。因此没有真实 SQL
执行成功率、Execution Accuracy、P50/P95、Token 或 Shadow 一致率，不能
进入 `SQLBOT_ENABLED` 或用户可见 SQLBot Canary。

## 3. 固定上游版本没有稳定的只生成 SQL 公共合同

SQLBot v1.8.0 内部存在生成 SQL 步骤，但公开 MCP 请求合同没有稳定的
generate-only/执行前 Hook/自定义执行器接口。若后续只能使用上游内部执行，
必须先完成：

- 独立只读角色；
- 专用 semantic schema/view；
- 事务只读与 statement timeout；
- 表、字段、行数和并发限制；
- ACTIVE Scenario/Dataset/Semantic 版本绑定；
- 实际 SQL 审计和项目 Query Guard 复验。

固定上游镜像还要求 privileged 本地容器，只允许隔离评测，不满足生产边界。

## 4. Golden Set 当前只完成离线合同验收

100 条 Golden Set 的 `100/100 PASS` 表示结构、指标/维度引用、拒答标签和
安全候选合同有效，不表示 SQLBot 真实执行 100/100。所有运行型指标保持
`null`，Canary 阈值尚未评估。

## 5. MySQL 真实服务器集成未验收

MySQL Connector 的预览、画像、分页、批读、归一化、超时、错误映射和健康
合同已通过隔离驱动模拟。当前本机没有用于验收的 `mysql:8.4` 镜像，未连接
任何真实或附件中的 MySQL。

`read_incremental` 仍明确返回 `UNSUPPORTED`，没有用全量读取冒充增量。

## 6. SQLBot Canary 保持阻断

tenant、workspace、user、scenario、percentage 范围和确定性分桶已经实现，
但首轮只完成平台路由合同。生产环境仍固定：

```text
PLATFORM_VERSION_ROUTING_ENABLED=false
QUERY_ENGINE_MODE=DETERMINISTIC_ONLY
```

开发/测试默认 SHADOW 不等于 SQLBot 已对用户开放。未命中 Canary 或 Runtime
未验证时均 fail-closed，不允许静默 fallback。

## 7. 全量后端测试夹具耗时高

测试夹具为每个非 `no_db` 用例重建完整 Schema。111 个测试函数参数化为
140 个 case，单容器串行执行两小时仅完成约 51%。本轮以四个互斥文件分片和
独立临时 SQLite 数据库完成 140/140，不跳过测试、不修改断言。

后续可优化 fixture 复用、事务回滚或预构建模拟数据快照，但必须保持用例隔离
和失败语义，不能以弱化测试换取速度。

## 8. 产品范围仍受冻结边界约束

P1B 不包含：

- 完整 RAG；
- 长期 Agent Memory；
- 多 Agent；
- 第三个场景；
- Kubernetes；
- 完整 SSO；
- 真实企业外部数据；
- 生产发布；
- 自动邮件、工单或跨系统执行。

收藏、导出和分享等未实现 UI 操作保持禁用并说明原因。

## 9. P2 入口

`P2_ENTRY=NOT_ALLOWED`。至少需要：

1. 仓库外管理员完成外部凭据撤销、轮换和日志核查确认；
2. 固定 SQLBot Runtime、模型和模拟 datasource 真实可用；
3. SQLBot 独立只读数据边界通过负向验证；
4. 真实 100 条评测达到 Canary 阈值；
5. 危险 SQL、越权和跨场景成功数继续为 0。

普通非安全缺陷可进入 backlog，但上述真实性、安全和运行证据不能豁免。

## 10. 回滚限制

- 逻辑回退优先关闭平台版本路由并切到 `DETERMINISTIC_ONLY`；
- `0012 → 0011` 会删除双场景会话绑定表；
- `0011 → 0010` 会删除 sales_ops 模拟数据表；
- `0010 → 0009` 会删除 SQLBot session、Shadow 和路由证据表；
- 降级前应导出需要保留的审计证据；
- 不需要也不得删除 PostgreSQL 数据卷。
