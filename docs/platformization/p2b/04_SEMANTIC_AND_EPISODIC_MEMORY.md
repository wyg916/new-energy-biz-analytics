# Semantic 与 Episodic Memory

## Semantic Memory

Semantic Memory 只保存稳定、复用价值明确的偏好和术语纠正。写入使用稳定键、
duplicate hash、版本和 conflict group；未经用户明确确认的模型推断停留在候选或被
拒绝，不能进入 ACTIVE。

纠正不会静默覆盖。新旧来源、时间和冲突组被保留，旧版本转为 SUPERSEDED 后新版本
才可 ACTIVE。实时收入、订单金额、候选根因、SQLBot Shadow、正式指标定义副本和
Secret 均禁止写入。

## Episodic Memory

成功的 analysis run 保存原始/标准化问题、场景与版本绑定、引擎、Query Plan、实际
SQL、结果摘要与不可逆哈希、RAG 证据、最终回答、Skill 步骤、错误、反馈、采纳状态、
成本和时延。完整明细结果不重复保存。

Episodic 服务支持按 run_id 回放，以及按问题、场景、用户和结果检索。Bad Case 可生成
评测候选；SQLBot Shadow 只可标记为 Shadow 评测证据，禁止作为最终事实或 Semantic
输入。
