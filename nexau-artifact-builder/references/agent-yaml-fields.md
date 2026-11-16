# agent.yaml 完整字段参考

> **本文覆盖**：`agent.yaml` 顶层字段全集（类型 / 必填 / 默认值）、各嵌套条目模型的字段、
> **校验强度分层**（哪些字段拼错会报错、哪些静默失效）、`system_prompt_type` 三值的真实行为、
> Jinja 模板上下文变量全集，以及顶层 `variables:` 宏与运行时 `variables` 的区别。
> **什么时候读**：写或改 agent.yaml 时查字段；agent 加载期报 `ConfigError` 时；
> 「明明写了却不生效」时（多半命中 §6 的静默失效）。
>
> 相关：`llm_config` 详见 `llm-config.md`；`tools` 条目详见 `builtin-tools.md` / `custom-tools.md`；
> `mcp_servers` / `sub_agents` 详见 `mcp-and-subagents.md`；`middlewares` 详见 `middlewares.md`。
>
> 事实源：框架侧的 agent 配置模型 `AgentConfigBase` 与 YAML 顶层校验模型 `AgentConfigSchema` 的实际行为。

---

## 1. 顶层字段全集

以 `AgentConfigBase` + `AgentConfigSchema` 对它的重声明为准。

### 1.1 身份

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `type` | `Literal["agent"] \| None` | ❌ 框架层可省 / ✅ 规范必写 | `None` | 框架层**可省略**，写了必须严格等于 `agent`；但**官方制品规范要求必写且值为 `agent`**（见 `artifact-spec-checklist.md` §2） |
| `name` | `str \| None` | ❌ | `None` | schema 层不强制；不写时 builder 兜底成 `"configured_agent"`。**实践上必写**——子代理靠它被调用、日志/trace 靠它区分 |
| `description` | `str \| None` | ❌ | `None` | 作为子代理时，父 agent 靠它决定要不要委派 |
| `source_id` | `str \| None` | ❌ | `None` | 组件来源标记，plugin 体系用；手写制品不用管 |

### 1.2 系统提示词

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `system_prompt` | `str \| list[str \| SystemPromptBlock] \| None` | ❌ | `None` | 内容本身或文件路径，取决于 `system_prompt_type` |
| `system_prompt_type` | `Literal["string","file","jinja"]` | ❌ | **`"string"`** | 见 §3。⚠️ 默认是 `string`，要读文件必须显式写；`jinja` 与 `file` 框架层等价，但**官方规范只认 `jinja`**（`artifact-spec-checklist.md` §2） |
| `system_prompt_suffix` | `str \| None` | ❌ | `None` | 追加到系统提示词末尾的固定后缀 |

### 1.3 能力装配

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `tools` | `list[Any]` | ❌ | `[]` | 条目字段见 §4.1。⚠️ **条目不做 schema 校验**，见 §6 |
| `skills` | `list[Any]` | ❌ | `[]` | 条目可以是**字符串路径**（最常见）或 `{name, path}` 对象（builder 两种都处理）。⚠️ 同样不做条目校验 |
| `sub_agents` | `list[SubAgentConfigEntry] \| None` | ❌ | `None` | 条目 `extra='forbid'` **真生效**，见 §4.2 |
| `mcp_servers` | `list[MCPServerConfig]` | ❌ | `[]` | 判别式联合，`extra='forbid'` **真生效**，见 §4.3 |
| `llm_config` | `dict \| None` | ✅ **顶层 key 必填** | — | `None` 直接报 `llm_config is required in agent configuration`。内部字段**零校验**，见 §5 与 `llm-config.md` |
| `sandbox_config` | `dict \| None` | 🚫 别写 | `None` | 平台注入是「你没写才注入」，你写了平台就不注入 → 沙箱基本必炸。见 `llm-config.md` §1 |
| `plugins` | `list[PluginEntryConfig]` | ❌ | `[]` | plugin 体系，手写制品一般用不到 |

