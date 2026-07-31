---
name: enterprise_contact
description: 当用户询问企业联系方式时使用此 Skill——包括法人、总经理、主要联系人的姓名/职务/电话/邮箱，以及控股股东、实际控制人等信息。通过 credit_code 关联 enterprise_basic。
---

# enterprise_contact — 企业联系人信息

每家企业一行，包含所有联系方式和股权控制字段。通过 `credit_code` 关联 `enterprise_basic`。

> **脱敏说明：** 测试数据中所有个人身份字段已脱敏：姓名显示为 `REDACTED_N`，电话为 `138NNNNNNNN`，邮箱为 `userN@example.com`，股东字段为 NULL。数据缺失是脱敏导致的，并非真实情况。

## 何时使用

- "某某企业的法人是谁？"
- "查一下某某企业的联系电话"
- "哪些企业的实际控制人是同一个人？"
- "找出法人兼任总经理的企业"

## Schema

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 内部 ID |
| `credit_code` | TEXT | 关联键，关联 `enterprise_basic` |
| `legal_person_name` | TEXT | 法人姓名（已脱敏） |
| `legal_person_position` | TEXT | 法人职务，如 `董事长兼首席执行官` |
| `legal_person_phone` | TEXT | 法人座机（已脱敏） |
| `legal_person_mobile` | TEXT | 法人手机（已脱敏） |
| `manager_name` | TEXT | 总经理姓名（已脱敏） |
| `manager_position` | TEXT | 总经理职务 |
| `manager_phone` | TEXT | 总经理座机 |
| `manager_mobile` | TEXT | 总经理手机 |
| `contact_name` | TEXT | 主要联系人姓名（已脱敏） |
| `contact_position` | TEXT | 联系人职务 |
| `contact_phone` | TEXT | 联系人座机 |
| `contact_mobile` | TEXT | 联系人手机 |
| `fax` | TEXT | 传真 |
| `email` | TEXT | 联系邮箱 |
| `controlling_shareholder` | TEXT | 控股股东（已脱敏） |
| `actual_controller` | TEXT | 实际控制人（已脱敏） |
| `actual_controller_nationality` | TEXT | 实控人国籍 |
| `created_at`、`updated_at` | TEXT | 时间戳 |

## 示例查询

**查看前 10 家企业的法人职务：**

```sql
SELECT b.enterprise_name, c.legal_person_position
FROM enterprise_contact c
JOIN enterprise_basic b ON b.credit_code = c.credit_code
LIMIT 10;
```

**法人兼任总经理的企业：**

```sql
SELECT b.enterprise_name
FROM enterprise_contact c
JOIN enterprise_basic b ON b.credit_code = c.credit_code
WHERE c.legal_person_name = c.manager_name
  AND c.legal_person_name IS NOT NULL;
```
