# P5C 一键启动与版本合同

## 唯一入口

根目录唯一面向用户的入口为 `一键启动.bat`，实现脚本为 `scripts/release/start-project.ps1`。批处理文件不再启动旧的四服务 Alpha Compose，而是启动 P5B `4.0.0-rc.3` 预生产组合：

```text
deploy/preproduction/compose.yaml
+ deploy/production-acceptance/p5b.override.yaml
-> renewable-p5b-gate-closure
```

## 启动行为

1. 检查 Docker Engine；
2. 校验合并后的 Compose 配置；
3. 按 Compose 中的内部加固标签或上游精确 digest 验证 10 个冻结镜像引用已存在，不以普通 Dockerfile 重建安全加固镜像；
4. 以 `docker compose up -d --wait` 启动 PostgreSQL、Redis、Vault、Keycloak、API、Web、Nginx、备份及幂等初始化任务；
5. 验证 API health/readiness、Web、OIDC discovery；
6. 验证数据库迁移为 `p5_0001`；
7. 写入不含秘密值的 `runtime/p5c-startup-report.json`；
8. 成功后打开 `https://p5b.localhost:8446`。

自动验收可使用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts/release/start-project.ps1 `
  -NoBrowser `
  -EvidencePath docs/platformization/p5c/evidence/p5c-startup-report.json
```

## 版本源

| 对象 | 当前事实 |
|---|---|
| P5B 运行时候选 | `4.0.0-rc.3` |
| Alembic head | `p5_0001` |
| P5C 主控分支 | `codex/p5c-baseline-convergence` |
| 4.1 流 | `PLANNED_NOT_YET_RC` |
| 生产授权 | false |
| 生产切流 | false |

Python/前端包中的 `0.1.0` 是历史组件包版本，不是当前 RC 发布版本；本阶段不伪造性地批量改写它们。后续发布应建立一个正式单一版本源，再由构建生成后端、前端和 Manifest 版本。

## 限制

该启动入口依赖已由 P5B 验收生成并固定的本地加固镜像。若镜像缺失，脚本 fail-closed，并提示先执行受控镜像恢复流程；它不会用普通 base Dockerfile 覆盖加固标签。