### 1.4 执行控制

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `tool_call_mode` | `str` | ❌ | `"structured"` | 合法值见 §7 |
| `max_iterations` | `int` (ge=1) | ❌ | **`100`** | 单次任务最多迭代轮数。schema 默认 100；**该给多大是装配取舍**，见 §1.4a |
| `max_context_tokens` | `int` (ge=1) | ❌ | **`128000`** | 上下文窗口上限 |
| `max_running_subagents` | `int` (ge=0) | ❌ | **`5`** | ⚠️ **当前是空旋钮**，见 `mcp-and-subagents.md` |
| `retry_attempts` | `int` (ge=0) | ❌ | **`5`** | LLM 调用失败重试次数 |
| `retry_backoff_max_seconds` | `int` (ge=1) | ❌ | **`30`** | 重试最大退避秒数 |
| `timeout` | `int` (ge=1) | ❌ | **`300`** | ⚠️ **当前未接线的死配置**，见 §8 |
| `stop_tools` | `set[str] \| None` | ❌ | `set()` | 命中即终止 agent 循环的工具名集合。YAML 里写 list，加载期会被转成 set。⚠️ **必须显式声明**，见 `mcp-and-subagents.md` |

#### 1.4a 装配建议：`max_iterations` 该给多大（**约定，不是 schema 约束**）

> 这一节是**写制品时的取值建议**，不写也能部署、也能跑——schema 只要求 `ge=1`。
> 它值得单独讲，是因为这个值给小了会**在用户看得见的地方**截断任务。

**给小了的表现不是静默的**：撞上限时 executor 会给 `AgentStopReason.MAX_ITERATIONS_REACHED`，
并在最终回复末尾拼一句 `[Error: Maximum iteration limit reached.]`（常见路径；另有收尾路径拼的是
`[Note: Maximum iteration limit reached]`，两者前面都是字面 `\n\n` 四个字符）。run 状态不会变成失败。所以「Agent 干到一半停了、末尾挂着一句 limit reached」= 这个值不够用。

**给大了不是免费的**，三笔代价：

1. **一轮 = 一次完整 LLM 调用**，token 与耗时随上限线性放大；跑飞的 Agent 会一直烧到撞顶。
2. **和网关 300s 非流式整请求超时直接撞车**（见 §8）。上限开大只是把「提前收尾」换成
   「被网关掐断、客户端什么都拿不到」——**长任务真正的解法是 `"stream": true`，不是把上限调高**。
3. 挂了 `RoundAndTokenReminderMiddleware` 时，「还剩几轮」的收敛提示只在 `remaining ≤ 3` 才转成
   催收口吻。上限极大时模型看到的永远是
   `Iteration 5/500 - Continue your response…`，等于告诉它「随便兜」。

> 📌 **真正的停机手段是 `stop_tools`**（子代理的 `complete_task`、`ask_user` 等，见 `mcp-and-subagents.md`）。
> `max_iterations` 是 runaway 兜底，不是流程控制手段——靠调大它来「让 Agent 干完活」是把因果搞反了。

**取值参考**（估法：先估「最坏情况下要连着调几次工具」，再 ×2~3 留冗余）：

| 场景 | 建议 | 理由 |
|------|------|------|
| 纯问答 / 单工具直答 | **20–50** | 一问一答 + 少量工具，撞不到上限 |
| 知识库多跳检索（Agentic Search、逐层读文件） | **50–100** | 一次问答读 10+ 文件时靠上限 |
| 文档流水线（解析 → 结构化 → 渲染） | **100–150** | 阶段多但每阶段步数可数 |
| 多步审核 / 多子代理委派 / text-to-SQL 反复试错 | **150–300** | 试错和委派都会成倍放大轮数 |
| 自动生成 + 自我 refine / verify 循环 | **500** | 平台 A4A 生成制品的约定值（A4A 自身 agent.yaml 用的是 10000）——**这类「机器生成、跑满迭代是常态」的场景才需要这么大** |

⚠️ **别无脑照抄 500**。它是给「自动生成 + 多轮 refine/verify」定的，对一个客服问答 Agent 只会放大
上面三笔代价。本 skill 各模板现用 **50 / 80 / 100 / 300**（`templates/*/agent.yaml`），都是按上表估过的，**不要去改模板**。

