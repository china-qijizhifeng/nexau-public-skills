---
name: nexau-artifact-builder
description: >-
  North Agent Cloud（NAC）/ NexAU 平台的 Agent 制品（Artifact）开发技能。当用户要求创建 Agent、
  生成制品、构建对话机器人、开发问数/审核/公文/知识库 Agent、打包上传 agent、或提到 nexau.json /
  agent.yaml / tool.yaml / SKILL.md / custom_tools / sub_agents / mcp_servers / middlewares /
  制品结构时使用。涵盖：制品结构与打包硬约束、agent.yaml 完整契约与校验强度、内置工具与自定义工具、
  Skill 设计与 Agentic Search、MCP 与子代理、中间件与内容安全护栏、环境变量与密钥注入、
  运行时路径边界、错误速查，以及 10 个可直接复制改造的实战模板。
---

# NexAU Agent 制品开发指南

> **事实源纪律**：本 skill 的每条硬结论都对着 NexAU 框架与 NAC 平台的实际运行行为核实过
> （框架侧 = NexAU SDK `0.5.0`）。文档会过时，运行时的实际行为才是事实源。
> 与本文冲突时以实测为准。

> ### 与平台侧 A4A 三个 skill 的关系（重要，别搞反上下游）
>
> 平台自带的 Agent4Agent（A4A）有一套配套 skill，分工是：
>
> | skill | 干什么 |
> |---|---|
> | `nexau-artifact-rules` | **静态硬规则的机器可读事实源**（`builder-static-rules.json` / `allowed-middlewares.json` / `builtin-tool-bindings.json`） |
> | `artifact-verifier` | 跑 Python 静态校验器出报告 |
> | `artifact-refiner` | 按规则改文件 |
>
> **✅ 该信它的**：那三份 **JSON 规则文件**——它们是校验器真正读的输入，本 skill 的
> `references/artifact-spec-checklist.md` 就是对着它们写的。
>
> **⚠️ 不要信它的**：`nexau-artifact-rules/references/` 下的 `agent-yaml-fields.md` 与
> `builtin-tools.md` —— 这两份是**本 skill 旧版的衍生品**（其 `SKILL.md` 规则 #18 明说
> 「已吸收 `nexau-artifact-builder` 的规则」），因此**原样保留了本 skill 后来纠正掉的错误**：
> 「`string` 不读文件 / 必须 `jinja` 才能读文件」、「model 裸名静默回落」（实为每次 chat 422）、
> 「`type`/`name` 必填」、「标配工具组合」、「不提供 `Glob` 和 `list_directory`」、
> 以及一条指向并不存在的目录的「内置工具 yaml 复制路径」。
>
> **⇒ 本 skill 与 A4A 那两份 .md 冲突时，以本 skill 为准；两边都存疑时以实测行为为准。**

## 0. 怎么用本 skill

本 skill 分三层，**按需读，不要一次性全读**：

| 我要做什么 | 去哪 |
|-----------|------|
| 从零建一个 Agent 制品 | 本文 §1→§2→§3，然后按 §7 选一个 `templates/` 模板复制改造 |
| 查 agent.yaml 某个字段怎么写 | `references/agent-yaml-fields.md` |
| 查内置工具叫什么、binding 怎么写 | `references/builtin-tools.md`；工具 YAML 从 `templates/_builtin-tool-yamls/` 复制（⚠️ 除 `agent_tool.yaml` / `skill_tool.yaml`——那两个是自动注入的） |
| 模型/采样参数怎么配、为什么用的模型不对 | `references/llm-config.md` |
| 密钥/环境变量注入到哪一层 | `references/env-vars-and-secrets.md` |
| 写自定义 Python 工具 | `references/custom-tools.md` |
| 接外部服务 / 拆子代理 | `references/mcp-and-subagents.md` |
| 上下文压缩、超长输出、内容安全护栏 | `references/middlewares.md` |
| nexau.json 字段、打包、运行时路径 | `references/nexau-json-and-packaging.md` |
| **多轮记忆 / 沙箱跨轮复用 / 用户上传的文件在哪 / 多 agent 怎么调 / 请求超时** | `references/runtime-session-and-io.md`（**做对话型或多步骤制品前必读**） |
| 报错了 / 行为不对 | `references/troubleshooting.md`（先查这里，再翻别处） |
| 确认制品符不符合官方规范 | `references/artifact-spec-checklist.md`（**生成任何新制品前当 checklist 过一遍**） |
| 找一个最接近我业务的现成例子 | `templates/README.md` 选型表 |

