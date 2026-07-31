# Word 文档 JSON Schema

Agent 只需生成符合 schema 的 JSON 数据，模板引擎负责排版。

模板索引入口（唯一数据源）：

- `../template-index.json`

单一数据源原则：

- 模板列表、别名映射、schema 路径、必填字段只维护在 `template-index.json`
- 本 README 不再重复维护模板清单数据，避免出现多份来源

## 目录结构

```
schemas/
├── base.json           → 共享类型定义（section, kv_table, data_table, policy_ref 等）
├── general/            → 通用文档模板（非公文）
└── govdoc/             → 党政机关公文模板（GB/T 9704）
```

## 使用方式

```bash
# 查看模板清单（读取 template-index.json）
<skill目录>/scripts/build templates

# 校验索引完整性（schema/test_input/别名目标）
<skill目录>/scripts/build check-index

# 按模板类型渲染
<skill目录>/scripts/build render <type> input.json output.docx

# 批量生成
<skill目录>/scripts/build batch <type> inputs/ outputs/

# 版本对比
<skill目录>/scripts/build diff <type> old.json new.json diff-output.docx

# 格式转换
<skill目录>/scripts/build ofd output.docx output.ofd
```

## 扩展新模板

1. 在 `schemas/` 下创建新子目录（如 `contract/`）
2. 定义 JSON Schema，复用 `base.json` 中的共享类型
3. 在 `../template-index.json` 增加模板定义与别名映射
4. 在引擎中注册新的文档类型
5. 执行 `<skill目录>/scripts/build check-index`