### 1.5 状态与上下文

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `context`（别名 `initial_context`） | `dict \| None` | ❌ | `None` | **注入 Jinja 模板的自定义变量**，见 §3.2。两个名字互为别名，都能写 |
| `global_storage` | `dict` | ❌ | `{}` | 静态初始键值，Agent 初始化时灌进运行时 `GlobalStorage`，供工具/中间件经 `agent_state.global_storage` 读写 |
| `initial_state` / `initial_config` | `dict \| None` | ❌ | `None` | 初始状态/配置，普通制品少用 |

### 1.6 钩子与观测

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `middlewares` | `list[HookDefinition] \| None` | ❌ | `None` | 见 `middlewares.md` |
| `before_model_hooks` / `after_model_hooks` | `list[HookDefinition] \| None` | ❌ | `None` | 模型调用前/后钩子 |
| `before_tool_hooks` / `after_tool_hooks` | `list[HookDefinition] \| None` | ❌ | `None` | 工具调用前/后钩子 |
| `tracers` | `list[HookDefinition]` | 🚫 别写 | `[]` | 运行期平台 tracer 与你自带的是**合并**关系（功能上能用），但**官方制品规范把它列为禁写字段**（与 `sandbox_config` 并列判 error）。结论：别写。见 `artifact-spec-checklist.md` §3 |
| `token_counter` | `HookDefinition \| None` | ❌ | `None` | 自定义 token 计数器 |
| `error_handler` | `Callable \| None`（**纯 Callable，无 str / import 分支**） | 🚫 **YAML 写不了** | `None` | 只能在 Python 侧赋值。YAML 里写 `'my.mod:handler'` 或 `{import: ...}` 都会 pydantic 硬失败：`error_handler: Input should be callable`（`AgentConfigSchema` **未重声明**它——同表其余钩子都被重声明成 `HookDefinition`，所以只有它写不了） |
| `skipped_components` | `list[str]` | ❌ | `[]` | 加载期被跳过的组件名，框架回填，别手写 |

> ⚠️ 本表两行 🚫 的原因**完全不同**，排障动作也不同：
> `tracers` 是**能写但规范禁写**（删掉即合规）；`error_handler` 是**框架层根本写不了**
> ——一看到 `Input should be callable` 就别再换写法试了，YAML 侧无解。

`HookDefinition` 结构：

```yaml
- import: <python 模块路径>:<类名或函数名>
  params: { ... }        # 传给构造函数的关键字参数
```

---

## 2. 一份完整的 agent.yaml（各字段就位的样子）

```yaml
type: agent
name: my_agent
description: 一句话说明这个 Agent 干什么

system_prompt: ./systemprompt.md
system_prompt_type: jinja

llm_config:
  model: ${env.LLM_MODEL}
  max_tokens: 8192
  temperature: 0.2

# 注入 systemprompt 的自定义 Jinja 变量（模板里用 {{ org_name }}）
context:
  org_name: 某某局
  hotline: "12345"

tools:
  - name: read_file
    yaml_path: ./tools/read_file.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:read_file

skills:
  - ./skills/my-domain          # 字符串形式（最常见）

sub_agents:
  - name: worker
    config_path: ./sub_agents/worker/agent.yaml

mcp_servers:
  - name: my_service
    type: http
    url: https://mcp.example.com/mcp
    timeout: 30

middlewares:
  - import: nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware
    params:
      threshold: 0.6

tool_call_mode: structured
max_iterations: 50
max_context_tokens: 128000
stop_tools: [complete_task]
```

---

## 3. `system_prompt_type` 的真实行为

### 3.1 三个值都走 Jinja2，区别只在「读不读文件」

系统提示词渲染时的实际行为：

| 值 | 行为 |
|---|------|
| `jinja` | 把 `system_prompt` 当**文件路径**读取，再 Jinja2 渲染 |
| `file` | **与 `jinja` 完全等价** —— 实现里两者共用同一分支 |
| `string`（默认） | 把 `system_prompt` 的**内容本身**当 Jinja2 模板字符串渲染 |

