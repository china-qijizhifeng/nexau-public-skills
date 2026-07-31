---
name: enterprise_basic
description: 当用户询问企业的身份、注册信息、地址、规模、行业分类或"专精特新"认定等级时使用此 Skill。这是最核心的主表——几乎所有涉及企业的查询都从这里开始。通过 credit_code 关联其他 enterprise_* 表。
---

# enterprise_basic — 企业基本信息

企业数据库的核心注册表。每家企业一行，以 `credit_code`（统一社会信用代码）为唯一标识。几乎所有按企业名称查询的问题都需要关联此表。

## 何时使用

- "某某企业注册在哪个区？"
- "海淀区有多少小型企业？"
- "列出制造业中所有的专精特新小巨人企业"
- "某某企业的注册资本是多少？"
- "某某企业属于哪个行业？"

如需联系方式请查 `enterprise_contact`，融资/上市信息请查 `enterprise_financing`，产品与知识产权请查 `enterprise_product`，产业链映射请查 `industry_enterprise` + `industry`。

## Schema

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 内部行 ID |
| `credit_code` | TEXT | **关联键。** 统一社会信用代码——所有 `enterprise_*` 表的共享标识 |
| `enterprise_name` | TEXT | 企业名称（测试数据中为 `测试企业_N`） |
| `declaration_year` | TEXT | 申报年度，如 `2021（新）`、`2024` |
| `data_batch` | TEXT | 内部批次标记（测试数据中为 `MOCK_BATCH_xxx`） |
| `sequence_number` | INTEGER | 批次内序号 |
| `register_district` | TEXT | 注册地所在区（如 `海淀区`、`黄浦区`、`南山区`） |
| `jurisdiction_district` | TEXT | 管辖区（可能与 `register_district` 不同） |
| `street` | TEXT | 街道 |
| `register_address` | TEXT | 注册地址（完整街道地址） |
| `correspondence_address` | TEXT | 通讯地址 |
| `postal_code` | TEXT | 邮编 |
| `register_date` | TEXT | 注册日期，ISO 日期格式 |
| `register_capital` | TEXT | 注册资本（万元）— **注意是 TEXT 类型**，数值比较时需用 `CAST(register_capital AS REAL)` |
| `register_capital_currency` | TEXT | 注册资本币种，几乎都是 `人民币` |
| `enterprise_scale` | TEXT | 取值：`微型`、`小型`、`中型`、`大型` |
| `enterprise_type` | TEXT | 取值：`民营`、`国有`、`合资`、`外资` |
| `foreign_capital_ratio` | REAL | 外资占比（0.0 – 1.0） |
| `industry_level1` – `industry_level4` | TEXT | 行业分类四级编码（如 `制造业` / `专用设备制造业` / `医疗仪器设备及器械制造` / `医疗诊断、监护及治疗设备制造`）。如需产业链视图请查 `industry_enterprise` |
| `main_product_service` | TEXT | 主营产品/服务简述 |
| `main_product_category` | TEXT | 主营产品类别 |
| `market_years` | INTEGER | 上市年限 |
| `enterprise_introduction` | TEXT | 企业简介（长文本） |
| `website` | TEXT | 企业官网 |
| `declaration_type` | TEXT | 申报类型，如 `更新`、`新增` |
| `zhuanjingtexin_level` | TEXT | 专精特新等级——取值：`专精特新中小企业`、`专精特新潜在"小巨人"企业`、`专精特新"小巨人"企业`，或 NULL |
| `financial_outlier_analysis` | INTEGER | 财务异常分析结果（测试数据中为 `无异常` / `轻微异常`） |
| `municipal_high_level_enterprise` | INTEGER | 是否市级高水平企业（0/1） |
| `created_at`、`updated_at` | TEXT | ISO 时间戳 |
| `unicorn_category`、`unicorn_year` | TEXT / INTEGER | 独角兽分类与入选年度 |
| `legal_entity_data` | TEXT (JSON) | 法人主体数据——JSON 格式，包含 `establish_year`、`employee_count`、`reg_no` |

## 常见取值

- `enterprise_scale`：`微型`、`小型`、`中型`、`大型`
- `enterprise_type`：`民营`、`国有`、`合资`、`外资`
- `zhuanjingtexin_level`：`专精特新中小企业` < `专精特新潜在"小巨人"企业` < `专精特新"小巨人"企业`
- `industry_level1` 示例：`制造业`、`信息传输、软件和信息技术服务业`、`科学研究和技术服务业`、`金融业`

## 示例查询

**海淀区注册资本最高的 10 家小型企业：**

```sql
SELECT enterprise_name,
       CAST(register_capital AS REAL) AS capital_wan,
       enterprise_scale
FROM enterprise_basic
WHERE register_district = '海淀区'
  AND enterprise_scale = '小型'
ORDER BY capital_wan DESC
LIMIT 10;
```

**按等级统计专精特新企业数量：**

```sql
SELECT zhuanjingtexin_level, COUNT(*) AS n
FROM enterprise_basic
WHERE zhuanjingtexin_level IS NOT NULL
GROUP BY zhuanjingtexin_level
ORDER BY n DESC;
```

**关联融资表查找已上市的制造业企业：**

```sql
SELECT b.enterprise_name, b.industry_level2, f.listing_status, f.stock_code
FROM enterprise_basic b
JOIN enterprise_financing f ON b.credit_code = f.credit_code
WHERE b.industry_level1 = '制造业'
  AND f.listing_status = '已上市';
```

## 注意事项

- `register_capital` 是 **TEXT 类型**，不是数值——排序或比较时必须用 `CAST(register_capital AS REAL)`。
- `industry_level1` 在测试数据中有些不规范（部分行带数字前缀如 `26 化学原料和化学制品制造业`）。如需模糊匹配请用 `LIKE '%制造%'`。
- `enterprise_name` 已脱敏——所有值形如 `测试企业_N`。如果用户按真实企业名查询，请说明这是测试数据。
