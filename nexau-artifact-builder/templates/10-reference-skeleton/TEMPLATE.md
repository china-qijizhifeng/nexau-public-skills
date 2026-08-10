# 模板：全字段参考骨架 / 档案智能归档助手（reference-skeleton）

> **定位**：NexAU **全能力字典** —— 11 个官方内置工具 + 1 个自定义工具 + 子代理 + Skill + 4 个中间件 + MCP，每个字段都带注释。
> **难度**：★★★☆☆（配置量大，但没有难懂的逻辑）
> **用法**：**查字典 / 按需删减**，不是「照着跑」。以「档案归档」为示范场景填满所有能力槽位。
> **来源**：nexau-cookbook《档案助手》(`档案助手/archive-assistant`)，教程 `tutorial-archive-assistant.md`。⚠️ 该样例**未被 cookbook README 收录**，是本 skill 新增的第 10 个模板。

---

## 这个模板教你什么

1. **一份 agent.yaml 里所有顶层字段长什么样**：`tools` / `skills` / `sub_agents` / `mcp_servers` / `middlewares` / `stop_tools` / 执行控制七件套（`max_iterations` / `max_context_tokens` / `max_running_subagents` / `timeout` / `retry_attempts` / `retry_backoff_max_seconds` / `tool_call_mode`），每项都标了框架默认值。删到只剩自己要的，比从零拼更快也更不容易写错。
2. **文件 + 多模态 + Shell 工具集的完整 binding 串**（已实测可加载，可直接抄）—— 尤其 `read_visual_file`（读扫描件/照片）和 `run_shell_command`（真正执行 `mkdir`/`mv`）的组合。
3. **「只读子代理并行分片」范式**：子代理只给 `list_directory` / `read_file` / `read_visual_file` / `complete_task`，**刻意不给写文件和 Shell**——判定归子代理、写操作归主 agent。这样才敢并行开多个。
4. **`complete_task` 必须配对 `stop_tools`**：挂了工具不等于会结束（cookbook 原版就漏了，见「本模板相对 cookbook 原版的改动」）。
5. **自定义工具走沙箱 API 而不是裸 `open()`**：`custom_tools/file_fingerprint.py` 是「声明 `agent_state` → `get_sandbox()` → `sandbox.read_file()`」的最小完整样板。
6. **4 个中间件的真实参数名与默认值**（`threshold` 而不是 `threshold_ratio`；`head_chars + tail_chars ≤ max_output_chars` 是硬校验；`RoundAndTokenReminder.max_context_tokens` 无默认必填）。

---

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 替代方案 |
|---|---|---|
| 「agent.yaml 的 XXX 字段怎么写 / 默认值是多少」 | ✅ 当字典查 | 也可看 `../../references/agent-yaml-fields.md` |
| 起一个新 agent，还不确定要哪些能力 | ✅ 复制后**删**到最小集 | —— |
| 要「读一堆本地文件（含扫描件/照片）→ 分类 → mv 归位 → 出清单」 | ✅ 改 skill 规则即可直接跑 | —— |
| 只做知识库问答 / RAG | ❌ 太重 | `01-agentic-rag` |
| 只调一个外部 HTTP API | ❌ | `02-rest-api-tool` |
| 只接 MCP server | ❌ 这里的 MCP 只是示例片段 | `04-mcp-server` |
| 只生成 PDF/Word 公文 | ❌ | `07-doc-generation` |
| 需要内容安全护栏 | ❌ 本模板无护栏 | `09-content-guardrail` |
| 生产上线（真做档案归档） | ⚠️ 必须先替换 `skills/archive-rules/` 全部占位规则 | —— |

---

## 目录结构

```
10-reference-skeleton/
├── nexau.json                       项目清单：agents 入口映射（+ excluded，仅打包端约定）
├── agent.yaml                       ⭐ 主配置，全字段带注释——本模板的核心资产
├── systemprompt.md                  归档指挥官 prompt（jinja，用 {{ date }} / {{ working_directory }}）
├── tools/                           12 个工具 schema（11 内置 + file_fingerprint）
│   ├── read_file / read_visual_file / read_many_files      读取（含多模态读扫描件）
│   ├── list_directory / Glob / search_file_content         浏览定位
│   ├── write_file                                          写归档清单
│   ├── run_shell_command                                   执行 mkdir / mv
│   ├── write_todos / ask_user / save_memory                会话工具
│   └── file_fingerprint.tool.yaml                          自定义工具 schema
├── custom_tools/
│   └── file_fingerprint.py          自定义工具实现：agent_state → get_sandbox → sha256
├── skills/archive-rules/
│   ├── SKILL.md                     索引 + 分类/命名概览（frontmatter 的 name 决定 LoadSkill 调用名）
│   └── references/
│       ├── INDEX.md                 references 目录导航索引（校验器要求，无 frontmatter）
│       └── {classification.md, naming.md}   大块规则（占位，必须替换）
└── sub_agents/file_classifier/
    ├── agent.yaml                   只读分类子代理（含 stop_tools: [complete_task]）
    ├── systemprompt.md              分类员 prompt
    └── tools/                       4 个工具 schema（只读 + complete_task）
```