⚠️ **纠正两个常见误解**：

- 「`string` 就是纯静态文本」——错。`string` 下内联字符串**同样支持 `{{ }}` 语法**，只是不读文件。
- 「必须用 `jinja` 才能读文件」——不准确。`jinja` 和 `file` 都读文件，代码层等价。
  本 skill 统一约定写 `jinja`（语义更直白）。

> 💡 框架里还残留着一套用 Python `str.format()` 的 `{var}` 单花括号语法的旧提示词处理路径
> ——**在当前调用路径下完全没被使用**，是死代码。写模板一律用 Jinja 的 `{{ }}`，别参考带单花括号的旧样例。

### 3.2 Jinja 上下文变量全集

四个来源。**按合并机制理解，而不是背顺序**：渲染时先造出 **② Agent 元信息** 当基底，
随后被另外三层**整体覆盖**——那三层在传进渲染之前就已经被压成同一个 dict，
其内部优先级从低到高是：**① 框架运行时事实** < **③ `context:`** < **④ `variables.template`**。

⚠️ **真实优先级是 ② < ① < ③ < ④ —— Agent 元信息最低**，任何一层的同名键都会盖掉它。
今天四组键零交集所以看不出差别，但你若在 `context:` 里定义 `agent_name` / `timestamp`，
生效的是**你的值**。

**① 框架运行时事实**

| 变量 | 内容 |
|------|------|
| `{{ date }}` | 当天日期（`%Y-%m-%d`） |
| `{{ username }}` | 当前用户名 |
| `{{ working_directory }}` | 工作目录（沙箱 `work_dir`，NAC 上通常是 `/home/user`） |
| `{{ operating_system }}` | `platform.platform()` 全串 |
| `{{ platform }}` | `sys.platform`（如 `linux`） |
| `{{ shell_tool_backend }}` | shell 工具后端（沙箱 vs 本地） |
| `{{ shell_tool_guidance }}` | 该后端的使用提示文本 |
| `{{ env_content }}` | 上面 7 项打包成的 dict（可 `{{ env_content.date }}` 这样用） |

**② Agent 自身元信息**——**优先级最低的基底**，
下面 4 个变量都可被 `context:` / `variables.template` 的同名键覆盖

| 变量 | 内容 |
|------|------|
| `{{ agent_name }}` | agent 的 `name` |
| `{{ agent_id }}` | agent 实例 id |
| `{{ timestamp }}` | 渲染时间戳 |
| `{{ system_prompt_type }}` | 当前的 `system_prompt_type` 值 |

**③ agent.yaml 顶层 `context:`（= `initial_context`）** —— 你自己定义的任意 key。
**这是最常用的定制点**：把机构名、热线、业务参数写进 `context:`，systemprompt 里 `{{ org_name }}` 引用。

**④ 运行时 `variables.template`** —— chat 请求里按次传入，**优先级最高**，会覆盖同名的 `context:` 值。
详见 `env-vars-and-secrets.md` 的 variables 三通道。

---

## 4. 嵌套条目模型

### 4.1 `tools[]` —— builder 实读键集（**≠ `ToolConfigEntry`**）

