# SQLBot v1.8.0 运行部署

更新时间：2026-07-31

## 固定制品

- 上游版本：`v1.8.0`
- 冻结提交：`b2de038`
- 镜像：`dataease/sqlbot:v1.8.0`
- Image ID：`sha256:5065baf17703cfad0407261c16d15c0aecb237877011e1603f59fb70a1f58abf`
- RepoDigest：`dataease/sqlbot@sha256:c4ca3acc34f0c63a64f3f3e7bb909760f17d184959635542278710144347d9e0`
- 平台/大小：Linux amd64，4510721820 bytes

未切换到 `latest`、`main` 或其他版本，也未复制 SQLBot 源码进项目核心。

## 实际容器与边界

- 容器：`renewable-sqlbot-v1-8-0`
- 运行状态：running，health=healthy，restart_count=0
- 管理入口：只绑定 `127.0.0.1:18080`
- 根路径探针：HTTP 200
- 网络：内部网络 `renewable-sqlbot_sqlbot_internal` 与共享代理网络
  `renewable-sqlbot-proxy`
- 卷：独立 excel、file、images、logs、postgresql 五类卷
- 上游要求：`privileged=true`

初始探针访问受认证保护的 OpenAPI，实际返回 401，导致容器长期
`starting`。探针改为公开根路径后重建，50 秒内达到 healthy。privileged
只允许当前本地隔离验收，禁止进入生产默认部署。

## 供应链证据

Docker SBOM 插件和 Docker Scout 均可调用，但对 4.51 GB 镜像的实际扫描
分别在 10 分钟后超时：

- `SBOM_PENDING`
- `VULNERABILITY_SCAN_PENDING`

没有生成或提交不完整 SBOM/SARIF，也不把工具存在表述为扫描完成。这两项和
privileged 均是生产发布阻塞。

## 启停和清理

启动必须从不跟踪的运行时环境提供三个必需秘密：

```text
docker compose --env-file <untracked-runtime-env> -f deploy/sqlbot/compose.yaml up -d
```

停止容器但保留独立卷：

```text
docker stop renewable-sqlbot-v1-8-0
docker rm renewable-sqlbot-v1-8-0
```

不得使用删除卷参数。主平台 `SQLBOT_ENGINE_ENABLED=false`、
`SQLBOT_RUNTIME_VERIFIED=false`，SQLBot 启停未影响 API、PostgreSQL、
Redis、Web 或 DeterministicEngine。

## 结论

容器、端口、网络、卷和健康为 PASS；实际模型、模拟 datasource、实际 SQL
和运行评测尚未完成，供应链扫描亦未完成。

`SQLBOT_RUNTIME = CONDITIONAL`