## 1. 制品是什么

制品（Artifact）= 运行一个 Agent 所需的全部配置和资源打成的压缩包（tar / tar.gz / zip）。
上传后平台解析 `nexau.json` 注册 Agent，部署时由 Agent Runtime 加载运行。

```
my-agent/
├── nexau.json           # 必须：项目清单（agents / setup / backend / runtime.command）
├── agent.yaml           # 必须：Agent 配置（模型、工具、skills、子代理、MCP、中间件）
├── systemprompt.md      # 必须：角色 + 流程 + 导航 + 输出规范（Jinja2 模板）
│                        #       官方规范 required_top_level_files 三件之一，且必须在顶层
├── tools/               # 按需：工具声明 *.tool.yaml
├── custom_tools/        # 按需：自定义工具的 Python 实现
├── skills/              # 按需：可插拔领域知识
│   └── <skill-name>/
│       ├── SKILL.md     #   必须：YAML frontmatter + 正文
│       └── references/  #   按需：知识原文（层级化组织）
└── sub_agents/          # 按需：子代理，每个一份自己的 agent.yaml
```

**运行时布局**（决定所有路径写法，细节见 `references/nexau-json-and-packaging.md`）：

| 位置 | 是什么 | 注意 |
|------|--------|------|
| `/agent` | 制品解压根 | ⚠️ 对 Python Runtime 是**只读挂载**，往这里写必然失败 |
| `/home/user` | 沙箱工作目录，runtime 进程 cwd | 可写；`/tmp` 也可写 |
| `/home/user/.skills/<skill目录basename>` | skills 部署位置 | 取值以 `LoadSkill` 返回的 `<SkillFolder>` 为准 |

**两套不同的路径基准，最容易踩**：

- `agent.yaml` 里的相对路径（`system_prompt` / `tools[].yaml_path` / `skills[]` / `sub_agents[].config_path`）→ 基准是 **agent.yaml 所在目录**
- `binding` 的 import 根 → 基准是**制品根目录**（`<root>` 与 `<root>/src` 被前插进 sys.path）

## 2. 开发工作流

### 第一步：把需求问清楚（三个问题）

1. **知识从哪来**：用户给的是文档集合 / GitHub 目录 / 数据库 / 外部 API / 已有向量库？
   → 决定走 Agentic Search、Text-to-SQL、自定义工具还是 MCP。
2. **要不要执行动作**：只问答，还是要读写文件、跑脚本、调外部系统？
   → 决定挂哪些工具。
3. **产出是什么**：一段回答 / 一份结构化结论 / 一个 Word 文件？
   → 决定要不要输出契约、要不要文档生成流水线。

### 第二步：选模板（不要从空白开始）

`templates/` 下有 10 个来自真实政企场景、已按当前 NAC 校正过的模板。
按 §7 或 `templates/README.md` 选最接近的一个复制，再按它的 `TEMPLATE.md`「复制后必须改的地方」改造。

### 第三步：按契约写配置

各文件的完整契约见 §0 表格指向的 references。写完对照 §8「平台契约红线」自检。

### 第四步：打包上传

```bash
cd /path/to/parent && tar -czf my-agent.tar.gz my-agent/
```

⚠️ 三条硬约束（违反直接被拒，细节见 `references/nexau-json-and-packaging.md`）：

- **压缩包 ≤ 100 MiB**，超限 413
- **归档只允许普通文件和目录** —— 含符号链接 / 设备 / FIFO 一律 400，所以**不要把
  `node_modules/` `venv/` `.git/` 打进去**；同时排除 `__pycache__/` 与 `*.pyc`
  （不会导致上传失败，但会把无用二进制打进制品——用 `tar --exclude` 或打包前清一遍）
- **必须含 `nexau.json`**

### 第五步：排障

先查 `references/troubleshooting.md`。它按「加载期 / 上传部署期 / 运行期 / 不报错但行为不对」分组。