⚠️ 条目在 schema 层是 `list[Any]`，`ToolConfigEntry` **根本不参与校验**，
只是个命名参考——照它抄会漏掉 `permissions`（它不在 `ToolConfigEntry` 里，但 builder 真读）。
下表以 builder 加载工具条目时**实际读的键**为准。

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `name` | `str` | ✅ | — | **LLM 看到的工具名**；会覆盖 `.tool.yaml` 里的 `name`。缺失 → `ConfigError` |
| `yaml_path` | `str` | ✅ | — | `.tool.yaml` 路径，**相对当前 agent.yaml 所在目录**。缺失 → `ConfigError` |
| `binding` | `str \| None` | ❌ 框架层可省 / ✅ 规范必填 | `None` | `模块路径:函数名`，**import 根是制品根目录**（与 `yaml_path` 基准不同！见 `custom-tools.md`）。框架层不写会回落到 `.tool.yaml` 里的 `binding`；**官方规范要求每个工具条目都显式写** |
| `lazy` | `bool` | ❌ | `False` | 延迟加载实现。⚠️ 未写时 builder 传的是 `False`（不是 `None`），会**无声覆盖** `.tool.yaml` 里的 `lazy: true`，见 `builtin-tools.md` §7 |
| `as_skill` | `bool` | ❌ | `False` | 把这个工具也暴露成 skill（触发 `LoadSkill` 自动注入） |
| `defer_loading` | `bool` | ❌ | 未写 → `None` → **回落 `.tool.yaml`** | 延迟加载定义（触发 `ToolSearch` 自动注入）。与 `lazy` 的覆盖行为**不对称** |
| `extra_kwargs` | `dict` | ❌ | `{}` | 注入给函数、**模型看不见**的参数（密钥走这里）。⚠️ 与 `additionalProperties: false` 互斥，见 `custom-tools.md` |
| `permissions` | `dict[str, list[str]]` | ❌ | `None` | per-tool allow/deny 白名单。**不在 `ToolConfigEntry` 里，官方规范也不禁**，但 builder 真读 → 落到 `Tool.permissions` → executor 据此建权限缓存。非 dict → `ConfigError`。⚠️ **不写 = 回落 `["**"]` 全放行；一旦写了，未命中 allow 的调用会走 ask 分支**——语义与风险同 §4.3，先读 `mcp-and-subagents.md` §3.7 再决定要不要写 |
| `source_id` | `str \| None` | ❌ | `None` | 来源标记 |

### 4.2 `sub_agents[]` — `SubAgentConfigEntry`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | `str` | ✅ | 调用标识；**覆盖**子 agent yaml 里自己的 `name` |
| `config_path` | `str` | ✅ | 子 agent 的 agent.yaml 路径，相对当前 agent.yaml 目录 |
| `source_id` | `str \| None` | ❌ | 来源标记 |

`extra='forbid'` **真生效**：多余字段直接
`Invalid agent configuration: sub_agents->0->bogus_field: Extra inputs are not permitted`。

### 4.3 `mcp_servers[]` — `MCPServerConfig`

三型共享字段（`MCPServerBaseModel`）：

| 字段 | 类型 | 必填 | 默认 |
|------|------|------|------|
| `name` | `str` | ✅ | — |
| `timeout` | `int` (gt=0) | ❌ | `None` |
| `env` | `dict[str,str]` | ❌ | `None` |
| `disable_parallel` | `bool` | ❌ | `False` |
| `permissions` | `dict[str, list[str]]` | ❌ | `None` ⚠️ **别填** —— 见 `mcp-and-subagents.md` §3.7 |
| `tool_permissions` | `dict[str, dict[str,list[str]] \| None]` | ❌ | `None` ⚠️ **别填** —— 同上 |
| `source_id` | `str \| None` | ❌ | `None` |

各型专有字段：

| `type` | 专有必填 | 专有可选 |
|--------|---------|---------|
| `stdio` | `command: str` | `args: list[str]` |
| `http` | `url: str` | `headers: dict[str,str]` |
| `sse` | `url: str` | `headers: dict[str,str]` |

⚠️ `type` 技术上可省略（pydantic 按字段形状推断并回填默认值），但这是隐藏行为——**始终显式写**。
配置细节与部署坑见 `mcp-and-subagents.md`。

### 4.4 `skills[]` — 字符串或 `SkillConfigEntry`

```yaml
skills:
  - ./skills/my-domain              # ✅ 字符串形式 —— 官方规范只允许这一种
  # - { name: alias, path: ./skills/other }   # 对象形式：框架支持，但规范判不合规
```

⚠️ 官方规范 `required_skill_entry_kind: "string_path"` —— **`skills[]` 条目必须是字符串路径**。
对象形式（`{name, path, source_id}`）框架能跑，但不符合规范。见 `artifact-spec-checklist.md` §7.1。

---

## 5. `llm_config` 的校验（零校验）

`LLMConfig` **不是 pydantic 模型**，是普通 Python 类，
构造时用 `**kwargs` 把所有未知字段吞进 `extra_params`。

