---
name: enterprise_financing
description: 当用户询问企业融资情况时使用此 Skill——包括银行贷款、股权融资、估值、上市状态、拟上市地点、未来融资需求等。通过 credit_code 关联 enterprise_basic。
---

# enterprise_financing — 企业融资与上市

每家企业一行，汇总银行贷款历史、最近股权融资、估值、上市状态及进度。通过 `credit_code` 关联 `enterprise_basic`。

## 何时使用

- "某某企业有没有申请过银行贷款？"
- "某某企业最近的估值是多少？"
- "列出所有在北交所已上市的企业"
- "哪些企业计划在未来 12 个月内融资超过 10000 万？"
- "制造业企业的平均信贷满足率是多少？"

## Schema

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 内部 ID |
| `credit_code` | TEXT | 关联键 |
| `applied_bank_loan` | INTEGER | 是否申请过银行贷款（0/1） |
| `credit_satisfaction_rate` | REAL | 信贷满足率（0.0 – 1.0） |
| `loan_purpose` | TEXT | 贷款用途，取值：`流动资金`、`设备采购`、`研发投入`、`扩大产能` |
| `next_financing_plan` | TEXT | 下一轮融资计划，取值：`暂无`、`12个月内`、`24个月内` |
| `next_financing_demand` | REAL | 下一轮融资需求金额（万元） |
| `next_financing_method` | TEXT | 融资方式，取值：`股权融资`、`债权融资`、`可转债` |
| `recent_equity_financing` | REAL | 最近一轮股权融资金额（万元） |
| `recent_valuation` | REAL | 最近估值（万元） |
| `listing_status` | TEXT | 上市状态，取值：`未上市`、`新三板`、`已上市`、`拟上市` |
| `stock_code` | TEXT | 股票代码（未上市企业为空） |
| `listing_progress` | TEXT | 上市进度，取值：`无`、`辅导期`、`申报中` |
| `planned_listing_location` | TEXT | 拟上市地点，取值：`无`、`上交所`、`深交所`、`北交所`、`港交所` |
| `overseas_listing` | TEXT | 是否海外上市：`是` / `否` |
| `created_at`、`updated_at` | TEXT | 时间戳 |

## 示例查询

**估值最高的企业：**

```sql
SELECT b.enterprise_name, f.recent_valuation, f.listing_status
FROM enterprise_financing f
JOIN enterprise_basic b ON b.credit_code = f.credit_code
ORDER BY f.recent_valuation DESC
LIMIT 10;
```

**各行业平均融资需求：**

```sql
SELECT b.industry_level1, AVG(f.next_financing_demand) AS avg_demand
FROM enterprise_financing f
JOIN enterprise_basic b ON b.credit_code = f.credit_code
WHERE f.next_financing_plan != '暂无'
GROUP BY b.industry_level1
ORDER BY avg_demand DESC;
```

**按交易所统计已上市企业数量：**

```sql
SELECT planned_listing_location, COUNT(*) AS n
FROM enterprise_financing
WHERE listing_status = '已上市'
GROUP BY planned_listing_location;
```
