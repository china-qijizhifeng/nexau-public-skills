---
name: users
description: 仅当用户明确询问平台用户（登录账号、SSO ID、角色）时使用此 Skill。此表与企业表无关，不应与其关联。大多数关于"用户"的问题实际上指的是企业而非平台用户——如有歧义请先和用户确认。
---

# users — 平台用户账号

数据平台自身的系统用户——不是企业。仅在用户询问登录账号、SSO、平台角色时使用。如果用户说"用户"但没有上下文，他们几乎总是指企业（`enterprise_basic`）；请先确认再操作。

## 何时使用

- "平台有多少管理员？"
- "列出所有 admin 角色的用户"
- "某某用户是什么时候创建的？"

**不要在以下场景使用此 Skill：** 用户询问企业、客户、联系人或任何业务领域的"用户"——那些数据在 `enterprise_basic` 和 `enterprise_contact` 中。

## Schema

| 列名 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 内部 ID |
| `sso_user_id` | TEXT | SSO 主体 ID（测试数据中已脱敏） |
| `display_name` | TEXT | 显示名（已脱敏） |
| `email` | TEXT | 邮箱（测试数据中为 `userN@example.com`） |
| `role` | TEXT | 角色，取值：`user`、`admin` |
| `created_at`、`updated_at` | TEXT | 时间戳 |
| `sso_raw_data` | TEXT | 原始 SSO 声明（已脱敏为空） |
| `password_hash` | TEXT | 本地密码哈希（已脱敏） |
| `username` | TEXT | 本地用户名（已脱敏） |

## 示例查询

**按角色统计用户数量：**

```sql
SELECT role, COUNT(*) AS n FROM users GROUP BY role;
```

**最近创建的账号：**

```sql
SELECT id, role, created_at FROM users ORDER BY created_at DESC LIMIT 10;
```

## 隐私说明

此表中所有个人身份字段均已脱敏。请勿假设这些值代表真实用户。
