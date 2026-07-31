---
name: pdf-to-md
description: |
  将用户提供的 PDF 文件通过 OCR 转换为 Markdown 文本。使用 SiliconFlow DeepSeek-OCR 逐页识别，支持并发处理，结果自动保存为同名 .md 文件。
  当用户提到 PDF 解析、PDF 转文本、读取 PDF 内容、识别 PDF 中的文字、OCR、扫描件识别等场景时使用此技能。
---

# PDF 转 Markdown Skill

将 PDF 文件通过 OCR 转换为结构化的 Markdown 文本。

## 使用方式

加载本技能后，通过 `run_shell_command` 调用脚本：

```bash
python3 {skill_path}/scripts/pdf_to_md.py <pdf_file_path>
```

其中 `{skill_path}` 是 `LoadSkill("pdf-to-md")` 返回的技能文件夹路径。

## 返回结果

脚本在 stdout 输出 JSON：

| 字段 | 说明 |
|------|------|
| `markdown` | 转换后的 Markdown 文本（超过 10000 字符会截断） |
| `output_file` | 完整结果保存的 .md 文件路径 |
| `total_pages` | PDF 总页数 |
| `total_chars` | 完整文本的字符数 |
| `truncated` | 是否被截断（"True"/"False"） |

如果 `truncated` 为 "True"，需通过 `read_file` 读取 `output_file` 路径获取完整内容。

## 处理流程

1. 验证文件存在、后缀为 .pdf、大小不超过 50MB
2. 用 PyMuPDF 将 PDF 拆分为单页
3. 每页并发发送至 DeepSeek-OCR API（最多 10 并发）
4. 按页码顺序拼接结果，用 `---` 分隔各页
5. 完整结果写入同目录下的同名 .md 文件

## 环境变量

- `OCR_API_KEY`：SiliconFlow API Key。本脚本经 `run_shell_command` 在**沙箱**里执行，
  只能读到 **sandbox scope** 的环境变量——必须配在「运行配置 → 沙箱环境」，
  或按次请求经 `variables.sandbox_env` 传入。配成 runtime scope 该脚本读不到。

## 依赖

- `PyMuPDF`（fitz）
- `httpx`

两者均已预装在沙箱的 `/opt/sandbox-python` venv 中（已 PATH 前置），直接 `python3` 调用即可。
