# Dataset Release Contract v0.1

状态：**目标合同已冻结；当前只实现暂存、质量、审批和不可变场站快照**。

## 核心对象

- `DatasetDefinition`：逻辑数据集、所有者、数据分类和源选择。
- `DatasetVersion`：不可变的 schema、mapping_version、source_version、质量结果、checksum、行数与时间范围。
- `ActivationPointer`：每个 tenant/workspace/scenario/dataset 唯一 ACTIVE 指针。
- `ReleaseAudit`：提交、审批、发布、激活、回滚的操作者、原因、时间与 run_id。

## 状态机

`DRAFT → INGESTED → QUALITY_PASSED|QUALITY_FAILED → PENDING_APPROVAL → APPROVED|REJECTED → PUBLISHED → ACTIVE → RETIRED`

- 发布只创建不可变版本；激活单独执行。
- 激活必须在单事务中锁定当前指针、验证权限/场景/语义兼容性并切换指针。
- 任一正式消费者只能通过 `ActivationPointer` 解析版本，禁止各自“取最新”。
- 回滚是把指针切回仍兼容的已发布版本，不删除版本和审计。
- 失败审计必须在业务事务回滚后写入，不能提交失败事务中的脏状态。

## 当前差距

`PublishedStationSnapshot` 已满足部分不可变发布语义，但没有通用 `DatasetVersion`、mapping_version、ACTIVE 指针、激活/回滚 API；只有场站分析在严格覆盖条件下读取快照，其他消费者仍读事实表。

## 验收

并发激活只能成功一次；所有看板/ChatBI/诊断/报告在同一请求上下文解析同一版本；失败发布不改变审批状态；回滚不丢版本；权限和场景不匹配必须拒绝。