后果：**`llm_config:` 块里写错字段名不会报错，也不会生效**——它静静躺在 `extra_params` 里。

`llm_config` 内每个字段在 NAC 上的真实命运（哪些会坏、哪些被覆盖）见 **`llm-config.md`**，本文不重复。

---

## 6. ⚠️ 校验强度分层（本文最该记住的一节）

`agent.yaml` **不是均匀严格校验的**。拼错字段名有时炸、有时静默失效，直接决定你怎么排障。

| 层 | 校验强度 | 拼错的后果 |
|---|---|---|
| **顶层 key** | 🔴 严格 `extra='forbid'` | `ConfigError: Invalid agent configuration: <key>: Extra inputs are not permitted` |
| **`sub_agents[]` 条目** | 🔴 严格 | `sub_agents->0->bogus_field: Extra inputs are not permitted` |
| **`mcp_servers[]` 条目** | 🔴 严格 | 联合类型逐分支报错 |
| **`tools[]` 条目** | ⚠️ **几乎不校验** | **静默忽略，不报错、不进 `skipped_components`** |
| **`skills[]` 条目** | ⚠️ **几乎不校验** | 同上 |
| **`llm_config` 内部** | ⚪ 零校验 | 吞进 `extra_params`，不报错不生效 |

### 为什么 tools/skills 不校验

`ToolConfigEntry` / `SkillConfigEntry` **确实**声明了 `extra='forbid'`，但 `AgentConfigBase`
把 `tools` / `skills` 两个字段的类型写死成了 `list[Any]`——**为它们准备的泛型参数声明了、却没用在字段注解上**；
对照之下 `sub_agents` 真用了泛型，所以只有它是严格的。

于是列表项根本不经过条目模型校验：**你写的键名框架不认识时，会被静默忽略**——
不报错、不进 `skipped_components`，这才是拼写陷阱的来源。

但「不校验」≠「什么都不查」：builder 对**已知键的值**仍有 **7 条硬校验**，命中即加载期
`ConfigError`（缺 `name` / 缺 `yaml_path` / `lazy` 非 bool / `defer_loading` 既非 null 也非 bool /
`extra_kwargs` 非 dict / `extra_kwargs` 含保留键 `agent_state`·`global_storage` / `permissions` 非 dict）。
**完整清单见 `builtin-tools.md` §8 结尾的 `tools` 条目硬失败表**（唯一事实源，本文不重抄）。

一句话分工：**键名拼错 = 静默；键名对但值的类型错 = 硬失败。**

**实践含义**：调试「`extra_kwargs` 没传进去 / 这个工具怎么没生效 / `as_skill` 不起作用」时，
**第一件事是逐字核对 `tools:` 条目的字段拼写**，别去翻框架源码——它不会告诉你拼错了。

> 常见的静默失效：`extra_kwarg`（漏 s）、`yamlpath`、`as_skills`、`defer_load`。

---

## 7. `tool_call_mode`

| 输入值 | 实际生效 | 说明 |
|--------|---------|------|
| `structured` | `structured` | **默认值**，推荐 |
| `xml` | `xml` | 另一种真实模式 |
| `openai` | `structured` | ⚠️ 历史遗留别名，会打一次性 warning 后归一化 |
| `anthropic` | `structured` | ⚠️ 同上 |
| 其它 | `ValueError` | `tool_call_mode must be one of 'xml', 'structured', 'openai', or 'anthropic'` |

**对外真实语义只有 `xml` / `structured` 两个值**。provider 的具体 wire 格式由 `llm_config.api_type`
决定（`openai_chat_completion`/`openai_responses`/`generate_with_token` → openai；
`anthropic_chat_completion` → anthropic；`gemini_rest` → gemini），**不由 `tool_call_mode` 推断**。

看到旧样例写 `tool_call_mode: openai` 就改成 `structured`。

---

## 8. ⚠️ 超时有三层，顶层 `timeout` 是死配置

