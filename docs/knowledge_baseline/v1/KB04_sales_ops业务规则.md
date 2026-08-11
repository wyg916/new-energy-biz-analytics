# KB04｜sales_ops 业务规则

> 知识域：`business_rule`  
> 场景：`sales_ops`  
> 版本：`1.0.0`

## 1. 场景定位

`sales_ops` 是第二业务场景，用于验证同一数据接入、语义模型、ChatBI、RAG、权限和查询治理框架对销售经营分析的复用能力。

DATA-4.1 活动公开源为 UCI Online Retail。

## 2. 当前活动数据范围

当前运行：

`DATA41-UCI-ONLINE-RETAIL-352-V1`

当前快照：

- 源工作簿总记录：541,909；
- 当前确定性样本入库：27,095；
- 选取规则：按原工作簿顺序每 20 个数据行保留 1 行，并保留 `source_row_number`；
- 时间：2010-12-01 至 2011-12-09；
- 当前样本覆盖完整时间周期，但不是源工作簿全量副本。

具体问数必须查询当前 ACTIVE 数据集，不能用上述行数作为实时经营值。

## 3. 源字段映射

| UCI 源字段 | staging | core | 规则 |
|---|---|---|---|
| `InvoiceNo` | `invoice_no` | `sales_order.order_id` | 稳定命名空间键；`C` 前缀识别取消/退款语义 |
| `StockCode` | `stock_code` | `sales_product.product_id` | 稳定键 |
| `Description` | `description` | `sales_product.product_name` | 仅按 Schema 长度裁切 |
| `Quantity` | `quantity` | `sales_order_item.quantity` | 核心数量取绝对值；源符号保留用于取消语义 |
| `InvoiceDate` | `invoice_time` | `sales_order.order_date` | 源时区未明确，技术存储统一标准化 |
| `UnitPrice` | `unit_price` | `sales_order_item.unit_price` | 不做币种转换 |
| `CustomerID` | `customer_id` | `sales_customer.customer_id` | 伪名稳定键；缺失 ID 限定在发票范围 |
| `Country` | `country` | `sales_region.region_name` | 直接映射 |

## 4. 有效订单规则

业务统计只使用符合活动语义版本定义的有效订单。

历史场景合同将 `completed` 与 `refunded` 视为经营统计范围内订单；取消或其他无效状态不进入正常订单、收入、客户和销量口径。退款金额通过独立字段进入净收入和退款分析。

最终状态枚举与识别规则以当前 ACTIVE `sales_ops` 语义模型为准。

## 5. 收入规则

### 5.1 行级毛额

基础关系：

`gross_amount = quantity × unit_price`

退款/取消行必须依据状态规则分离处理，不能直接把负数量与正常销售混合后无解释聚合。

### 5.2 净收入

`net_revenue` 表示折扣和退款后的经营收入字段。

当前 UCI `UnitPrice` 不做币种转换，因此：

- 不得与 charging_ops 的金额直接跨场景相加；
- 如需要跨场景汇总，必须显式增加币种映射、汇率版本和换算时间。

## 6. 成本与毛利

UCI 源数据不提供商品成本。

当前 DATA-4.1 为保持毛利分析链路，登记了：

`cost_amount = 非退款净收入 × 70%`

这是明确的 `BUSINESS_ASSUMPTION`，不是源数据观测值。

因此：

`gross_profit = net_revenue - cost_amount`

销售毛利相关回答必须能解释成本规则来源，不得描述成 UCI 原始成本。

## 7. 销售人员

UCI 源没有销售人员字段。若当前 Schema 需要 `salesperson` 外键，占位实体必须保持“源未提供”的派生分类，不能生成具体员工身份并声称来自源数据。

## 8. 用户/客户保护

`CustomerID`：

- 只保存伪名化稳定键；
- 不恢复姓名、联系方式或其他身份信息；
- 普通 ChatBI/RAG 不返回客户级敏感明细；
- 缺失 CustomerID 只在发票作用域生成替代键，避免跨发票错误合并身份。

## 9. 支持的经营分析维度

历史 `sales_ops` 场景支持：

- date
- region
- channel
- product
- category
- customer_segment
- salesperson
- organization

实际查询必须使用当前发布语义模型允许的维度和 Join。

## 10. 典型指标

现有场景提供的主要经营指标包括：

- `sales_revenue`
- `order_count`
- `customer_count`
- `average_order_value`
- `sales_quantity`
- `gross_profit`
- `gross_margin`
- `refund_amount`
- `refund_rate`
- `new_customer_count`
- `repeat_customer_count`
- `channel_contribution`

具体公式、维度兼容性和状态必须从当前 ACTIVE Semantic Model / `metric_definition` 读取。

## 11. 场景隔离

- `charging_ops` 与 `sales_ops` 可同时 ACTIVE；
- 请求场景、QueryContext、DatasetVersion、SemanticModelVersion 必须一致；
- 跨场景调用返回场景不匹配或拒绝；
- 不允许根据同名字段自动跨场景 Join。
