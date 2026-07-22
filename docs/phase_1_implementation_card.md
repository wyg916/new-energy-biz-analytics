# Phase 1 实施卡与验收记录

状态：已授权并完成（2026-07-22）。本文件关闭原 C-01/C-02。

## 冻结运行环境

- Python 3.11.9；后端 FastAPI 0.115.12、SQLAlchemy 2.0.41、Alembic 1.16.1。
- Node.js 24.x；npm 11.x；React 19.1、Vite 6.4。
- PostgreSQL 16.9、Redis 7.4.5、Docker Compose 2.26+。
- 端口：Web 8080、宿主 API 18000（容器内 8000）、PostgreSQL/Redis 仅 Compose 内网暴露。原宿主 8000 在 Phase 8 验收时发现被仓库外进程占用，因此采用可回滚端口调整。

## 验收范围

认证登录、401/403、三类角色、JSON 日志、统一错误结构、可逆迁移、开发配置与生产 fail-closed、后端/前端容器基础设施。低保真原型作为页面信息架构基线，由项目负责人本轮连续授权关闭视觉门。

## 非目标

本阶段不声明指标、ChatBI、记忆或报告功能完成。

## 回滚

代码使用本阶段独立 Git 提交回滚；数据库执行 `alembic downgrade base` 后可重新升级。

## 运行验收证据

- Alembic：`upgrade head → downgrade base → upgrade head` 通过。
- 后端：6 项认证、401、403、健康检查及生产 fail-closed 测试通过；语句覆盖率 95%。
- 前端：TypeScript 与 Vite 生产构建通过。
- Compose：配置解析通过；全容器启动留在 Phase 8 新环境验收执行。
