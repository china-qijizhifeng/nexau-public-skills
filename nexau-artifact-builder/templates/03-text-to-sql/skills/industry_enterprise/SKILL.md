---
name: industry_enterprise
description: 当用户需要查看企业与产业链节点的映射关系时使用此 Skill——即"某个产业链节点下有哪些企业"或"某家企业参与了哪些产业链节点"。这是 `enterprise_basic` 和 `industry` 之间的关联表。
---

# industry_enterprise — 企业 ↔ 产业链节点映射

多对多关联表，将企业（`enterprise_basic.credit_code`）链接到产业链节点（`industry.id`）。一家企业可映射到多个节点；一个节点通常关联多家企业。

如需按企业级别的行业分类查询（四个 `industry_level1..4` 列），直接使用 `enterprise_basic`——更快且不需要关联。当你需要**产业链视图**（某条链的上游/中游/下游）时才使用此表。

## 何时使用

- "AI 产业链（chain_id 45）下有哪些企业？"
- "AI 产业链每个上游节点各有多少企业？"
- "某某企业参与了哪些产业链节点？"
- "哪些企业同时出现在上游和下游？"

## Schema

| 列名 | 类型 | 说明 |
|---|---|---|
| `industry_id` | INTEGER PK | 外键，关联 `industry.id` |
| `credit_code` | TEXT PK | 外键，关联 `enterprise_basic.credit_code` |
| `chain_id` | INTEGER | 去范式化的产业链 ID（与 `industry.chain_id` 一致） |
| `industry_path` | TEXT | 祖先节点 ID 的 JSON 数组——从 `industry.path` 复制，用于快速过滤 |
| `created_at` | TEXT | 时间戳 |

复合主键为 `(industry_id, credit_code)`。

## 示例查询

**产业链 45 中所有企业及其节点名称：**

```sql
SELECT b.enterprise_name, i.name AS chain_node, i.chain_position
FROM industry_enterprise ie
JOIN industry i         ON i.id = ie.industry_id
JOIN enterprise_basic b ON b.credit_code = ie.credit_code
WHERE ie.chain_id = 45
ORDER BY i.depth, i.sort_order;
```

**AI 产业链中每个节点的企业数量：**

```sql
SELECT i.name, COUNT(*) AS n_enterprises
FROM industry_enterprise ie
JOIN industry i ON i.id = ie.industry_id
WHERE ie.chain_id = 45
GROUP BY ie.industry_id
ORDER BY n_enterprises DESC;
```

**查看某家企业参与的所有产业链节点：**

```sql
SELECT i.chain_id, i.name, i.chain_position, i.depth
FROM industry_enterprise ie
JOIN industry i ON i.id = ie.industry_id
WHERE ie.credit_code = 'MOCKCREDIT0000000034';
```

## 注意事项

- `industry_path` 是以 TEXT 存储的 JSON 数组（如 `[3821, 3836, 3837]`）。可用 `LIKE '%, 3836,%'` 做快速子树过滤。
- `chain_id` 已去范式化——与通过 `industry` 表关联得到的值一致。只需按链过滤时可直接使用，省去一次关联。
- 有些企业在此表中没有记录——如需包含所有企业请用 `LEFT JOIN`。
