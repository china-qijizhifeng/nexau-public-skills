# 模板库

10 个来自真实政企交付场景的 Agent 制品模板，来源是 [nexau-cookbook](https://github.com/hzhua/nexau-cookbook)，
**已按当前 NAC 平台事实校正**（校正内容见每个模板的 `TEMPLATE.md`「相对 cookbook 原版的改动」）。

> **这些是骨架，不是成品。** 复制过来之后一定要读该模板的 `TEMPLATE.md`，
> 按「复制后必须改的地方」逐条改完再打包。

## 怎么选

### 按场景

| 你要做的事 | 用哪个 |
|-----------|--------|
| 政策 / 法规 / 手册 / 制度问答 | [`01-agentic-rag`](./01-agentic-rag/) |
| 接外部 REST API（行情、天气、第三方 SaaS） | [`02-rest-api-tool`](./02-rest-api-tool/) |
| 自然语言查业务数据库 | [`03-text-to-sql`](./03-text-to-sql/) |
| 把数据库 / 外部系统封装成可复用服务 | [`04-mcp-server`](./04-mcp-server/) |
| runtime 需要 NAC 不自带的依赖（native 驱动 / 内网 SDK / 锁版本包） | [`05-native-driver-airgap`](./05-native-driver-airgap/) |
| 复用已有的向量库 / 知识库平台，不想重建索引 | [`06-external-vector-kb`](./06-external-vector-kb/) |
| 根据材料生成 Word 公文 / 结构化文档 | [`07-doc-generation`](./07-doc-generation/) |
| 材料审核 / 合规核查 / 表单预审 | [`08-business-review`](./08-business-review/) |
| 给任意 Agent 加内容安全护栏 | [`09-content-guardrail`](./09-content-guardrail/) |
| 不确定该配什么，想查全字段用法 | [`10-reference-skeleton`](./10-reference-skeleton/) |

### 按技术模式

| 技术模式 | 模板 |
|---------|------|
| Agentic RAG + 层级化知识库 | `01`、`08` |
| 自定义工具封装外部 API | `02`、`06` |
| Text-to-SQL（一表一 Skill） | `03` |
| MCP server 接入 | `04` |
| `nexau.json` `setup` 离线装依赖 | `05` |
| 多 Skill 协作 + 文档生成流水线 | `07` |
| 严格输出契约 / 审核 checklist | `08` |
| Middleware 确定性拦截 | `09` |
| 子代理 + 多模态 + 全套中间件 | `10` |

### 难度递进（第一次做 Agent 建议按这个顺序看）

`01` → `02` → `03` → `04`/`05`/`06` → `07`/`08`，`09`/`10` 是横切能力，随时可查。

## 目录

| 目录 | 说明 |
|------|------|
| `_builtin-tool-yamls/` | **内置工具的 `.tool.yaml`，即取即用** —— 需要哪个就复制到你制品的 `tools/` 下，再在 agent.yaml 里注册 binding。⚠️ 其中 `agent_tool.yaml` / `skill_tool.yaml` 是框架**自动注入**的（`Agent` / `LoadSkill`），**不要复制、不要写进 `tools:`**，放在这里仅供查阅其 schema |
| `01`–`10` | 各场景模板，每个含 `TEMPLATE.md` |

## 每个模板里有什么

```
NN-<slug>/
├── TEMPLATE.md      ← 先读这个：教什么 / 什么时候用 / 复制后必须改哪里 / 已知的坑
├── nexau.json
├── agent.yaml
├── systemprompt.md
├── tools/
├── custom_tools/    （部分模板）
└── skills/          （部分模板）
```

## 关于裁剪

模板是从 cookbook **裁剪**过的：保留了结构骨架、配置、层级索引和代表性内容，
剔除了大宗领域原文、锁文件和示例数据库（它们对「学怎么搭」没有增量价值，只增加体积）。

被裁掉了什么、去哪拿完整版，每个模板的 `TEMPLATE.md` 末尾都写了。
需要完整可跑的原版就去 <https://github.com/hzhua/nexau-cookbook>。

## 官方静态校验器

平台自带一个**制品静态校验器**（比「框架能不能跑」严格得多）。本目录的模板都已按它校正过。
复制改造完成后，**打包前跑一遍**（校验器随平台分发，不在你的制品里）：

```bash
S=<校验器脚本目录>
R=<规则文件目录>
PYTHONPATH=$S python3 $S/validate_artifact_static.py \
  --artifact-root <你的制品目录> --rules-root $R 2>/dev/null
```

⚠️ 必须带 `2>/dev/null`，否则 stderr 的 `E2B SDK not installed` 会让 JSON 解析失败。

规则全解与「哪些 error 该修、哪些是规范滞后不该修」见 `../references/artifact-spec-checklist.md`。

### 模板跑出来的残留 error 怎么判读

跑出来还有 error 不一定是模板坏了。当前有**两类**残留，**性质完全不同**：

| error code | 出现在 | 性质 | 该怎么办 |
|---|---|---|---|
| `skills.references.index_missing`<br>`skills.references.directory_index_missing` | 所有带 `references/` 知识树的模板（01 / 07 / 08 / 10） | **平台缺陷**：校验器规则文件把 `index_file` 配成了 `SKILL.md`，与平台自己的散文规范（禁止 references 内用 `SKILL.md`）打架 | 平台把规则文件里的 `index_file` 改成 `"INDEX.md"` 即可（实测改完 0 error）。**不要为消错把索引改回 `SKILL.md`** |
| `middleware.not_allowed`<br>`middleware.params.unexpected` | 09 / 10 | **有意偏离**：平台明确规定「middleware 不允许自由创新」，白名单只有 2 个。这不是误报 | 政企合规确实需要护栏（09 的敏感词就是），可以有意偏离但要向交付方说明；只是想调参的，优先 `params: {}` 用默认值 |

除这两类之外的 error，一律当真问题查。
详细判读见 `../references/artifact-spec-checklist.md` §8.2 与 §9.3；各模板具体剩哪几条见其 `TEMPLATE.md`。

## 复制模板的标准动作

1. 把模板目录整个拷到你的工作目录，改名
2. 读 `TEMPLATE.md` 的「复制后必须改的地方」，逐条改（通常是：agent name、description、
   skill 名与内容、工具的 `extra_kwargs`、`${env.X}` 变量名）
3. 换掉 `skills/*/references/` 下的示例知识为你自己的
4. 对照主 `SKILL.md` §8「平台契约红线」和 §9「上传前自检清单」过一遍
5. 打包上传
