# P5A 全镜像安全复扫

## 实际结论

`IMAGE_SECURITY=BLOCKED`。Trivy 0.70.0 使用本轮新下载的漏洞数据库和 Java 漏洞数据库，对 11 个运行/禁用角色对应的 8 个唯一 image ID 完成实际全镜像漏洞扫描；没有 ignore、severity 降级、结果删除或虚构 waiver。

按唯一 image ID 计为 50 个 Critical 实例、833 个 High 实例、24 个唯一 Critical 标识、641 个唯一 High 标识；按 11 个运行角色累计为 51 Critical、847 High，因为 backup 与 PostgreSQL 使用同一 image ID。无正式 waiver，任何 Critical/High 均未标为 ACCEPTED。

## 镜像与结果

| 角色 | 镜像/固定引用 | 内容 digest 或 image ID | C | H | 唯一 CVE/漏洞标识 | 状态 |
|---|---|---|---:|---:|---:|---|
| API | `renewable-p5a-api:5.0.0-p5a` | `sha256:42abcf52fdc4162f83bd4b188928e0d11a6b6afa9225eea6efff7dbd1a448205` | 0 | 0 | 1 | PASS |
| Web | `renewable-p5a-web:5.0.0-p5a` | `sha256:5364a6c917fd39d37b284cdbd055d17d0b3cc0628e66b29d327f8cc3954aa43b` | 0 | 0 | 0 | PASS |
| PostgreSQL | `renewable-p5a-postgres:16.14` | `sha256:486298eaa6cbd4830f8d1ae199e6dc9f33cee75a6bc178b0ee2d34c94b3041e3` | 1 | 14 | 39 | BLOCKED |
| Redis | `redis:7.4.10-alpine` | `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2` | 0 | 0 | 0 | PASS |
| Nginx | `nginx:1.31.3-alpine` | `sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752` | 0 | 0 | 0 | PASS |
| Keycloak | `renewable-p5a-keycloak:26.7.0` | `sha256:c2b643bb866cb4c297176d11e8c60065ec4628102a19256ffb65b5a8d0bfeafd` | 0 | 15 | 47 | BLOCKED |
| Vault | `hashicorp/vault:2.0.3` | `sha256:a296a888b118615dc01d5f1a6846e6d4a7277946caaed5b447008fff5fe06b54` | 0 | 3 | 6 | BLOCKED |
| SQLBot（禁用） | `dataease/sqlbot:v1.8.0` | `sha256:c4ca3acc34f0c63a64f3f3e7bb909760f17d184959635542278710144347d9e0` | 49 | 801 | 3595 | BLOCKED |
| 告警接收端 | `renewable-p5a-alert-receiver:5.0.0-p5a` | 与 API image ID 相同 | 0 | 0 | 1 | PASS |
| migration | `renewable-p5a-migration:5.0.0-p5a` | 与 API image ID 相同 | 0 | 0 | 1 | PASS |
| backup | `renewable-p5a-backup:16.14` | 与 PostgreSQL image ID 相同 | 1 | 14 | 39 | BLOCKED |

“唯一 CVE/漏洞标识”包含所有 severity，不等同于 C+H。详细 affected package、installed/fixed version、扫描完成时间、Trivy 版本、原始 JSON 文件名和原始证据 SHA-256 均在 `evidence/container-security/container-security-summary.json`。每个角色另有 `trivy-<role>.json`；相同 image ID 的角色使用相同字节证据，并由 `scan_execution=REUSED_IDENTICAL_IMAGE_ID` 明确标注，没有重复声称为独立内容扫描。

## PostgreSQL/backup 特殊说明

15 个严重实例均被 Trivy 归到 `usr/local/bin/gosu` 的 Go stdlib。实际运行镜像中该路径是指向 `/sbin/su-exec` 的 symlink，目标由 Alpine `su-exec-0.3-r0` 所有，14,152 字节，未发现 Go 版本字符串；这是本轮实机核验事实。但没有权威 CVE 不适用裁定或正式 waiver，因此没有将 1C/14H 改为 ACCEPTED，两个角色仍为 BLOCKED。

## 证据与限制

- 首次 API 扫描使用 Trivy 默认 5 分钟上限，真实失败为 `context deadline exceeded`；随后仅提高到 60 分钟，没有缩小扫描范围，最终全部完成。
- 漏洞数据库约 103 MiB；Keycloak 触发的 Java 数据库约 901 MiB，均为本轮实际下载。
- SQLBot 镜像约 4.51 GB，完整解析约 50 分钟；扫描没有启动 SQLBot 服务、外部模型或 Canary。
- 本地扫描值是当前 P5A 验收证据，不是生产 SLA 或生产安全批准。

原始扫描存在无 waiver 的 Critical/High，生产结论必须保持 `NO_GO`。