---

## 复制后必须改的地方

按顺序做，1–4 是**不改就跑不对**，5–9 是裁剪。

| # | 文件:字段 | 改成什么 |
|---|---|---|
| 1 | `nexau.json:agents` | key 换成你的 agent 名（现为 `archive_assistant`），value 保持指向 `agent.yaml` 的相对路径 |
| 2 | `agent.yaml:name` / `description` | 与 `nexau.json` 的 key 对齐；description 写清这个 agent 干什么（模型选子代理/平台展示都读它） |
| 3 | `skills/archive-rules/**` | **占位规则全部替换成你单位的真实规范**。门类码、保管期限（永久/30 年/10 年）都是编的，照搬会导致定级错误。同时改 `SKILL.md` frontmatter 的 `name` + `description`（description 决定模型什么时候想起来加载它） |
| 4 | `systemprompt.md` | 角色、流程、铁律换成你的业务；**保留 `/home/user/.skills/` 那句**（skill 运行时根目录，平台静态校验器要求 systemprompt 里出现） |
| 5 | `agent.yaml:tools` | **删到最小集**。工具越少，模型选错概率越低、上下文越省。用不到 Shell 就删 `run_shell_command`（连带删 `tools/run_shell_command.tool.yaml`） |
| 6 | `agent.yaml:mcp_servers` | **不接外部服务就整段删掉**。示例里的 `host.docker.internal:8000` 在 NAC K8s 沙箱里不解析 |
| 7 | `agent.yaml:sub_agents` + `sub_agents/` 目录 | 不需要并行委派就整段删（连目录一起）。留着的话务必保持 `stop_tools: [complete_task]` |
| 8 | `agent.yaml:middlewares` | ①ContextCompaction ②LongToolOutput ④RuntimeEnvironment 一般都留；③RoundAndTokenReminder 看是否需要轮次提示。③ 的 `max_context_tokens` 要和顶层 `max_context_tokens` 保持一致 |
| 9 | `custom_tools/file_fingerprint.py` + `tools/file_fingerprint.tool.yaml` | 不需要指纹就两个文件一起删，并删掉 `agent.yaml` 里那条 `- name: file_fingerprint` |

**跑起来只需要 1 个环境变量**：`LLM_MODEL`（runtime scope）。`LLM_BASE_URL` / `LLM_API_KEY` 已从 llm_config 移除——NAC 会覆盖它们。

---

## 关键设计要点

### 1. 归档场景的铁律：原件不可改 + 分类必有据

tutorial 强调「归档最容易出问题的不是不会分，而是乱动原件 / 乱归类」。所以：

- **刻意不挂内容编辑工具**（`replace` / `multiedit_tool` / `apply_patch`）。归档只动**文件名和位置**（`mv`），不动**内容**。
  → 这条思路可迁移：**能力清单本身就是护栏**，别把「用不上但没坏处」的工具挂上去。
- **分类必有据**：每个门类/期限判定要对得上 `archive-rules` 的具体条目；拿不准用 `ask_user`，不硬归。
- **破坏性操作先确认**：批量 `mv`、覆盖同名文件先 `ask_user`。

### 2. 只读子代理 = 可安全并行的前提

| | 主 agent | file_classifier 子代理 |
|---|---|---|
| 读文件 / 读扫描件 | ✅ | ✅ |
| 写文件 / Shell / mv | ✅ | ❌ 刻意不给 |
| 职责 | 编排 + 执行归档动作 + 出清单 | 只判定门类/期限并汇总 |
| 并行 | 单实例 | 多实例分片（并发数由框架/prompt 决定，**不由 `max_running_subagents` 控制**，见「已知的坑」） |

**反例**：如果给子代理 Shell，多个子代理同时 `mv` 会互相踩、且没人知道最终布局。写操作必须收敛到单点。

