---
name: industry
description: 当用户询问产业链结构、某个行业节点的位置（上游/中游/下游）、行业之间的层级关系、或需要遍历产业链树时使用此 Skill。配合 `industry_enterprise` 可将企业映射到产业链节点上。
---

# industry — 产业链节点

一张层级结构的参考表，描述产业链。每行是产业链中的一个节点（如"AI 上游 — 算力 — GPU 集群"），树结构通过 `parent_id` 和物化路径列 `path` 编码。节点所属的产业链由 `chain_id` 标识。

如需查找某个节点下有哪些企业，请关联 `industry_enterprise`（通过 `industry_id`）。

## 何时使用

- "AI 产业链的结构是什么样的？" → 按 `chain_id` 过滤 `industry` 表
- "某某行业在产业链中属于什么位置？" → 按 `name` 查找
- "列出 AI 产业链的所有末端节点（下游应用）" → 按 `depth` 和 `chain_position` 过滤
- "GPU 集群节点下有哪些企业？" → 关联 `industry_enterprise`
- 如需按企业行级的行业分类查询，优先使用 `enterprise_basic.industry_level1..4`（已去范式化，更快）

## Schema

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 内部节点 ID——被 `industry_enterprise.industry_id` 引用 |
| `chain_id` | INTEGER | 节点所属的产业链 ID（如 `45` = AI 产业链） |
| `parent_id` | INTEGER | 同一产业链中的父节点 ID。根节点为 NULL |
| `name` | TEXT | 节点名称（如 `上游（基础要素与基础设施）`） |
| `description` | TEXT | 节点的详细描述 |
| `path` | TEXT | 物化祖先路径，JSON 数组格式（如 `[3821, 3836, 3837]`）。可用 `LIKE` 做快速子树查询 |
| `depth` | INTEGER | 树深度，0 = 根节点 |
| `sort_order` | INTEGER | 同级节点的排序序号 |
| `chain_position` | TEXT | 取值：`up`（上游）、`mid`（中游）、`down`（下游）——仅在顶层节点上有值 |
| `icon` | TEXT | UI 图标提示（如 `arrow-up-from-line`） |
| `created_at`、`updated_at` | TEXT | ISO 时间戳 |

## 常见取值

- `depth`：`0`（产业链根节点，约 2 行）、`1`（上/中/下游，约 6 行）、`2`（子分类，占大多数）
- `chain_position`：`up`、`mid`、`down`（仅 depth=1 的节点有值）

## 示例查询

**查看所有产业链的顶层结构：**

```sql
SELECT chain_id, depth, name, chain_position
FROM industry
WHERE depth <= 1
ORDER BY chain_id, depth, sort_order;
```

**AI 产业链（chain_id=45）的所有叶子节点：**

```sql
SELECT id, name, depth, path
FROM industry
WHERE chain_id = 45
  AND id NOT IN (SELECT DISTINCT parent_id FROM industry WHERE parent_id IS NOT NULL)
ORDER BY depth, sort_order;
```

**查找 AI 产业链所有"上游"节点对应的企业：**

```sql
SELECT b.enterprise_name, i.name AS industry_node
FROM industry i
JOIN industry_enterprise ie ON ie.industry_id = i.id
JOIN enterprise_basic b     ON b.credit_code = ie.credit_code
WHERE i.chain_id = 45
  AND i.chain_position = 'up';
```

**通过 `path` 从某节点回溯到根节点：**

```sql
SELECT id, depth, name
FROM industry
WHERE id IN (3821, 3836, 3837)   -- 来自子节点 path 列中的 ID
ORDER BY depth;
```

## 注意事项

- `path` 是以 TEXT 存储的 JSON 数组。SQLite 有 `json_each()` 可展开，但简单的子树过滤用 `LIKE '%, 3836,%'` 通常就够了。
- `chain_position` 仅在 depth=1 的节点上有值。查询叶子节点时不要用它过滤。
- `parent_id` 根节点为 NULL——请用 `IS NULL`，不要用 `= 0`。
