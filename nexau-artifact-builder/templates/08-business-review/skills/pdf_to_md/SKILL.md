---
name: pdf-to-md
description: |
  将用户提供的 PDF 文件通过 OCR 转换为 Markdown 文本。使用 SiliconFlow DeepSeek-OCR 逐页识别，支持并发处理，结果自动保存为同名 .md 文件。
  当用户提到 PDF 解析、PDF 转文本、读取 PDF 内容、识别 PDF 中的文字、OCR、扫描件识别等场景时使用此 skill。即使用户只是说"帮我看看这个 PDF"或"把这个文件转成文字"，也应触发。
---

# PDF 转 Markdown Skill

将 PDF 文件通过 OCR 转换为结构化的 Markdown 文本。

## 何时使用

- 用户提供了 PDF 文件需要读取内容
- 需要从扫描件、证件、合同等 PDF 中提取文字信息
- 其他 skill（如公积金审核）需要解析用户提交的 PDF 材料

## 使用方式

本技能**没有**注册同名工具，用 `run_shell_command` 跑技能自带的脚本（部署后位于 `/home/user/.skills/pdf_to_md/scripts/pdf_to_md.py`）：

```bash
python /home/user/.skills/pdf_to_md/scripts/pdf_to_md.py path/to/document.pdf
```

脚本向 stdout 打印 JSON 结果。多个 PDF 分别调用即可。

## 返回结果

| 字段 | 说明 |
|------|------|
| `markdown` | 转换后的 Markdown 文本（超过 10000 字符会截断） |
| `output_file` | 完整结果保存的 .md 文件路径 |
| `total_pages` | PDF 总页数 |
| `total_chars` | 完整文本的字符数 |
| `truncated` | 是否被截断（"True"/"False"） |

如果返回结果中 `truncated` 为 "True"，说明 `markdown` 字段只包含前 10000 字符，完整内容需通过 `read_file` 读取 `output_file` 路径的文件。

## 处理流程

1. 验证文件存在、后缀为 .pdf、大小不超过 50MB
2. 用 PyMuPDF 将 PDF 拆分为单页
3. 每页并发发送至 DeepSeek-OCR API（最多 10 并发）
4. 按页码顺序拼接结果，用 `---` 分隔各页
5. 完整结果写入同目录下的同名 .md 文件
6. 返回截断后的文本供 LLM 直接使用

## 注意事项

- 每页独立 OCR，复杂跨页表格可能识别不完整，需人工核对
- 扫描质量差的 PDF（模糊、倾斜、手写）识别准确率会下降
- 需要 `OCR_API_KEY` 环境变量（**必填、无默认值**，缺失时脚本直接报 "API Key required for PDF OCR"）；`OCR_BASE_URL` 可选，默认指向 SiliconFlow
- 脚本跑在沙箱里，所以这两个环境变量必须配置在 **sandbox scope**（runtime scope 的变量沙箱读不到）
- 依赖 `PyMuPDF`（fitz）和 `httpx`，沙箱镜像已预装，无需在 `nexau.json` 里额外声明 setup