⚠️ 子代理**不自带 Skill**。委派时必须把 `archive-rules` 的门类/期限口径写进任务说明，否则它无据可依（systemprompt 第 4 步已写死这条）。

### 3. `sub_agents` 是列表不是 dict

```yaml
sub_agents:
  - name: file_classifier              # ← 调用标识，写错报 SubAgentNotFoundError
    config_path: ./sub_agents/file_classifier/agent.yaml
```

框架自动注入名为 `Agent` 的工具；`skills:` 声明后自动注入 `LoadSkill`。**这两个都不要手写进 `tools:`**。

### 4. 自定义工具的沙箱边界

```python
def file_fingerprint(file_path: str, agent_state: AgentState | None = None) -> dict:
    sandbox = get_sandbox(agent_state)                      # agent_state 由框架按签名自动注入
    res = sandbox.read_file(resolve_path(file_path, sandbox), binary=True)
```

- 自定义工具函数跑在 **agent-runtime 进程**，裸 `open()` / `os.path` 读的是运行时进程的盘，**看不到沙箱里 agent 的工作文件**。
- `agent_state` **不写进 `input_schema`**（写了会报错）。
- 返回 dict 里 `content` 必须是**字符串**才完整发给 LLM；`returnDisplay` 只给前端。
- 详见 `../../references/custom-tools.md`。

---

## 已知的坑

| ⚠️ 坑 | 症状 | 修法 |
|---|---|---|
| **`complete_task` 没登记进 `stop_tools`** | 子代理调完 `complete_task` 还继续跑，直到 `max_iterations` 撞墙；`result` 也没成为返回给主 agent 的 final_response | 子代理 `agent.yaml` 加 `stop_tools: [complete_task]`（本模板已修） |
| **`extra_kwargs` × `additionalProperties: false`** | `ValueError: Invalid parameters for tool 'X': Additional properties are not allowed ('db_path' was unexpected)` | 给该工具的 `input_schema` **删掉 `additionalProperties: false`**。别把密钥 key 写进 `properties`（模型会看见并覆盖）。只有 `agent_state`/`sandbox`/`ctx` 注入、无 `extra_kwargs` 的工具不受影响，可保留 |
| **`${env.X}` 连注释里的都会被解析** | 注释里写个示例 `${env.MCP_TOKEN}` → 加载期 `ConfigError` | 注释里一律写 `<占位符>`。替换发生在 `yaml.safe_load` 之前、对整个文件文本做正则（`[A-Za-z_][A-Za-z0-9_]*`，中文如 `${env.变量名}` 不会被匹配，可安全出现在注释里）。不支持默认值/转义 |
| **项目没有可见模型卡 → `${env.LLM_MODEL}` 不注入** | agent 加载 `ConfigError`，看起来像 yaml 写错了 | 先在平台给项目挂上至少一张可见模型卡 |
| **中间件 import 路径漏 `execution` 层** | import 报错 | 统一前缀 `nexau.archs.main_sub.execution.middleware.` |
| **中间件参数名写错** | 只有 `ContextCompactionMiddleware` 是 `extra=forbid` 会给出清晰报错；其余中间件抛 Python 原生 `TypeError` | 对着 agent.yaml 注释里的参数名抄；`head_chars + tail_chars > max_output_chars` 会直接 `ValueError` |
| **MCP server 连不上** | 不会导致加载失败（框架只 log warning），但每次拉起 agent 白等 `timeout` 秒 | 不接就把 `mcp_servers` 整段删掉 |
| **以为 `max_running_subagents` 能限并发** | 调大调小都不改变实际并发 | 它是**空旋钮**：框架只是把这个值存下来，没有任何地方消费它（既没有 Semaphore 也没有线程池上限）。要控并发只能写进 systemprompt 的调度规则。详见 `../../references/mcp-and-subagents.md` §5.6 |
| **打包时误压外层目录** | 平台找不到 `nexau.json` | 压缩**含 `nexau.json` 的那一层内部**。另：包 ≤ 100 MiB（超限 413）；归档**只允许普通文件和目录，含符号链接必 400 失败** |
| **本模板跑平台静态校验器会剩 9 条 error（有意保留，见下）** | 8 条中间件相关（6 × `middleware.params.unexpected` + 2 × `middleware.not_allowed`）+ 1 条 `tool.binding.import_error` | **不要为了消错删中间件、砍参数或改 binding**。逐条说明见下方 |

### 关于那 9 条 error：8 条是「有意偏离白名单」，1 条是本地环境假阳性