> **用 `nac` CLI 跑闭环（可选）**：装了 North Agent Cloud CLI 就能一条龙做
> 打包 → 建版本 → 部署 → smoke/chat 验证 → 拉 log/trace。
> **命令细节以独立的 `nac` skill 为准**，本 skill 不复制 CLI 参考（避免两处漂移）。

## 3. 八条设计原则

来自 cookbook 十个真实交付案例的沉淀。**制品质量的差距主要来自结构设计，不是 prompt 写得多。**

| # | 原则 | 一句话 | 反面教材 |
|---|------|--------|---------|
| 1 | **三层分离** | systemprompt 管流程，SKILL.md 管知识框架，references 管原文 | 全塞进一个 3000 行 system prompt，改一个条款要翻全文，每次对话都加载全部知识 |
| 2 | **Prompt 只当指挥官** | 告诉 Agent「你是谁 / 怎么干活」，不告诉它「你知道什么」 | 在 prompt 里教业务知识，知识一更新整个 Agent 要重测 |
| 3 | **Skill 可插拔** | frontmatter `description` 决定触发，触发门槛要**故意写低** | description 写得太窄，用户随口一问就不触发 |
| 4 | **知识按需加载** | 原文存文件 + 索引指路，Agent 自己查 | 让 Agent「背」知识 → 引用的是记忆中的大意，条款号/金额/公式必错 |
| 5 | **表格优于散文** | 分类、条件、材料、额度一律上表格，并给「关键词」列做用户话术→条目的映射 | 大段散文，LLM 定位不准、漏项 |
| 6 | **显式处理边界** | 风险清单 + 「不知道就说不知道」的合法退出路径 + 容易遗漏项的提醒 | 没有退出路径 → LLM 自信地编造 |
| 7 | **工具结果要引导** | 不只说「用什么工具」，还要说「拿到结果后做什么」 | Agent 把 PDF 读出来总结一下就完了，不做交叉核验 |
| 8 | **输出格式即质量控制** | 结论先行 + 必须标注引用出处 + ✅❌⚠️ 三级状态标记 | 散文式回答，看起来完整但无法验证 |

**推论：工具越少越好。** Agent 可见的工具越多，选错概率越高、上下文越贵。
本 skill **不设「标配 N 件套」**——按场景挑，纯对话 `tools: []` 完全合法。选法见
`references/builtin-tools.md` 的场景对照表。

## 4. 五个核心文件的最小骨架

### nexau.json

```json
{
  "agents": { "my_agent": "agent.yaml" }
}
```

真正被平台消费的字段只有 `agents` / `setup` / `backend` / `runtime.command`。
⚠️ `excluded` **平台完全不解析**，它只是打包端约定，别指望服务端按它过滤。
`setup`（离线装依赖的唯一入口）等完整规范见 `references/nexau-json-and-packaging.md`。

### agent.yaml

```yaml
type: agent
name: my_agent
description: 一句话说明这个 Agent 干什么

system_prompt: ./systemprompt.md
system_prompt_type: jinja        # jinja / file 都是读文件后 Jinja2 渲染；string 是把值本身当模板

llm_config:
  model: ${env.LLM_MODEL}        # 跟随项目默认模型
  max_tokens: 8192
  temperature: 0.2
  # 本地裸跑 NexAU（不经 NAC）时需自行补 base_url / api_key；
  # 在 NAC 上这两个字段会被平台无条件覆盖，写了没用。

# ⚠️ tools / skills / middlewares 三个键即使为空也要显式写出来
#    （官方制品规范 required_list_fields，缺键判不合规——见 §8 E）
tools: []                        # 按需；见 references/builtin-tools.md
skills: []                       # 按需；见 §6
middlewares: []                  # 按需；见 references/middlewares.md

max_iterations: 50
max_context_tokens: 128000
tool_call_mode: structured       # 合法值只有 xml / structured
```

完整字段表、默认值、**校验强度分层**（哪些字段拼错会报错、哪些静默失效）见
`references/agent-yaml-fields.md`。

### systemprompt.md

见 §5。

### tools/*.tool.yaml

```yaml
type: tool
name: my_tool
description: >-
  工具描述 —— 这段是 LLM 决定用不用它的唯一依据，要写清「什么时候用」
input_schema:
  $schema: http://json-schema.org/draft-07/schema#
  type: object
  properties:
    param1:
      type: string
      description: 参数描述
  required: [param1]
  # ⚠️ 用了 extra_kwargs 就不能写 additionalProperties: false（见 §8）
```

