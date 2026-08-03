# PostgreSQL 16.14 镜像安全关闭

## 原始发现

P5A 镜像 `renewable-p5a-postgres:16.14` 为 `1 Critical / 14 High`。15 条均来自基础层 `/usr/local/bin/gosu` 内 Go stdlib `v1.24.6`；Critical 为 `CVE-2025-68121`，扫描器给出的修复版本为 `1.24.13 / 1.25.7 / 1.26.0-rc.3`。最终文件系统虽已把 `gosu` 指向 C 实现 `su-exec`，旧二进制仍可从父层恢复，因此原门禁结论有效。

## 处置

`deploy/preproduction/postgres.Dockerfile` 保持官方 PostgreSQL `16.14`、数据目录和 entrypoint 合同，先用 `su-exec` 替代 `gosu`，再通过 `FROM scratch` 复制合并后的最终文件系统。这样不改变数据库主版本或业务 SQL，同时不再发布含旧 Go 二进制的父层。

最终本地镜像：

- reference：`renewable-p5b-postgres:16.14-hardened`；
- image ID：`sha256:487cefedff04f3c7f6304e554cc14bf7220a23d513978a51b2d012c40d0cf882`；
- PostgreSQL：`16.14`；
- `/usr/local/bin/gosu`：链接至 `/sbin/su-exec`。

## 复扫

Trivy 0.70.0 于 `2026-08-03T13:26:52Z` 完整扫描最终镜像文件系统：`0 Critical / 0 High / 0 Medium / 0 Low / 0 Unknown`。未使用 ignorefile、severity 降级或 waiver。

- 原始 JSON：`evidence/container-security/trivy-postgresql.json`；
- JSON SHA-256：`86df064e259b0e27dfbda8dea10f3f2ce7031373700cbdbbca17c7645749c278`。

数据卷、WAL、迁移、固定数据量、业务哈希、备份恢复和故障恢复在 P5B 独立栈与最终回滚演练中复验后，才关闭 PostgreSQL 运行兼容门禁。