先把两类性质分开——它们的处置方式完全不同：

**A. 8 条中间件 error —— 平台是「有意收窄」，本模板是「有意偏离」**

平台的 `allowed-middlewares.json` 目前只放行 **ContextCompaction** 和 **LongToolOutput** 两个中间件，且**不允许 LongToolOutput 带任何参数**。这**不是**「规范滞后于框架能力、可以无视」——`artifact-hard-rules.md` §5.1 明写「不允许自由创新」，白名单窄是平台的**主动收窄**。本模板定位是全字段字典，所以**有意偏离**官方规范保留了完整的 4 个中间件与真实参数：

| 条数 | code | 命中位置 | 为什么本模板不改 |
|---|---|---|---|
| 6 | `middleware.params.unexpected` | `middlewares[1].params` 的 `max_output_chars` / `head_lines` / `tail_lines` / `head_chars` / `tail_chars` / `bypass_tool_names` | 这 6 个都是 `LongToolOutputMiddleware` 里真实存在、有默认值的参数（`head_chars + tail_chars ≤ max_output_chars` 还是硬校验）。砍掉等于丢掉「截断阈值怎么调」这份字典价值 |
| 1 | `middleware.not_allowed` | `middlewares[2].import` RoundAndTokenReminderMiddleware | 框架真实提供，但**不在平台白名单内** |
| 1 | `middleware.not_allowed` | `middlewares[3].import` RuntimeEnvironmentMiddleware | 同上。⚠️ 这条在补 `params: {}` **之前是被掩盖的**——校验器缺 `params` 键时直接 `continue`，不走白名单检查；补齐后才暴露，属于「修对了一条、显形了另一条」，不是新引入的问题 |

⚠️ **交付真项目时这 8 条不能照抄放过**：偏离官方规范需自负后果，上线前要么与平台确认、走白名单收录流程，要么按下面的做法收敛。详见 `../../references/artifact-spec-checklist.md` §9.3。

**落地做真项目时**：如果你的平台环境同样只放行这两个中间件，就按需只留 ①ContextCompaction（参数照抄即可）+ ②LongToolOutput（**删掉 `params` 下所有键，留 `params: {}`**），删掉 ③④ 两段——这样中间件这 8 条就全清。本模板不这么做，是因为它要当字典查。

**B. 1 条 `tool.binding.import_error` —— 校验器所在环境没装 `nexau`，不是模板问题**

报在 `agent.yaml.tools[11].binding`（`custom_tools.file_fingerprint:file_fingerprint`），原文是 `No module named 'nexau'`。原因：校验器会真的 `import` 自定义工具模块，而 `file_fingerprint.py` 顶部 `from nexau.archs...` 导入了框架——在**没装 nexau 的机器上**跑校验器必然失败。同一批 11 个内置工具 binding 因同样的原因只报 `tool.binding.import_warning`——校验器对内置 binding 的导入失败降级成 warning，对自定义 binding 才判 error。

判据很简单：**在装了 `nexau` 的环境（平台侧 / agent-runtime 镜像里）跑同一条命令，这条就会消失**。所以不要为了消它去删 `from nexau...` 或改 binding —— 那才是真把工具改坏。

---

## 本模板相对 cookbook 原版的改动

