# 前端数据集真实闭环

## 13 步操作

React 数据接入页实现：

1. 创建/幂等登记数据源；
2. 测试连接；
3. 发现 Schema/Table/Column；
4. 数据预览；
5. 字段映射核验；
6. 数据质量检查；
7. 创建不可变 DatasetVersion；
8. 提交审核；
9. 批准；
10. 发布；
11. 原子激活；
12. 查看当前 ACTIVE；
13. 回滚并显示 rollback_record 数量。

另提供待审版本驳回入口和 charging_ops 场景底座安装/重验入口。

## 真实后端绑定

- 数据源创建：`POST /api/v1/platform/foundation/sources`
- 管理源发现：`GET /sources/{id}/discover`
- 平台状态：`GET /api/v1/platform/foundation`
- DatasetVersion：create/submit/approve/reject/publish/activate
- 回滚：`POST /datasets/{id}/rollback`

按钮执行后以响应中的数据库 state 刷新，不使用静态成功状态。管理型 PostgreSQL 预览已从 DashboardService 解耦，直接读取受权限约束的源事实投影。

## 状态

- Loading：按钮和状态显示处理中；
- Empty：未安装/无 ACTIVE/空 Schema 明确显示；
- Error/Blocked：错误面板显示并声明无 fallback；
- Success：只显示后端返回后的状态；
- Unauthorized：清除会话并返回登录；
- Forbidden：显示权限阻塞；
- Stale/Conflict：409 信息显式呈现；
- Reject/Activation failure：保持旧状态并刷新数据库事实。

## 验证

Playwright 全量 17/17 PASS，其中新增覆盖：

- Unauthorized、Forbidden；
- 空 Schema、字段发现失败、连接失败、DQ 失败；
- 审批驳回；
- 激活失败保留旧 ACTIVE；
- 回滚；
- 无静默 fallback。