内置工具的 YAML 直接从 `templates/_builtin-tool-yamls/` 复制。
⚠️ 该目录里的 `agent_tool.yaml` / `skill_tool.yaml` **不要复制、不要写进 `tools:`** ——
它们对应框架自动注入的 `Agent` / `LoadSkill`，放在那里仅供查阅 schema（见 §6）。

### skills/\<name\>/SKILL.md

```markdown
---
name: my-skill
description: |
  说明这个 skill 覆盖什么、**什么时候该用它**。
  触发门槛要故意写低：「即使用户只是随口问一下 X，也应触发此 skill」。
---

# 技能标题

## 核心知识框架
## 知识库导航（references 有哪些、怎么逐层下钻）
## 输出格式模板
## 重要原则 / 边界
```

## 5. systemprompt 写法

`system_prompt_type: jinja`（或 `file`，两者代码层等价）时读文件并做 Jinja2 渲染。
可用模板变量有 12+ 个，还能通过 agent.yaml 顶层 `context:` 注入自定义变量——
全集见 `references/agent-yaml-fields.md`。

**推荐骨架**（顺序有讲究）：

1. **一句话角色定义**（放最前）
2. **强制工作流程**（3-6 个编号步骤，第一步通常是「加载 skill 拿到路径」）
3. **知识库导航方法**（层级化知识库必写，见下）
4. **工具使用规则表**（我要做什么 → 用什么工具 → 参数怎么填）
5. **🚫 禁止操作**
6. **输出规范**（模板 + 状态标记）
7. **边界与防幻觉**（不知道时的退出路径）

### 层级化知识库的导航引导

```markdown
## 知识库导航方法

你的知识库层级化组织在 skill 的 references/ 下。部署后 skills 根目录位于 `/home/user/.skills/`；
**取具体路径以 LoadSkill 返回的 SkillFolder 为准**，不要自己拼。

第1跳: read_file("{SkillFolder}/references/INDEX.md")        → 看主题目录
第2跳: read_file("{SkillFolder}/references/主题A/INDEX.md")   → 看文件列表
第3跳: read_file("{SkillFolder}/references/主题A/具体文件.md") → 读内容

🚫 禁止跳步：看到子目录名后必须先读该子目录的 INDEX.md，
   禁止凭猜测构造文件名——只读取 INDEX.md 中明确列出的文件。

**知识库结构概览**：
| 主题目录 | 内容 |
|---------|------|
| ... | ... |
```

> **为什么概览表必不可少**：没有它，Agent 每次都得先读根索引才能开始，多一跳、多花 token。

> 🚨 **「skills 根目录位于 `/home/user/.skills/`」这句话是正则硬门，措辞不能改写。**
> 平台静态校验器用 `(?i)skills\s*根目录位于\s*` + `/home/user/.skills/` 匹配 systemprompt
> （`builder-static-rules.json` 的 `required_systemprompt_patterns`）。
> 语义等价但换了动词的写法（「skills **部署在** …」「skill 目录**在** …」）**一律不匹配**，
> 会被判 `agent.system_prompt.required_pattern_missing` —— 而报错文案是「你没写这句话」，
> 你却明明写了，很难往「措辞不对」上想。**照抄上面模板里的原句，别润色。**

> **索引文件命名：整个 skill 只有一个 `SKILL.md`，在技能根目录；`references/` 内部各层索引一律
> 命名 `INDEX.md`。**
>
> 理由是语义：`SKILL.md` 是 **skill 的入口**，框架靠它（且只靠它）加载技能
> （`Skill.from_folder` 只在 skill 根目录找 `SKILL.md`）。`references/` 下面是**知识库层级，不是 skill**，
> 不该占用 skill 专用的文件名——否则「哪个 SKILL.md 才是入口」永远是歧义。
> 这与 `skill-knowledge-organizer` skill 的产出**完全一致**（它产出的就是 `INDEX.md`）。
> 平台散文规范（`artifact-hard-rules.md`）**只在「不能用 `SKILL.md`」这半句上与我们一致**——
> 它推荐的具体名字是小写 `index.md` / `overview.md`；我们取 `INDEX.md`（与 organizer 对齐、且大写更醒目）。
> 三方在「references 内不该出现 SKILL.md」这一点上没有分歧，分歧只在具体拼写。
>
> ⚠️ **但平台静态校验器当前会因此报错**：它的规则文件把索引名配成了 `SKILL.md`
> （`builder-static-rules.json` 里的 `"index_file": "SKILL.md"`），于是 `INDEX.md` 版会被判
> `skills.references.index_missing` + 每个非空子目录一条 `directory_index_missing`。
> **这是校验器配置与平台自己的散文规范打架，属平台缺陷**——修法是把那一行改成 `"INDEX.md"`
> （已实测：改完 `INDEX.md` 版制品 0 error 通过）。详见 `references/artifact-spec-checklist.md` §8。
>
> 歧义靠位置区分：skill 根目录下那个是**入口**，`references/` 里的都是**导航索引**。

