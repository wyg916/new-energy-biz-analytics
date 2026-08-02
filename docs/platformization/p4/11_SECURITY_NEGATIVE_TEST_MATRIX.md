# P4 安全负向测试矩阵

| 边界 | 实际攻击/故障 | 结果 |
| --- | --- | --- |
| OIDC | 伪造签名、错误 issuer/audience、过期、nonce/state 重放 | 成功数 0，PASS |
| 身份入口 | 预生产 LOCAL bearer | 401，成功数 0，PASS |
| 映射 | 未映射、禁用、错误组、跨 tenant/workspace | 成功数 0，PASS |
| 前端 | 伪造 tenant/user 或直传权限字段 | 服务端忽略，成功数 0 |
| RBAC/ABAC | 跨租户、跨 workspace、跨场景、无策略 | 默认拒绝，成功数 0 |
| 数据源 | 未审核直接 ACTIVE、缺 Secret、跨租户访问 | 成功数 0 |
| SQL | 写入、多语句、危险函数、未发布 source、自由 SQL | Query Guard 拒绝，15/15 |
| Secret | 引用禁用、版本缺失、Vault 停机/认证失败 | fail-closed，无明文 fallback |
| 输出 | Secret 日志/API/前端泄漏 | 0 |
| RAG | 越权文档、prompt injection、依赖不可用 | 拒绝/受控降级，无伪造引用 |
| SQLBot | 无授权外部凭据、运行时故障 | 请求 0；主答案影响 0 |
| 告警 | 重放、错误签名、超时、连续失败 | 幂等、拒绝、审计、熔断 |
| 发布 | 未审核 ACTIVE、production activate | 拒绝；production 授权 false |

高置信度 tracked-file Secret 扫描命中 0，且按约束未扫描 `.env*`。API 最终镜像使用固定 digest 的 Python 3.11.15 Alpine 基础镜像，FastAPI 0.139.2、Starlette 1.3.1、PyJWT 2.13.0；删除运行时 pip/setuptools/wheel 后 Docker Scout 复扫为 0 Critical / 0 High。首次旧 API 镜像扫描的 4 Critical / 45 High 已通过重建消除，不被隐藏或改写为成功。

最终预生产镜像复扫结果：React Web/Nginx 0 Critical / 0 High；加固 PostgreSQL 16.14（用 Alpine `su-exec` 替换上游静态 `gosu`）0/0；Redis 7.4.10 0/0；Vault 2.0.3 为 0 Critical / 1 High；Keycloak 26.7.0 因 Docker Scout 层分析超时，改用 Trivy 0.70.0、10 分钟上限复扫，结果为 0 Critical / 15 High（12 个唯一漏洞），完整报告 SHA-256 `cc8e9f6618ae4d5a395280f030d2fab02ed9000177e2dc548ae4d19759dbdaf5`。Vault 和 Keycloak 的未修复上游项进入生产外部门禁，不将其写成 PASS。

SQLBot `v1.8.0` profile 默认禁用，已固定 registry digest，但因没有授权外部凭据、未进入本轮运行栈，未执行该镜像漏洞扫描。它不能被视为安全签署通过；启用或生产验收前必须完成独立扫描与风险处置。

依赖扫描覆盖和残余结果见 `10_RELEASE_CANDIDATE_MANIFEST.md`；真实企业基础设施的扫描/签署仍是生产外部门禁。