裁剪：**未删除任何文件**——本模板定位就是全字段字典，cookbook 原版 `archive-assistant/` 的所有文件都保留。完整原版见 `nexau-cookbook/档案助手/archive-assistant/`，教程见同目录 `tutorial-archive-assistant.md`（含裁剪自查清单与部署步骤）。

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `sub_agents/file_classifier/agent.yaml` | **补齐 `skills: []` / `middlewares: []`** | 本 skill 反复强调「三键必写」，而这是整个 skill 里唯一一份子代理 agent.yaml，会被当成子代理写法的官方范本抄走。校验器**不递归 `sub_agents/`**（它根本不处理这个目录），所以省略不报错——但同样两行放在制品根 `agent.yaml` 里就是 `skills.invalid_type` / `middlewares.invalid_type`。框架侧这两个键确实可选（`middlewares` 可为 `None`、`skills` 默认空列表），补齐纯粹是让范本与规范一致 |
| `agent.yaml` 中间件段头注释 | 「执行顺序 = 声明顺序」→ 按 hook 阶段分别写明：`before_*` / `stream_chunk` 正向、`after_agent` / `after_model` / `after_tool` **倒序**、`wrap_*` 洋葱（index 0 最外层） | **原注释是假规则**。实际行为：`after_agent` / `after_model` / `after_tool` 三个 hook 都按**声明的倒序**依次调用中间件；`wrap_model_call` / `wrap_tool_call` 则是逐层包裹的洋葱结构（index 0 在最外层）。与 `../../references/middlewares.md` §4 直接矛盾。本模板 4 个中间件恰好在倒序/洋葱阶段各只有一个参与者，跑不出差别——但在一份「全字段参考骨架」里教一条假规则，会被原样抄进同阶段挂两个中间件的真项目 |
| `agent.yaml` ④ RuntimeEnvironmentMiddleware 段注释 | 「注入（日期/工作目录等）」→ 「注入工作目录 / 操作系统 / shell 后端，**刻意不注入日期、用户名、任意 env**；三个值全空时静默不注入」 | 事实错误。该中间件自己的文档就写明「日期、用户名、任意环境变量这类易变值应留在用户自己的模板里」，它只提供 `current_directory` / `working_directory` / `operating_system` / `shell_tool_backend` / `shell_backend` 这几个键（后两组是别名，实际三个值），默认模板也只有三行；三个值全空时它直接渲染成空串、静默不注入。`middlewares.md` §6 选型表早就写对了，是模板注释单方面漂移 |
| `sub_agents/file_classifier/agent.yaml` | **新增 `stop_tools: [complete_task]`**（+ 说明注释） | **真 bug**：原版挂了 `complete_task` 却没登记 stop_tools，框架看它就是个普通工具——子代理不会因此结束，`result` 也不会成为返回主 agent 的 final_response（框架是拿工具名去比对 `stop_tools` 才决定停机的） |
| `agent.yaml:llm_config` | 删除 `api_type` / `base_url` / `api_key` / `stream`，只留 `model` + `max_tokens` + `temperature`；加一行「本地裸跑需补 base_url/api_key」注释 | NAC 上 `base_url`/`api_key` 被平台运行期无条件覆盖，`api_type` 被模型卡派生值覆盖，`stream` 在流式路径强制 True——写了不生效，是噪声 |
| `sub_agents/file_classifier/agent.yaml:llm_config` | 同上 | 同上 |
| `agent.yaml` 顶部 `${env.*}` 说明 | 「只保留 3 个必填的 `${env.LLM_*}`」→「只保留 1 个 `${env.LLM_MODEL}`」；补充「替换发生在 `yaml.safe_load` 之前」「只读 runtime scope」「沙箱脚本要用 sandbox scope」 | 随 llm_config 收敛同步；并纠正「${env.*} 读不到密钥」类旧说法——密钥分 runtime / sandbox 两条互不可见通路 |
| `agent.yaml` 自定义工具段注释 | 新增 `extra_kwargs` 与 `additionalProperties: false` 互斥的警告 | 这是 P0 级已实测复现的坑，而 `file_fingerprint.tool.yaml` 里恰好就有 `additionalProperties: false`——用户一加密钥就会中招 |
| `agent.yaml:skills` 段注释 | 新增运行时路径说明（`/home/user/.skills/<目录 basename>`，basename 决定路径、frontmatter `name` 决定 LoadSkill 调用名） | 原版没写，用户容易把两者混为一谈 |
| `agent.yaml:mcp_servers` 段注释 | 新增「NAC K8s 沙箱不解析 `host.docker.internal`；连不上不会加载失败但会白等 timeout」 | 原版只说「不需要就删」，没说不删的代价 |
| `systemprompt.md` 第 3 步 | `LoadSkill 加载 skills/archive-rules` → `LoadSkill 加载 archive-rules`，补 `/home/user/.skills/` 根目录与「以 `<SkillFolder>` 返回值为准拼路径」 | `skills/archive-rules` 是**源码目录**不是运行时路径，会误导模型去读不存在的路径；且 systemprompt 里显式出现 `/home/user/.skills/` 是平台静态校验器的要求 |
| `custom_tools/file_fingerprint.py` docstring | 补 `extra_kwargs` 互斥警告 + runtime/sandbox 两条密钥通路说明 | 同上，就近提醒 |
| `tools/file_fingerprint.tool.yaml:description` | 删掉「修改时间」 | 实现只返回 size / sha256 / mime，description 承诺了不存在的字段，会让模型误以为能拿到 mtime |
| `agent.yaml:max_running_subagents` 注释 + 本文「只读子代理」表 | 标注它是**空旋钮**（设了不改并发） | 原注释「最大并行子代理数」是错误承诺：这个值被存下来之后就再没有任何地方读它，与本 skill 的 `references/mcp-and-subagents.md` §5.6 自相矛盾 |
| `systemprompt.md` 第 3 行 | 删掉「（删减指南见 tutorial）」 | cookbook 教程不随模板分发，这句指向一个运行时不存在的文档，且它会随 systemprompt 进模型上下文 |
| `agent.yaml` 执行控制段 | **新增主 agent 的 `stop_tools: [ask_user]`**（+ 说明注释） | **真 bug**：原版主 agent 挂了 `ask_user` 却没登记 stop_tools——提完问不会停，模型会继续往下瞎跑（与子代理 `complete_task` 同一类问题）。平台静态校验器 `agent.stop_tools.required_for_tool` 硬拦 |
| `agent.yaml:middlewares[4]` RuntimeEnvironment | 把注释掉的 `# params:` 改成真实的 `params: {}`（`template` 一行仍保持注释） | 原版这条中间件整个 `params` 键缺失。校验器 `middlewares.entry.missing_key` 要求每个中间件条目必须同时有 `import` 和 `params`；全用默认值时写空字典 `{}` 即可 |
| `systemprompt.md` 第 3 步 skill 路径两行 | 措辞改成「部署后沙箱里的 skills 根目录位于 `/home/user/.skills/`，本 skill 即落在它下面的 `archive-rules/`」+「这只是默认落点，一律以 `<SkillFolder>` 为**权威路径**拼接」 | 校验器 `agent.system_prompt.required_pattern_missing` 用正则匹配「skills 根目录位于 `/home/user/.skills/`」这个固定说法，原措辞「Skill 部署后位于沙箱 …下」匹配不上；顺手把「默认落点 vs 权威路径」的主从关系讲明白 |
| **新增** `skills/archive-rules/references/INDEX.md` | 新写一份 references 目录导航索引（文件清单表 + 读法顺序） | 校验器 `skills.references.index_missing`：非空的 `references/` 必须有导航索引。⚠️ 索引文件名本 skill 统一用 `INDEX.md`（`SKILL.md` 是 skill 入口专用名，不该被知识库层级占用）；平台校验器的规则文件当前把 `index_file` 配成了 `SKILL.md`，属平台缺陷，会因此报这一条——见 ../../references/artifact-spec-checklist.md §8 |
| `custom_tools/__pycache__/` | 删除（含 `file_fingerprint.cpython-312.pyc`） | 编译产物不该进制品包，白占体积；`nexau.json:excluded` 只是打包端约定，平台不解析 |

