# Alpha 当前能力与边界

## 已实现并在本轮复核

- FastAPI、React/Nginx、PostgreSQL、Redis 的模块化单体 Compose；
- 认证、RBAC、区域范围、401/403、审计与生产配置 fail-closed；
- 固定 seed 模拟数据、30 万充电会话、15 项指标和 20 条数据质量规则；
- 数据库驱动的总览、收入、毛利、场站和设备分析；
- Query Plan、确定性参数化 SQL、Query Guard、只读执行和 Answer Guard；
- 固定 40 题 ChatBI 评测、危险 SQL 12 条拒绝、有限多轮会话状态；
- 异常、同群比较、收入/毛利拆解、贡献定位和相关非因果边界；
- 周报/月报草稿、Markdown/CSV 导出、analysis_run 和来源证据；
- Docker Compose 启动、可回滚迁移、API/Web 健康与一键启动脚本。

## 当前未实现

- 系统管理或审计前端页面；
- CSV/Excel/PostgreSQL 可配置数据接入；
- charging_ops 可安装场景包；
- HTTPS、自动备份恢复、监控告警和发布候选流程；
- 原生 DOCX/PDF 导出、SSO、生产级共享多租户；
- 长期个人记忆、多 Agent、自动邮件/工单、自由 SQL；
- MySQL、REST API 数据源、Kafka、CDC、Kubernetes。

## 真实性边界

本轮仅证明代码、固定模拟数据和本地 Docker Compose 环境可复现。不得宣称企业生产上线、真实客户使用、真实经营收益或真实大规模场站支撑。