### 四个必须防的 Agent 坏习惯

这四条是实测反复出现的，**systemprompt 和 skill 入口 SKILL.md 里都要写**：

| 坏习惯 | 表现 | 防御话术 |
|--------|------|---------|
| 跳过索引猜文件名 | 看到 `合同纠纷/` 就猜 `违法解除劳动合同纠纷处理.md`，真名是 `违法解除劳动合同.md` | 「必须先读子目录 INDEX.md，只读其中明确列出的文件」 |
| 不加载 skill 就读文件 | 猜 `/agent/skills/...` 或 `skills/...`，全部报错 | 工作流程第一步就是「加载 skill 获取路径」 |
| 在大目录上全局搜索 | 对 references 根目录 `search_file_content` 卡死 | 「禁止对根目录搜索，必须限定到分类子目录」 |
| 不查资料凭记忆答 | 有知识库也跳过检索 | 「⚠️ 禁止凭记忆回答，必须先查阅知识库、基于原文回答」 |

## 6. Skill 设计

### 运行时加载机制（两级懒加载）

1. **始终可见**：SKILL.md 的 `name` + `description` + `SkillFolder` 作为摘要注入系统提示词
2. **按需加载**：Agent 调 `LoadSkill` 后，SKILL.md 正文才进入上下文
3. **references/ 不自动加载**：只是躺在磁盘上，Agent 必须用文件工具主动读

⚠️ **有 references 目录的 skill 必须挂 `read_file` 工具**，否则 Agent 看得见文件清单却读不到内容，
会回答「无法访问参考文件」。

⚠️ **目录名和 `name` 是两回事**：skill 的**部署路径由本地目录 basename 决定**
（`skills/pdf_to_md/` → `/home/user/.skills/pdf_to_md`），而 **LoadSkill 用什么名字调用由
frontmatter `name` 决定**（`name: pdf-to-md`）。两者可以不一致——`templates/07-doc-generation/`
就是活例子。

⚠️ **声明了 `skills:` 后框架会自动注入 `LoadSkill` 工具，禁止手写进 `tools:`**。
同类还有 `Agent`（声明 sub_agents 时）和 `ToolSearch`（有 defer_loading 工具时）。

### Agentic Search：默认的知识检索方式

不用向量库，让 Agent 像查百科全书一样逐层翻目录。SKILL.md 提供知识框架和查阅指引，
详细资料放 references/，Agent 用文件工具按需检索。

**这个模式需要凑齐的四件事**（不是「标配工具组合」，是这一种模式的组成要件）：
- SKILL.md = 知识框架 + references 清单 + 查阅指引
- references/ = 详细资料，按主题分层
- 工具挂 `read_file` + `search_file_content`（后者底层走 ripgrep，比逐文件扫读或 shell grep 快得多）
- systemprompt 写明「何时查阅哪个 reference」+ 多跳导航 + 禁止操作

#### ⚠️ 大型/扁平知识库：必须先用 skill-knowledge-organizer 整理（强制前置）

命中下表**任一**条件时，**必须先 `LoadSkill skill-knowledge-organizer`** 完成层级化整理，
再回来配置 Agentic Search。除非用户明确说「不要整理、直接同步即可」，否则不得跳过——
懒加载下不会隐式触发相关 skill，这条规则就是唯一触发点。

