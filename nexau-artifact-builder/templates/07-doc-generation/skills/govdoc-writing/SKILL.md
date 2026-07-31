---
name: govdoc-writing
description: |
  公文写作规范与模板技能。包含各类公文（通知、报告、请示、批复、函件、纪要、决定等）的
  写作格式要求、行文规范、模板示例和常用公文用语。当需要撰写公文、确认公文格式、
  选择公文类型时使用此技能。
---

# 公文写作规范

依据《党政机关公文处理工作条例》（中办发〔2012〕14号）和 GB/T 9704-2012《党政机关公文格式》，提供公文写作所需的全部规范和模板参考。

## 公文类型速查

| 文种 | 行文方向 | 适用场景 | docx-report type | 结尾语 |
|------|---------|---------|-----------------|--------|
| 通知 | 下行 | 传达要求、部署工作、告知事项 | notice | 特此通知。 |
| 通报 | 下行 | 表彰先进、批评错误、传达情况 | notice | 特此通报。 |
| 报告 | 上行 | 汇报工作、反映情况、答复询问 | report | 特此报告。 |
| 请示 | 上行 | 请求上级指示、批准 | resolution (subtype: 请示) | 妥否，请批示。 |
| 批复 | 下行 | 答复下级请示 | resolution (subtype: 批复) | 此复。 |
| 函 | 平行 | 不相隶属机关商洽工作、询问答复 | letter | 盼复。/ 此复。 |
| 纪要 | — | 记载会议情况和议定事项 | minutes | （无固定结尾） |
| 决定 | 下行 | 重要事项决策部署、奖惩人员 | decision | （无固定结尾） |
| 意见 | 均可 | 对重要问题提出见解和处理办法 | notice | 以上意见如无不妥，请批转……执行。 |

## 正文标题层级（所有文种通用）

| 层级 | 编号格式 | 字体 | JSON level |
|------|---------|------|-----------|
| 一级 | 一、二、三、 | 黑体三号 | 1 |
| 二级 | （一）（二）（三） | 楷体三号 | 2 |
| 三级 | 1. 2. 3. | 仿宋加粗三号 | 3 |
| 四级 | （1）（2）（3） | 仿宋三号 | （放入 paragraphs） |

## references/ 目录导航

加载本技能后，用 `read_file` 按需查阅以下参考资料：

### guidelines/ — 规范指南

| 文件 | 内容 | 何时查阅 |
|------|------|---------|
| `references/guidelines/format-standard.md` | GB/T 9704 格式标准（版面、字体、版头/主体/版记） | 需要确认排版细节时 |
| `references/guidelines/writing-rules.md` | 行文规则、语体风格、数字标点、结构逻辑 | 需要确认写作规范时 |
| `references/guidelines/common-phrases.md` | 公文常用开头语、过渡语、结尾语、动词搭配 | 需要规范用语时 |

### templates/ — 文种模板

| 文件 | 对应文种 | 内容 |
|------|---------|------|
| `references/templates/notice.md` | 通知 / 通报 / 意见 | 结构框架 + JSON sections 示例 + 正文范例 |
| `references/templates/report.md` | 报告 | 结构框架 + JSON sections 示例 + 正文范例 |
| `references/templates/letter.md` | 函 | 结构框架 + JSON sections 示例 + 正文范例 |
| `references/templates/resolution.md` | 请示 / 批复 | 两种 subtype 的结构和范例 |
| `references/templates/minutes.md` | 会议纪要 | meeting_info + agenda_items 示例 |
| `references/templates/decision.md` | 决定 | 结构框架 + JSON sections 示例 + 正文范例 |

## 使用方法

1. 先确认公文类型 → 查上面的「公文类型速查」表
2. 读取对应文种的模板文件 → 见上面「templates/ — 文种模板」表里的 `references/templates/` 各文件，获取该文种的结构框架和 JSON 示例
3. 如需确认格式细节 → 读 `references/guidelines/format-standard.md`
4. 如需规范用语 → 读 `references/guidelines/common-phrases.md`
5. 按模板构造 JSON → 交给 docx-report 的 `build render` 生成 Word
