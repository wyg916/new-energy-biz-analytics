# 产品级 Alpha 实现架构

## 形态与运行边界

系统采用模块化单体：一个 FastAPI 应用承载认证、指标、驾驶舱、ChatBI、诊断和报告 API；一个 React 单页应用负责交互；PostgreSQL 保存业务事实、身份、会话状态、analysis_run 与审计；Redis 作为已编排的短期基础组件。Nginx 提供静态页面并反向代理 `/api/`。

```text
Browser :8080
  └─ Nginx / React
       └─ /api → FastAPI :8000 (host :18000)
                    ├─ PostgreSQL 16.9
                    └─ Redis 7.4.5
```

部署边界为单机 Docker Compose Alpha，不声称高可用或生产级多租户。

## 核心模块

| 模块 | 实现位置 | 责任 |
|---|---|---|
| 配置/安全 | `backend/app/core` | 集中配置、JWT、日志、数据库与 fail-closed |
| 身份与范围 | `backend/app/api/auth.py`、`models/auth.py` | 认证、角色、区域范围、审计 |
| 数据与质量 | `backend/app/data`、`models/business.py` | 固定 seed、事实维度、20 项质量门禁 |
| 指标服务 | `backend/app/services/metrics.py` | 15 项指标的唯一计算入口 |
| 驾驶舱 | `backend/app/services/dashboard.py` | KPI、趋势和场站排行 |
| 可信 ChatBI | `backend/app/chatbi` | 解析、计划、编译、Guard、只读执行、答案与记忆 |
| 诊断 | `backend/app/services/diagnostics.py` | 异常、同群、收入/毛利拆解和贡献 |
| 报告 | `backend/app/services/reports.py` | 可审核草稿、Markdown/CSV 导出和回溯 |

## 数据与可信链路

所有页面、问数、诊断和报告数字均调用数据库上的结构化计算；前端没有 seed/demo/fallback 业务数字。Query Plan 只允许已发布指标、维度、过滤和时间范围；Compiler 只生成单条参数化只读查询；Guard 以 AST、表字段白名单、参数和范围交集进行二次校验；Answer Guard 只允许回答绑定结构化结果中的数字。

每次 ChatBI 与报告运行记录 `analysis_run_id`、用户、权限范围、Query Plan/版本、指标版本、模拟数据批次、结果摘要与状态。页面和导出显示模拟数据、数据时间、来源和 run_id。

## 安全和配置

- 未认证返回 401，角色或区域越权返回 403；
- 区域权限在编译前与请求过滤取交集并 fail-closed；
- 任意 SQL、DDL/DML、多语句、系统表、文件/延时函数和注释绕过均拒绝；
- 生产环境拒绝示例密钥、默认数据库口令和自动演示账号；
- 数据库迁移支持 upgrade、downgrade、re-upgrade。

## 取舍

Alpha 使用确定性规则解析中文合同内问题，保证可测、可解释和可离线复现；它不宣称开放域自然语言覆盖。短期工作状态是进程内、会话状态持久化至数据库；没有实现跨设备长期偏好记忆。报告以可审核草稿和 Markdown/CSV 为边界。