**逐字保留、没有改的**（已逐项核对、当前仍正确）：所有 `binding` 串、11 个内置工具 schema、`tool_call_mode: structured`、执行控制七件套的默认值（`max_iterations` 100 / `max_context_tokens` 128000 / `max_running_subagents` 5 / `timeout` 300 / `retry_attempts` 5 / `retry_backoff_max_seconds` 30；⚠️ 默认值都对，但 `max_running_subagents` 的**语义**注释已改，见上表）、4 个中间件（LongToolOutput / RoundAndTokenReminder / ContextCompaction / RuntimeEnvironment）的 import 路径与全部参数默认值注释、`file_fingerprint.tool.yaml` 的 `additionalProperties: false`（本工具无 extra_kwargs，保留是对的）、`nexau.json`。

**`nexau.json` 的 `excluded` 字段**：平台**完全不解析**（backend 侧无任何读取），只是打包端约定。保留原样未动，但别对外宣称「平台会按 excluded 排除文件」——真正被平台消费的是 `agents` / `setup` / `backend` / `runtime.command`。

---

## 延伸

- `../../references/agent-yaml-fields.md` —— agent.yaml 字段契约与校验强度
- `../../references/builtin-tools.md` —— 内置工具清单与 binding
- `../../references/custom-tools.md` —— 自定义工具三件套、沙箱 API、`extra_kwargs`
- `../../references/llm-config.md` —— NAC 对 llm_config 的覆盖规则
- `../../references/env-vars-and-secrets.md` —— runtime scope vs sandbox scope
- `../_builtin-tool-yamls/` —— 官方内置工具 schema 全集（本模板 `tools/` 下的都来自这里）
- 相关模板：`01-agentic-rag`（Skill/RAG 深挖）、`04-mcp-server`（MCP 完整版）、`07-doc-generation`（PDF/多模态）、`09-content-guardrail`（护栏）
