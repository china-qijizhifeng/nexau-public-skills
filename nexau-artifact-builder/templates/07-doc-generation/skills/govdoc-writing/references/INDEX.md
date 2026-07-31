# govdoc-writing / references 导航索引

本目录是公文写作知识库的资料区，按 **Agentic Search** 方式使用：先在本索引里定位到需要的那一份，再用 `read_file` 单独读取，**不要整目录加载**（合计数万字）。

## 子目录

| 子目录 | 装什么 | 何时进去 |
|--------|--------|---------|
| `guidelines/` | 3 份规范指南：格式标准、行文规则、常用套语 | 需要确认"怎么排、怎么行文、用什么措辞"时 |
| `templates/` | 6 份文种写作模板，每份自带可直接被 docx-report 渲染的 JSON sections 示例 | 已确定文种、要动笔写正文时 |

各子目录内还有一层自己的导航索引（同名 `INDEX.md`），列出该目录下每个文件的用途。

## guidelines/ 文件速览

| 文件 | 内容 |
|------|------|
| `guidelines/format-standard.md` | GB/T 9704 格式标准：纸张版面、字体字号、版头/主体/版记各要素编排 |
| `guidelines/writing-rules.md` | 行文规则（上行/下行/平行）、语体风格、数字与标点、结构逻辑 |
| `guidelines/common-phrases.md` | 按文种归类的开头语、过渡语、结尾语与动词搭配 |

## templates/ 文件速览

| 文件 | 对应文种 |
|------|---------|
| `templates/notice.md` | 通知 / 通报 / 意见 |
| `templates/report.md` | 报告 |
| `templates/letter.md` | 函 |
| `templates/resolution.md` | 请示 / 批复 |
| `templates/minutes.md` | 会议纪要 |
| `templates/decision.md` | 决定 |

## 典型查阅顺序

1. 定文种 → 看技能主说明里的「公文类型速查」表
2. 写正文 → 读 `templates/` 下对应的那一份，照它的结构框架和 JSON sections 示例来
3. 核排版 → 读 `guidelines/format-standard.md`
4. 顺措辞 → 读 `guidelines/common-phrases.md`
5. 拿不准行文方向或语气 → 读 `guidelines/writing-rules.md`
