# 容量、降级与故障恢复

## 隔离容量测试

测试环境为本机 Docker 隔离栈，40 个请求、并发数 4、每请求工作量 8，错误数 0。结果仅用于复现和回归，不是生产 SLA。

| 路径 | P50 (ms) | P95 (ms) | 错误率 |
| --- | ---: | ---: | ---: |
| 身份中间件 | 142.036 | 184.709 | 0% |
| Policy Engine | 163.736 | 204.088 | 0% |
| Memory 查询 | 729.383 | 1360.462 | 0% |
| Skill 执行 | 5474.118 | 5662.203 | 0% |
| 审计拒绝写入 | 156.860 | 251.374 | 0% |

## 故障与恢复

- Redis 停止时存活探针 200、就绪探针 503；恢复后就绪 200。
- PostgreSQL 停止时存活探针 200、就绪探针 503；恢复后就绪 200，核心数据量不变。
- RAG 索引不可用时按受控降级返回，不绕过权限，也不制造引用。
- Secret Provider 缺失时 fail-closed，不发起外部请求。
- SQLBot 不可用时 DeterministicEngine 主答案成功，Shadow 故障不外溢。
- API 重启前后 principals/roles/policies/retention 为 3/3/1/1，charging/sales 为 300000/50000，证明引导幂等。

## 迁移与备份

- 专用临时数据库完成 `base → head → base → head`，最终 revision 为 `p3_0001`。
- `pg_dump`/restore 演练通过；dump 16,715,044 bytes，SHA-256 为 `7c5c2e8dcdbc776d60649cd36d38c1107650eb16c8f044bd29612502187d8466`。
- 恢复库核对 charging sessions 300000、sales orders 50000 后删除临时恢复数据库；未删除 PostgreSQL 或 Redis 卷。

固定种子模拟数据期间为 2025-01-01 至 2026-06-30；每个业务响应继续包含 `analysis_run_id`/`run_id` 追溯位置。