| 层 | 管什么 | 生效吗 | 为什么 |
|---|---|---|---|
| agent.yaml 顶层 `timeout`（默认 300） | 名义上是 agent 执行时长 | ❌ **死配置** | 这个值确实流进了执行配置，但 Agent 装配 executor 时**根本没有把它传下去**——executor 的构造签名里压根没有 `timeout` 这个参数 |
| `llm_config.timeout` | **单次 LLM 请求** | ✅ | 见 `llm-config.md` |
| **网关整请求超时**（`NEXAU_AGENT_GATEWAY_REQUEST_TIMEOUT_SECS`，默认 **300s**） | 一次 `/agent-api/chat` 调用的**总时长**，**仅非流式** | ✅ **最容易先掐断的一环** | 非流式请求走一个带超时的 HTTP 客户端；流式走另一个**不设超时**的客户端。默认 300s，生产环境也是 300 |

**实践含义**：`max_iterations` 开大（默认 100，模板里有开到 300 的）+ 请求体 `"stream": false`，
两个值一撞，长任务会在 ~5 分钟处被网关掐断，而 pod 和 trace 里 agent 还在跑。
**解法是把请求改成 `"stream": true`（流式路径无整请求超时），不是去调 agent.yaml 的 `timeout`——那个改了没用。**
（`max_iterations` 本身该给多大见 §1.4a——注意**调大它并不能绕开这 300s**。）
chat 路由在入口网关上的读超时是 3600s，不会先于网关掐，所以网关这 300s 就是非流式的真上限。

讲「超时怎么配」时务必区分这三层。

（框架侧行为所对应的 NexAU SDK 版本号未核，见 SKILL.md 开头。）

---

## 9. 顶层 `variables:` 宏 vs 运行时 `variables`

**两个同名但毫无关系的机制，最容易混。**

### 9.1 顶层 `variables:` —— 加载期文本宏

```yaml
variables:
  max_tokens: 8000
  db: { host: pg.internal }     # 只能引用到标量叶子

llm_config:
  max_tokens: ${variables.max_tokens}
```

机制：

- 在 **`yaml.safe_load` 之前**对原始文本正则替换 `${variables.a.b}`
- **只支持标量值**（引用到 dict/list 会报错）
- 替换完 `variables` key 被 `pop` 掉，**`AgentConfigSchema` 永远看不到它**
  （所以它不在 §1 的字段表里，也 `hasattr(cfg, 'variables') == False`）
- ⚠️ **注释里的 `${variables.x}` 一样会被解析**（替换在 load 之前）
- ⚠️ **不跨文件继承**：子代理 yaml 要自己再写一份
- ⚠️ 只在真正从 `.yaml` 文件加载时生效（`AgentConfig.from_yaml` / `AgentConfigSchema.from_yaml`）；
  `AgentConfig.from_dict()` 不走这条路

### 9.2 运行时 `variables` —— chat 请求的三通道

`ContextValue` 的三个通道：

| 通道 | 去处 |
|------|------|
| `template` | 合并进 Jinja 渲染上下文（§3.2 的 ④，优先级最高） |
| `runtime_vars` | 不进 prompt，走 `agent_state.get_variable()` |
| `sandbox_env` | 注入沙箱进程的环境变量 |

详见 `env-vars-and-secrets.md`。

### 9.3 对照

| | 顶层 `variables:` | 运行时 `variables` |
|---|---|---|
| 出现位置 | agent.yaml 里 | chat 请求 body / Playground 面板 |
| 生效时机 | 加载期一次性文本替换 | 每次请求 |
| 引用语法 | `${variables.x}`（yaml 文本里） | `{{ x }}`（Jinja）或 `agent_state.get_variable()` |
| 能改吗 | 改了要重新部署 | 按请求变 |

---

## 10. 与 `${env.X}` 的关系

`${env.X}` 是**另一套**加载期文本替换，与 `${variables.x}` 并列但独立：

- 只读 **runtime pod** 的环境变量，**不新增任何进程环境变量**
- **未设置 = 加载期 `ConfigError` 硬失败**
- **注释里的一样会被解析**；不支持 `${env.X:-default}` 默认值语法，不支持转义

完整语义与三条密钥通路见 **`env-vars-and-secrets.md`**。
