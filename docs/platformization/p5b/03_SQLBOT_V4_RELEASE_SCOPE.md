# SQLBot v4 首版发布范围冻结

## 结论

- `SQLBOT_INCLUDED_IN_V4_RELEASE=false`
- `SQLBOT_RUNTIME=NOT_INCLUDED`
- `SQLBOT_IMAGE_INCLUDED_IN_BOM=false`
- `SQLBOT_EXTERNAL_EVALUATION=DEFERRED`
- `SQLBOT_CANARY_ELIGIBLE=false`
- Adapter 与离线合同测试继续保留，不代表运行时发布资格。

## 实际边界

默认 Compose 不再定义 SQLBot 服务或基础地址；P5B 渲染后的服务、镜像和配置均不包含 `dataease/sqlbot`。生产配置校验拒绝通过开关、运行时验证标记或 `CANARY` / `SQLBOT_ENABLED` 查询模式重新启用 SQLBot。前端与运行状态明确展示“未包含在本版本”。

Gate Registry 保留 `SQLBOT_IMAGE_SECURITY` 的原始 `BLOCKED` 事实，不将 49 Critical / 802 High 伪造为已修复或通过。当前 v4 发布视图以 `applicable_to_release=false`、`blocking_scope=future_sqlbot_release` 和 `release_disposition=DEFERRED` 表达不适用；重新纳入必须进入独立后续版本并重新完成镜像安全与外部运行验收。

## 验证

```text
docker compose -p renewable-p5b-gate-closure \
  -f deploy/preproduction/compose.yaml \
  -f deploy/production-acceptance/p5b.override.yaml config --services

docker compose -p renewable-p5b-gate-closure \
  -f deploy/preproduction/compose.yaml \
  -f deploy/production-acceptance/p5b.override.yaml config --images
```

两份输出均不包含 SQLBot；完整渲染配置也不含 SQLBot 服务、镜像或 `SQLBOT_BASE_URL`。

## 回滚

仅在独立后续版本完成安全验收后，显式恢复服务定义、BOM/SBOM 组件和配置许可。不得只打开环境变量。
