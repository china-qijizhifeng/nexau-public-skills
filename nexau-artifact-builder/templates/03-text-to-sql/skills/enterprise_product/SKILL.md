---
name: enterprise_product
description: 当用户询问企业产品时使用此 Skill——包括产品名称、产品营收、日产能、关联的知识产权（专利）等。每家企业可有多个产品，通过 credit_code 关联 enterprise_basic。
---

# enterprise_product — 企业产品与知识产权

每行代表一个（企业, 产品）对。一家企业可以有多个产品，通过 `product_index` 区分。每行还列出最多三个关联的知识产权/专利名称。

## 何时使用

- "某某企业生产什么产品？"
- "营收最高的 10 个产品"
- "哪些企业有 3 个以上产品？"
- "按行业统计产品总营收"
- "找出包含某关键词的所有专利"

## Schema

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 内部 ID |
| `credit_code` | TEXT | 关联键，关联 `enterprise_basic` |
| `product_index` | INTEGER | 企业内的产品序号（1, 2, 3, …） |
| `product_name` | TEXT | 产品名称（测试数据中为 `产品_N`） |
| `product_revenue` | REAL | 产品营收（万元） |
| `daily_capacity` | TEXT | 日产能——数值以 TEXT 存储 |
| `capacity_unit` | TEXT | 产能单位，取值：`件/日`、`吨/日`、`台/日`、`套/日` |
| `ip_name_1` | TEXT | 关联知识产权 1 名称 |
| `ip_name_2` | TEXT | 关联知识产权 2 名称 |
| `ip_name_3` | TEXT | 关联知识产权 3 名称 |
| `created_at`、`updated_at` | TEXT | 时间戳 |

## 示例查询

**营收最高的 10 个产品及其所属企业：**

```sql
SELECT b.enterprise_name, p.product_name, p.product_revenue
FROM enterprise_product p
JOIN enterprise_basic b ON b.credit_code = p.credit_code
ORDER BY p.product_revenue DESC
LIMIT 10;
```

**拥有 3 个及以上产品的企业：**

```sql
SELECT b.enterprise_name, COUNT(*) AS n_products
FROM enterprise_product p
JOIN enterprise_basic b ON b.credit_code = p.credit_code
GROUP BY p.credit_code
HAVING n_products >= 3
ORDER BY n_products DESC;
```

**按行业统计产品总营收：**

```sql
SELECT b.industry_level1, SUM(p.product_revenue) AS total_revenue
FROM enterprise_product p
JOIN enterprise_basic b ON b.credit_code = p.credit_code
GROUP BY b.industry_level1
ORDER BY total_revenue DESC;
```

## 注意事项

- `daily_capacity` 是 TEXT 类型——做数值运算时需用 `CAST(daily_capacity AS REAL)`。
- 专利名称已脱敏，不要假设为真实的知识产权数据。
- 有些企业在此表中没有记录——如需包含所有企业请用 `LEFT JOIN`。
