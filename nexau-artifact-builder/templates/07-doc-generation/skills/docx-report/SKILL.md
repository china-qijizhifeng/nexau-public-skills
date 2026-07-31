---
name: docx-report
description: |
  将结构化 JSON 数据渲染为标准 Word 文档（.docx）。支持公文（通知/报告/函件/请示/批复/纪要/决定等）
  和通用文档格式。当需要生成 Word 文档、输出公文、创建报告时使用此技能。
---

# docx-report — Word 文档生成技能

将结构化 JSON 数据渲染为标准 .docx 文件。支持公文和通用文档。

加载本技能后，`{skill_path}` 指 `LoadSkill("docx-report")` 返回的技能文件夹路径。

## 首次使用

确保脚本有执行权限：

```bash
chmod +x {skill_path}/scripts/build
```

第一次 `render` 会自动检测并编译 .NET 渲染引擎（约 2-3 秒），输出 `✅ 引擎编译完成` 后开始渲染。后续调用直接使用缓存，无需重复编译。

> 💡 也可以用 `{skill_path}/scripts/build warmup` 提前编译，但不是必须的。

## 生成文档

```bash
{skill_path}/scripts/build render <type> <input.json> <output.docx>
```

示例：

```bash
{skill_path}/scripts/build render notice /tmp/data.json /tmp/output.docx
```

脚本会自动：
1. **校验 JSON**（检查 required 字段 + section 结构），格式不对立即报错
2. 调用渲染引擎生成 .docx
3. 输出 `✅ 生成完成：/tmp/output.docx (XXXX bytes)`

## ⚠️ 关键规则

### 1. 只用 `build render`，禁止 `dotnet run`

```bash
# ✅ 正确
{skill_path}/scripts/build render notice data.json output.docx

# ❌ 错误 → CS8802 编译冲突（多个 top-level statements 文件）
cd {skill_path}/templates && dotnet run --project GovDoc.csproj ...
```

`build render` 内部自动隔离编译（只编译 GovDocEngine.cs），避免 CS8802。

### 2. JSON 的 section 结构必须用 heading + level + paragraphs

```json
{
  "heading": "一、总体要求",
  "level": 1,
  "paragraphs": ["第一段正文……", "第二段正文……"],
  "children": [
    { "heading": "（一）目标", "level": 2, "paragraphs": ["……"] }
  ]
}
```

| ❌ 错误字段名 | ✅ 正确字段名 | 说明 |
|-------------|-------------|------|
| `title` | `heading` | section 标题 |
| `content` | `paragraphs` | 正文段落，且必须是**字符串数组** |
| 缺少 level | `level: 1/2/3` | 必填：1=黑体 2=楷体 3=仿宋加粗 |
| `paragraphs: "文字"` | `paragraphs: ["文字"]` | 必须是数组，不是字符串 |

### 3. 输出文件名用英文

```bash
# ✅ /tmp/output_notice.docx
# ❌ /tmp/关于XX的通知.docx（中文在 Linux shell 下可能乱码）
```

## 可用模板类型

查看完整清单：

```bash
{skill_path}/scripts/build templates
```

常用类型及其 required 字段：

| type | 适用公文 | required 字段 |
|------|---------|--------------|
| `notice` | 通知/通报/公告/意见 | type, gov_org, doc_num, title, send_to, date, sections |
| `report` | 报告/公报/议案 | type, title, org, date, sections |
| `letter` | 函件 | type, gov_org, doc_num, title, send_to, date, sections |
| `resolution` | 请示/批复 | type, subtype, gov_org, doc_num, title, send_to, date, sections |
| `minutes` | 会议纪要 | type, gov_org, doc_num, title, meeting_info, agenda_items, date |
| `decision` | 决定/命令 | type, gov_org, doc_num, title, date |
| `generic` | 通用文档 | type, title, sections |

⚠️ 不同模板的 required 字段不同。按 `notice` 构造的 JSON **不能**用 `generic` 模板渲染（字段不匹配）。

## 其他命令

```bash
{skill_path}/scripts/build templates       # 查看模板清单
{skill_path}/scripts/build check-index     # 校验模板索引完整性
{skill_path}/scripts/build batch <type> <input_dir> <output_dir>  # 批量生成
{skill_path}/scripts/build diff <type> <old.json> <new.json> <output.docx>  # 版本对比
```

## 常见错误速查

| 错误现象 | 原因 | 解决方法 |
|---------|------|---------|
| 首次 render 多花几秒 + 输出编译日志 | 正常：引擎首次编译 | 无需处理，编译完自动渲染 |
| 首次 render exit code 1 | 编译失败（环境问题） | 看 `2>&1` 的完整输出定位错误（**不要接 `\| tail`**，会掩盖真实退出码并截断），再重试一次 |
| 首次 render 卡在 `dotnet restore` / NuGet 取包失败 | 沙箱出网被拦 | 属环境问题；需放通 NuGet 出网，或离线环境预置 NuGet 包 |
| `CS8802: Only one compilation unit can have top-level statements` | 直接用了 `dotnet run` | 改用 `build render` |
| `❌ 未知模板类型 'xxx'` | type 拼写错误或不存在 | 执行 `build templates` 查看可用类型 |
| `❌ JSON 校验失败` + 详细错误列表 | JSON 字段名/结构不匹配 | 按错误提示逐条修正 |
| Word 文件 < 3KB | JSON 数据结构对了但内容为空 | 检查 paragraphs 数组是否有内容 |
| `Permission denied` (exit 126) | 脚本缺少执行权限 | `chmod +x {skill_path}/scripts/build` |
| 中文文件名乱码 | Linux shell 编码 | 输出文件名用英文 |

## Schema 参考文件

详细 schema 定义在技能文件夹的 `schemas/` 目录下：

- `schemas/base.json` — 公共定义（**section、policy_ref、table** 等结构在这里）
- `schemas/govdoc/<type>.json` — 各公文类型的字段定义
- `schemas/general/generic.json` — 通用文档

⚠️ 各类型 schema 中的 `sections` 字段通过 `$ref` 引用 `base.json#/definitions/section`。
构造 JSON 时以上面「section 结构」为准。

## references/ 目录导航

技能文件夹的 `references/` 下是**法规与格式标准原文（要点整理版）**，不是运行时必读项。
日常构造 JSON 只看上面的字段对照表即可；只有需要核对某个排版参数、判断文种是否用对、或向用户解释「为什么这里必须这么排」时，才用 `read_file` 按需读取，**不要整篇加载**。

| 文件 | 内容 | 何时查阅 |
|------|------|---------|
| `references/GB-T-9704-2012-党政机关公文格式.md` | GB/T 9704-2012 要点：纸张幅面、版头/主体/版记各要素的编排规则 | 核对字号字体、页边距、发文机关标志位置、页码或版记排法等**排版细节** |
| `references/中办发〔2012〕14号-党政机关公文处理工作条例.md` | 工作条例要点：15 种法定文种的定义与适用范围、行文规则、公文办理流程 | 判定**该用哪个文种**、确认行文方向（上行/下行/平行） |

先读 `references/INDEX.md` 可拿到这两份文件的完整速览与分工判据（「这份文件长什么样」查格式标准，「这件事该发什么文」查工作条例）。