| 触发条件 | 典型表现 |
|---------|---------|
| 文件数 ≳ 50 且无主题分层 | 几百个文件全部平铺在 `references/` 根 |
| 知识库源是 GitHub 目录 / 本地目录 / 压缩包 | 用户给一个 repo 路径或一堆文档让你「做成 Agent」 |
| 文件名无规律 | 乱码 / UUID / `doc_001.md`，需重命名 |
| 没有现成索引或分类目录 | 拿到的是平铺 .md 列表 |
| 内容跨多个主题维度 | 条文 + 案例 + 表单 + 流程 + FAQ 混在一起 |

> 反例（本规则要防的就是这个）：把几百个文件平铺进 `references/` 根、只生成一个扁平索引。
> Agent 无法逐层缩小范围，定位慢、命中差。

#### 例外：纯上下文加载

仅当用户**明确要求**不用工具、且知识量极小时，把全部知识写进 SKILL.md 本身。这不是默认选择。

> 用户要求接入**向量库 / 已有知识库平台**时，Agentic Search 不是唯一解——
> 见 `templates/06-external-vector-kb/`。

## 7. 模式选型

| 你的场景 | 用哪个模板 | 核心模式 | 一定要读的 reference |
|---------|-----------|---------|-------------------|
| 政策/法规/手册问答 | `01-agentic-rag` | 层级化 SKILL.md 多跳路由 | §6 |
| 接外部 REST API（行情、天气、SaaS） | `02-rest-api-tool` | custom tool 封装 API | `custom-tools.md` |
| 自然语言查数据库 | `03-text-to-sql` | 一表一 Skill + SQL 安全写在代码里 | `custom-tools.md` |
| 数据库/外部系统要复用成服务 | `04-mcp-server` | HTTP MCP server | `mcp-and-subagents.md` |
| runtime 需要 NAC 不自带的依赖（native 驱动 / 内网 SDK） | `05-native-driver-airgap` | `nexau.json` `setup` + 离线 whl | `nexau-json-and-packaging.md` |
| 复用已有向量库 / 检索平台 | `06-external-vector-kb` | 检索 API 工具封装 | `custom-tools.md` |
| 根据材料生成 Word / 结构化文档 | `07-doc-generation` | 多 Skill 协作 + 渲染引擎 | `middlewares.md` |
| 材料审核 / 合规核查 / 表单校验 | `08-business-review` | 三层分离 + 严格输出契约 | §3 八条原则 |
| 内容安全 / 敏感词拦截 / 上线合规 | `09-content-guardrail` | SensitiveWordMiddleware 三路拦截 | `middlewares.md` |
| 不知道该配什么 / 想查全字段用法 | `10-reference-skeleton` | 全字段参考骨架（按需删减） | `agent-yaml-fields.md` |

每个模板目录下的 `TEMPLATE.md` 有「这个模板教你什么 / 复制后必须改的地方 / 已知的坑」。

## 8. 平台契约红线

**这张表是自检清单，写完 agent.yaml 逐条过一遍。**

### A. 写了会坏

| 写法 | 后果 |
|------|------|
| `llm_config.api_key: <字面量>` | 凭证进制品 = 安全事故；平台静态校验器判 error；且平台会覆盖，写了也无效 |
| `sandbox_config: ...` | **你写了平台就不注入**，沙箱路由走你那份，基本必炸 |
| `llm_config.model` 写裸模型名（无 `provider/` 前缀） | sidecar 直接 Reject 不走回落，每次 chat 422 |
| `${env.X}` 引用了未注入的变量（**包括写在 YAML 注释里的**） | 加载期 ConfigError 硬失败 |
| 工具用了 `extra_kwargs` 但 `.tool.yaml` 写了 `additionalProperties: false` | **每次调用**抛 `ValueError: Additional properties are not allowed` |
| middleware import 路径漏 `execution` 层 | `No module named ...`，启动失败 |
| 手写 `LoadSkill` / `Agent` / `ToolSearch` 进 `tools:` | 与框架自动注入冲突 |
| 归档里含符号链接（打包了 `node_modules/` `venv/`） | 上传 400 |
| 制品压缩包 > 100 MiB | 上传 413 |

### B. 写了没用（无害噪声，会被平台覆盖）

`llm_config.base_url` / `llm_config.api_key` / `llm_config.api_type` / `llm_config.stream`
—— NAC 上都由平台按命中的模型卡注入或强制。**本地裸跑 NexAU 时才需要写。**

⚠️ `tracers` 情况特殊：**运行期**平台 tracer 与你自带的是**合并**关系（写了功能上能用），
但**平台官方制品规范把 `tracers` 列为禁写字段**（与 `sandbox_config` 并列判 error）。
结论是**别写**，观测交给平台。

### C. 必须显式声明，否则静默不生效

| 字段 | 不写的后果 |
|------|-----------|
| `stop_tools: [complete_task]` | 子代理挂了 `complete_task` 也不会结束，result 不会成为返回值 |
| `skills:` 里的 skill 目录 | 不会被上传到沙箱，Agent 读不到 |
| systemprompt 里的工具使用规则 | Agent 乱猜参数、跳过检索、在大目录上搜到超时 |
| custom tool 签名里的 `agent_state` / `sandbox`（**具名形参**，`**kwargs` 不算） | 拿不到沙箱句柄且**毫无报错**。自定义工具跑在 agent-runtime 进程里，不在沙箱里——裸 `open()` 会去读写 runtime 容器那个同名的 `/home/user`，读不到 agent 的文件、或把产物静默写错容器。见 `references/custom-tools.md` §1–§3 |

### D. 校验强度不均，拼错未必报错

- 顶层 key 拼错 → `ConfigError: Extra inputs are not permitted`（会报）
- `sub_agents` / `mcp_servers` 条目多余字段 → 硬失败（会报）
- ⚠️ **`tools` / `skills` 条目多余或拼错的 key → 静默忽略，不报错**（最难查）
- ⚠️ `llm_config` 内部字段 → 零校验

细节见 `references/agent-yaml-fields.md`「校验强度分层」。

### E. 官方制品规范另有一套更严的要求

除了上面这些，平台还有一套**制品静态规范**（比「框架能不能跑」严格）：
`type`/`system_prompt_type`/`tool_call_mode` 三个值必须钉死、`tools`/`skills`/`middlewares`
三个键必须存在（空也要写）、`tools[].binding` 必填、`skills[]` 必须是字符串路径、
`.tool.yaml` 字段走白名单、`references/` 各层必须有索引文件、
挂 `ask_user` 必须写进 `stop_tools`、systemprompt 必须写出 `/home/user/.skills/`。

**全量规则 + 自查清单见 `references/artifact-spec-checklist.md`。**
它不是上传硬门（上传照样过、也能跑），但要产出「官方规范制品」就得满足。

## 9. 上传前自检清单

- [ ] `nexau.json` 在压缩包里，`agents` 指向的 agent.yaml 路径正确（相对 nexau.json）
- [ ] 压缩包 ≤ 100 MiB，不含符号链接（没打进 `node_modules/` `venv/` `.git/`）
- [ ] agent.yaml 过一遍 §8 的 A–E 五节（E「官方制品规范」最容易漏）
- [ ] 每个 `${env.X}`（**含注释里的**）对应的变量都已在正确的 scope 建好
- [ ] 密钥走的是正确通路：给 custom_tools 用 → runtime scope；给沙箱脚本/CLI 用 → sandbox scope
- [ ] 有 references 的 skill 都挂了 `read_file`
- [ ] 用了 `extra_kwargs` 的工具，其 `.tool.yaml` 没有 `additionalProperties: false`
- [ ] systemprompt 有：工作流程 + 导航方法 + 工具规则表 + 禁止操作 + 输出格式
- [ ] SKILL.md 的 `description` 触发门槛足够低
- [ ] 大型知识库已过 `skill-knowledge-organizer`（它产出的 `INDEX.md` 命名正是本 skill 的约定，无需改名）
- [ ] 整个 skill 只有技能根目录一个 `SKILL.md`；`references/` 内各层索引都叫 `INDEX.md`
- [ ] **跑过平台官方静态校验器**，`pass: true` 或只剩已知的白名单滞后类 error
      （命令与判读见 `references/artifact-spec-checklist.md`）

## 10. 出问题了

先查 `references/troubleshooting.md`。那里按失败阶段分组，每行给「症状 → 根因 → 具体动作」。

两个最常见的误判：

- **「部署成功」≠「模型配对了」** —— model 未命中项目授权卡在部署期不报错，chat 期才 422。
- **「本地跑通」≠「云上跑通」** —— 本地 LocalSandbox 会继承 `os.environ`，云端沙箱不会。
