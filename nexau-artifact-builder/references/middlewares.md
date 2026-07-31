# Middlewares（中间件）

> **本文覆盖什么**：agent.yaml 里 `middlewares:` 的全部 7 个框架自带中间件——完整 import 串、每个参数的名/类型/默认值/是否必填、可直接抄的配置片段、执行顺序（洋葱模型）、报错形态，以及内容安全护栏 `SensitiveWordMiddleware` 专章。
> **什么时候读它**：要给制品加「上下文压缩 / 长工具输出截断 / 轮次提醒 / LLM 降级 / 敏感词拦截」时；或 agent 启动即报 `ConfigError: Error instantiating hook ...` / `Module ... has no attribute ...` 时。
> 不覆盖：agent.yaml 其他字段（见 `references/agent-yaml-fields.md`）、自定义中间件的 Hook 接口开发。

代码事实源：`nexau/archs/main_sub/execution/middleware/`（下文简称 `middleware/`）、`nexau/archs/main_sub/config/config.py`、`.../execution/hooks.py`。

> 🚨 **先读这条，否则照本文抄配置必被判不合规。**
> 本文讲的是**框架层能力**（7 个中间件、全部参数）。但**平台官方制品规范的中间件白名单只放行 2 个**：
> `ContextCompactionMiddleware`（仅允许 `threshold` 一个参数）和 `LongToolOutputMiddleware`
> （**一个参数都不允许**，只能写 `params: {}`）。用其余 5 个、或给 LongToolOutput 带参数，
> 静态校验器会报 `middleware.not_allowed` / `middleware.params.unexpected`。
>
> ⚠️ **这不是「规范滞后」，是平台有意收窄**：散文规范 `artifact-hard-rules.md` §5.1 标题就叫
> 「不允许自由创新」。所以用白名单外的中间件 = **有意偏离官方规范**，是个需要你承担的取舍：
> 政企合规场景确实可能必须上 `SensitiveWordMiddleware` 护栏，那就有意偏离并向交付方说明；
> 但只是想调调 `LongToolOutputMiddleware` 参数的，**优先写 `params: {}` 用默认值**。
> 判读口径与白名单全文见 `references/artifact-spec-checklist.md` §9.3。
> 另：`middlewares[]` 每个条目**必须同时有 `import` 和 `params`**，没参数也要写 `params: {}`。

---

## 0. 30 秒速查

| 你的场景 | 加什么 | 必须给的参数 |
|---|---|---|
| 长对话 / 多轮会话会撑爆上下文 | `ContextCompactionMiddleware` | 至少给一个 param（空 `params` 直接报错） |
| Agent 会读大文件 / 跑长输出命令 | `LongToolOutputMiddleware` | 全部可选 |
| 长流程、要让模型知道「还剩几轮」 | `RoundAndTokenReminderMiddleware` | `max_context_tokens`（**真必填**） |
| 主 LLM 网关会挂，要自动切备用 | `LLMFailoverMiddleware` | `fallback_providers`（必填） |
| 想让模型知道 cwd / OS / shell 后端 | `RuntimeEnvironmentMiddleware` | 全部可选 |
| 政企合规：拦敏感词 | `SensitiveWordMiddleware` | `lexicon_dir` / `lexicon_file` / `lexicon_words` 三选一（必填） |
| 流式事件回调 | ❌ 别写 —— NAC 平台已自动注入 `AgentEventsMiddleware` |

> 上表前两行在官方白名单内，其余「加什么」列出的中间件都会报 `middleware.not_allowed`（见顶部 🚨 与 `references/artifact-spec-checklist.md` §9.3）。

**不需要的整段删掉。** `middlewares:` 字段本身可以完全不写（默认 `None`）。

声明骨架：

```yaml
middlewares:
  - import: <module.path>:<ClassName>
    params:
      key: value
```

---

## 1. 声明语法与 import 硬规则

### 1.1 ⚠️ import 路径必须带 `execution` 层，且必须写到**具体模块文件**

这是最高频的启动失败原因。

```
✅ nexau.archs.main_sub.execution.middleware.long_tool_output:LongToolOutputMiddleware
❌ nexau.archs.main_sub.middleware.long_tool_output:LongToolOutputMiddleware   # 少了 execution
❌ nexau.archs.main_sub.execution.middleware:LongToolOutputMiddleware          # 少了模块文件
❌ nexau.archs.main_sub.execution.middleware.long_tool_output.LongToolOutputMiddleware  # 用了 . 不是 :
```

机制（已实测核实）：

- `middleware/` 目录**没有 `__init__.py`**（`ls` 确认），是 Python 3 namespace package。实测 `importlib.import_module("nexau.archs.main_sub.execution.middleware")` 成功但 `__file__ is None`、`__dict__` 里没有任何中间件类 → 写到目录级必失败。
- 分隔符必须是 `:`，不是 `.`：`utils/common.py:32-35` `if ":" not in import_string: raise ValueError("Import string must contain ':' separator")`；随后 `module.__dict__.get(attr_name)`（`common.py:52-53`）。
- ⚠️ **抛出的异常类型是 `ConfigError`，不是 `AttributeError` / `ModuleNotFoundError`**：`common.py:66-76` 把三类底层异常统一转包。实测四种错法的真实报错原文（用于 grep）：

| 错法 | 实测报错（`ConfigError` 的 message） |
|---|---|
| 写到目录级 | `Could not import attribute from '<串>': Module 'nexau.archs.main_sub.execution.middleware' has no attribute 'LongToolOutputMiddleware'` |
| 少 `execution` 层 | `Could not import module from '<串>': No module named 'nexau.archs.main_sub.middleware'` |
| 用 `.` 不用 `:` | `Error importing from '<串>': Import string must contain ':' separator` |
| 类名拼错 | 同「写到目录级」那条，`has no attribute '<你写的类名>'` |

- **唯一例外**：`context_compaction/` 是真包（有 `__init__.py`，`context_compaction/__init__.py:24` re-export 了 `ContextCompactionMiddleware`），所以目录级和文件级两种写法都能跑：
  - `...execution.middleware.context_compaction:ContextCompactionMiddleware` ✅（推荐，最短）
  - `...execution.middleware.context_compaction.middleware:ContextCompactionMiddleware` ✅

### 1.2 条目 schema：只允许 `import` 和 `params` 两个键

`config/base.py:41-47` `HookImportConfig`，`model_config = ConfigDict(extra="forbid", populate_by_name=True)`：

```yaml
middlewares:
  - import: ...            # 必填，str
    params: {...}          # 可选，mapping
  - ...同一个 import 串的裸字符串形式也合法（无参数时）
```

写第三个键（如 `name:` / `enabled:` / `source_id:`）会在 schema 校验阶段直接 `ValidationError` → `ConfigError: Invalid agent configuration`（`config.py:250-252` from_dict / `schema.py:173-175` from_yaml 各自转包）。这与 `tools:` 条目「多余键静默忽略」的行为**相反**，别混。

已实测（`AgentConfigSchema.model_validate`）：

| 条目写法 | 结果 |
|---|---|
| `{import: ..., params: {...}}` | ✅ 解析为 `HookImportConfig` |
| 裸字符串 `"mod:Cls"` | ✅ |
| 多写任意第三个键 | ❌ `ValidationError`（`middlewares.0.HookImportConfig.<键> Extra inputs are not permitted`） |
| `params` 不是 mapping（如列表） | ❌ `ValidationError` |

### 1.3 ⚠️ 相对路径参数的解析规则不统一

`config/config.py:512-519`：只有**键名以 `_path` 或 `_file` 结尾**的字符串参数，才会把相对路径解析成「相对 agent.yaml 所在目录」：

```python
for k, v in params.items():
    if isinstance(v, str) and (k.endswith("_path") or k.endswith("_file")):
        p = Path(v)
        if not p.is_absolute():
            v = str(self.base_path / p)
```

| 参数 | 相对路径怎么解析 |
|---|---|
| `compact_prompt_path`、`lexicon_file` | ✅ 自动按 agent.yaml 目录解析（本 skill 约定 agent.yaml 在制品根，官方规范 `required_top_level_files` 也要求它在顶层，所以基准就是 `/agent/`） |
| `lexicon_dir`、`temp_dir` | ❌ **不解析**，按进程 CWD 解析 —— 必须写绝对路径（如 `/agent/lexicon`） |

### 1.4 中间件构造失败 = agent 启动失败（默认 strict）

`config.py:667-684` 的 `build_hooks()` 里每个中间件套了 `try/except Exception` → `_handle_component_error()`（`config.py:468-477`）：

- `strict=True`（`AgentConfigBuilder.__init__` 默认，`config.py:452`；`AgentConfig.from_yaml` 走 `AgentConfigLoadOptions` 默认 `strict=True`，`config/base.py:37`；NAC agent-runtime 未覆盖此项）→ 直接 `raise ConfigError(f"Skipped middleware {i}: {e}")`，整个 agent 加载失败。
- 只有显式 `strict=False` 才会「warning + 跳过该中间件继续跑」——那种情况下护栏会静默消失。制品默认路径不会遇到。

所以：**中间件参数写错 = pod 启动就挂，不是运行时才发现**。日志里找 `Skipped middleware <i>:` 这行拿根因。

### 1.4b ⚠️ 但「运行期」异常相反：被吞成一条 warning，请求照常返回

构造期失败是硬失败；**hook 真正执行时抛的异常，`MiddlewareManager` 全部 `try/except` 掉，只打 `logger.warning` 然后继续下一个中间件**：

| 阶段 | 吞异常？ | 证据 |
|---|---|---|
| `before_agent` / `before_model` / `after_model` / `before_tool` / `after_tool` / `stream_chunk` | ✅ 吞，打 `⚠️ <阶段> middleware <obj> failed: <exc>` | `hooks.py:662-663`、`718-719`、`755-756`、`800-801`、`780-781`、`843-844` |
| `wrap_model_call` / `wrap_tool_call` | ❌ 不吞，异常向上冒 | `hooks.py:804-819`、`847-862` |

**排障含义**：护栏（敏感词）/ 压缩「装了但好像没起作用」时，除了查配置，还要 grep 启动后的运行日志里有没有 `⚠️ Before-model middleware ... failed:` —— 它不会让请求变红，只会让功能静默消失。

### 1.5 ⚠️ `extra=forbid` 只对 ContextCompactionMiddleware 成立

| 中间件 | 传错参数名时的报错 |
|---|---|
| `ContextCompactionMiddleware` | **pydantic** `ValidationError: ... Extra inputs are not permitted`（`context_compaction/config.py:31` `model_config = ConfigDict(extra="forbid")`，`context_compaction/middleware.py:90-132` 把 `**kwargs` 整体喂给 `CompactionConfig(**kwargs)`） |
| 其余 **6 个** | Python 原生 `TypeError: __init__() got an unexpected keyword argument 'xxx'`，再被 `config.py:537-543` 包成 `ConfigError: Error instantiating hook '<import 串>': ...` |

原因：另外 6 个都是普通 Python 类，构造函数是显式列出的 keyword-only 参数、**没有 `**kwargs` 兜底**（`llm_failover.py:203-209`、`long_tool_output.py:177-187`、`round_and_token_reminder.py:32-37`、`runtime_environment.py:48-52`、`agent_events_middleware.py:61-66`、`sensitive_word.py:394-411`）。

**排障含义**：效果都是「传错就报错」，但**别按 pydantic 报错去找** —— 6/7 的情况下你看到的是 `TypeError` / `ConfigError: Error instantiating hook`，grep `ValidationError` 会一无所获。

⚠️ 再细一层：`_instantiate_hook_object` **只捕 `TypeError`** 加 `Error instantiating hook` 前缀（`config.py:538-543`）。中间件构造函数自己抛的 `ValueError` / `FileNotFoundError`（如 `head_chars + tail_chars`、词库三选一、`lexicon_dir` 不存在）**不带这个前缀**，只会以裸消息出现在 `Skipped middleware <i>: <原文>` 里。所以统一的定位锚点是 **`Skipped middleware`**，不是 `Error instantiating hook`。

---

## 2. 七个中间件总表

| # | 类名 | 完整 import 串 | 一句话用途 | 必填参数 |
|---|---|---|---|---|
| 1 | `ContextCompactionMiddleware` | `nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware` | 上下文接近上限时自动压缩历史 | 无具名必填，但 `params` 不能为空 |
| 2 | `LongToolOutputMiddleware` | `nexau.archs.main_sub.execution.middleware.long_tool_output:LongToolOutputMiddleware` | 截断超长工具输出，全文落盘沙箱 | 无 |
| 3 | `RoundAndTokenReminderMiddleware` | `nexau.archs.main_sub.execution.middleware.round_and_token_reminder:RoundAndTokenReminderMiddleware` | 每次调模型前注入「第几轮/还剩几轮/token 预算」提示 | **`max_context_tokens`** |
| 4 | `LLMFailoverMiddleware` | `nexau.archs.main_sub.execution.middleware.llm_failover:LLMFailoverMiddleware` | 主 provider 失败时按序切备用 + 可选熔断 | **`fallback_providers`** |
| 5 | `RuntimeEnvironmentMiddleware` | `nexau.archs.main_sub.execution.middleware.runtime_environment:RuntimeEnvironmentMiddleware` | 往首条 system 消息末尾追加运行时环境事实 | 无 |
| 6 | `SensitiveWordMiddleware` | `nexau.archs.main_sub.execution.middleware.sensitive_word:SensitiveWordMiddleware` | 敏感词拦截（输入+输出），见 §5 | **词库三选一** |
| 7 | `AgentEventsMiddleware` | `nexau.archs.main_sub.execution.middleware.agent_events_middleware:AgentEventsMiddleware` | 流式事件出口 | `session_id` —— **平台已注入，别在 YAML 里写** |

> 🚨 **官方白名单只放行第 1、2 两个**（`allowed-middlewares.json`）：`ContextCompactionMiddleware` 只允许 `threshold` 一个参数，`LongToolOutputMiddleware` 一个参数都不允许（`params: {}`）。下面 §3 逐个详解的是**框架层全集**，写进制品前先按 `references/artifact-spec-checklist.md` §9.3 判断这次要不要有意偏离。

---

## 3. 逐个详解

### 3.1 ContextCompactionMiddleware

上下文压缩。`middleware/context_compaction/`。

**参数全集**（= `CompactionConfig` 字段，`context_compaction/config.py:28-80`）：

| 参数 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `max_context_tokens` | `int \| None` | `None` | 否 | `None` = 运行时从 `AgentConfig.max_context_tokens` 继承（该值本身默认 128000，`config/base.py:91`） |
| `auto_compact` | `bool` | `True` | 否 | 关掉就只剩紧急压缩 |
| `emergency_compact_enabled` | `bool` | `True` | 否 | 超限兜底压缩 |
| `threshold` | `float` | `0.75` | 否 | ⚠️ **字段名是 `threshold`，不是 `threshold_ratio`**；只对 `trigger=token_threshold` 生效（`config.py:38`、`trigger_strategies/token_threshold.py:30`） |
| `trigger` | `"token_threshold" \| "time_based"` | `"token_threshold"` | 否 | |
| `gap_threshold_minutes` | `float` | `5` | 否 | 仅 `trigger=time_based` 用 |
| `compaction_strategy` | `"llm_summary" \| "sliding_window" \| "tool_result_compaction"` | `"tool_result_compaction"` | 否 | 见下方合法值说明 |
| `keep_iterations` | `int` | `3` | 否 | 保留最近 N 轮迭代不压缩；必须 `>= 1` |
| `keep_user_rounds` | `int` | `0` | 否 | `0`=禁用；`>0` 时切「用户轮」模式，且**与 `keep_iterations` 互斥** |
| `compactable_tools` | `list[str] \| None` | `None` | 否 | 仅 `tool_result_compaction` 生效；`None`=压缩所有工具结果 |
| `summary_llm_config` | `dict \| None` | `None` | 否 | 摘要 LLM 的嵌套覆盖 |
| `summary_model` / `summary_base_url` / `summary_api_key` / `summary_api_type` | `str \| None` | `None` | 否 | 上一项的扁平 legacy 写法 |
| `compact_prompt_path` | `str \| None` | `None` | 否 | 不传时自动解析到包内 `prompts/compact_prompt.md`；相对路径按 agent.yaml 目录解析（键以 `_path` 结尾） |
| `retry_attempts` | `int` | `3` | 否 | 摘要 LLM 调用重试次数 |
| `save_history` | `bool` | `True` | 否 | 压缩掉的原始消息归档到 `{sandbox_tmp}/.nexau_history_archive/<namespace>/transcript.jsonl`（append-only JSONL，路径固定不可配，防路径穿越；`history_archive.py:15-62`） |

> `token_counter` 是构造函数的另一个显式参数，但它要的是 `TokenCounter` 实例，**YAML 里没法传**，忽略即可。

**`compaction_strategy` 三个合法字面量，实际只有 2 个实现**（`context_compaction/factory.py:41-53`）：

| 写法 | 实际类 | 行为 |
|---|---|---|
| `tool_result_compaction`（默认） | `ToolResultCompaction` | 只把旧的工具结果替换成占位文本，**不调 LLM**、不丢对话文本。便宜、可预测，绝大多数制品用这个 |
| `llm_summary` | `SlidingWindowCompaction` | 调摘要 LLM 把旧迭代压成 summary。贵，但保留语义 |
| `sliding_window` | 同上 | ⚠️ **已废弃别名**：`config.py:85-91` 的 `model_validator` 命中即 `warnings.warn(..., FutureWarning)` 并把值**改写成 `llm_summary`**。两者走同一个类，行为完全一致 |

> `emergency_compact_enabled: true` 走的是第三个类 `UserModelFullTraceAdaptiveCompaction`（`factory.py:85-94` `create_emergency_compaction_strategy`），**不可通过 `compaction_strategy` 选中**，只在超限兜底时自动启用。

⚠️ 两个必须知道的坑：
- **没有 `custom` 选项**。框架文档 `nexau/archs/main_sub/CLAUDE.md` 里那段 `class CompactionStrategy(str, Enum): SLIDING_WINDOW / TOOL_RESULT_COMPACT / CUSTOM` 已过时——当前代码里 `CompactionStrategy` 是 `compact_stratigies/base.py:22` 的一个 `Protocol`（结构化接口），不是 Enum，没有字符串值。**别照抄那段示例**（那段示例里的 `window_size` 参数同样不存在，传了会被 `extra=forbid` 打回）。
- **落到 trace / 持久化里的 strategy 字符串 ≠ 你在 YAML 里写的值**（各策略类的 `name: ClassVar[str]`，框架规定它与 Python 类名解耦、稳定不变）：

  | YAML `compaction_strategy` | 持久化 / trace 里的 strategy | 证据 |
  |---|---|---|
  | `llm_summary` 或 `sliding_window` | `sliding_window` | `compact_stratigies/sliding_window.py:99` |
  | `tool_result_compaction`（默认） | `tool_result` | `compact_stratigies/compact_tool_result.py:43` |

  所以写了 `llm_summary` 却在 trace 里看到 `sliding_window`、写了 `tool_result_compaction` 却看到 `tool_result`，**都不是配错**。
- **`params` 不能是空的**：`context_compaction/middleware.py:126` `if not kwargs: raise ValueError("Configuration parameters (kwargs) are required...")`。只写 `- import: ...ContextCompactionMiddleware` 而不给 `params` 会启动失败。至少给一个字段（比如 `auto_compact: true`）。
- `keep_iterations` 和 `keep_user_rounds` 同时设会 `raise ValueError("Cannot set both keep_iterations and keep_user_rounds")`（`sliding_window.py:145-151`、`compact_tool_result.py:69-75`）。判据是 `keep_iterations != 3 and keep_user_rounds > 0`，所以想用 `keep_user_rounds` 就**别碰** `keep_iterations`。

**典型配置**（长对话默认推荐）：

```yaml
middlewares:
  - import: nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware
    params:
      auto_compact: true
      threshold: 0.75
      compaction_strategy: tool_result_compaction
      keep_iterations: 3
      save_history: true
```

> ⚠️ **这是框架层写法，不是合规写法**：官方白名单里 `ContextCompactionMiddleware` 的 `params_allowed` 只有 `threshold`，上面的 `auto_compact` / `compaction_strategy` / `keep_iterations` / `save_history` 会各报一条 `middleware.params.unexpected`。要过静态校验就只写 `params: { threshold: 0.75 }`（其余全是默认值，行为几乎一致）。见 `references/artifact-spec-checklist.md` §9.3。

要语义摘要（对话内容本身很长、工具结果不是大头）时：

```yaml
      compaction_strategy: llm_summary   # 不要写 sliding_window（FutureWarning）
      keep_iterations: 3
      retry_attempts: 3
```

### 3.2 LongToolOutputMiddleware

在 `after_tool` 阶段截断超长工具输出，全文通过 Sandbox API 落盘，截断视图里给出文件路径让模型自己去读。`long_tool_output.py`。

| 参数 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `max_output_chars` | `int` | `10000` | 否 | 序列化后超过这个字符数才截断；必须 `>= 1` |
| `head_lines` | `int` | `50` | 否 | 截断视图保留的开头行数；`>= 0` |
| `tail_lines` | `int` | `30` | 否 | 保留的结尾行数；`>= 0` |
| `head_chars` | `int` | `5000` | 否 | 保留的开头字符数；`>= 0` |
| `tail_chars` | `int` | `5000` | 否 | 保留的结尾字符数；`>= 0` |
| `temp_dir` | `str \| None` | 沙箱自动解析的输出目录 | 否 | 省略=运行时用 `BaseSandbox.get_tool_output_dir()`；显式传 `null` = **关闭全文落盘**；传字符串 = 覆盖（相对路径不会被自动解析，写绝对路径） |
| `bypass_tool_names` | `list[str] \| None` | `None`（等价于 `["LoadSkill"]`） | 否 | 见下方⚠️ |

证据：`long_tool_output.py:64-93`（默认常量）、`:177-214`（签名与校验）。

> **行数版和字符数版不是二选一**：`_truncate()` 把「按行截」和「按字符截」各算一版，然后在长度 `< max_output_chars` 的候选里取**最长**的那版（都不满足才退而求其次）。所以调 `head_lines`/`tail_lines` 只有在它产出的结果比字符版更长且仍在限内时才可见。

⚠️ 两个必须知道的约束：

1. **构造期硬校验 `head_chars + tail_chars <= max_output_chars`**（`long_tool_output.py:198-199`），否则 `ValueError: head_chars + tail_chars must be <= max_output_chars` → 启动失败。默认值 `5000 + 5000 = 10000` 正好卡在等号上，**所以你一旦调小 `max_output_chars` 就必须同步调小 head/tail_chars**：

   ```yaml
   # ❌ 启动即挂：5000+5000 > 4000
   params: { max_output_chars: 4000 }
   # ✅
   params: { max_output_chars: 4000, head_chars: 2500, tail_chars: 1000 }
   ```

2. **`bypass_tool_names` 是追加语义，不是覆盖**：`long_tool_output.py:214`
   ```python
   self._bypass_tool_names = _DEFAULT_BYPASS_TOOL_NAMES | frozenset(bypass_tool_names or ())
   ```
   默认集合是 `frozenset({"LoadSkill"})`（`:93`），你传的列表与它取**并集**。也就是说 **`LoadSkill` 永远在豁免名单里，无法让它被截断**（设计如此：LoadSkill 不启沙箱，无处落盘；且 skill 正文本来就不该被截）。

**典型配置**：

```yaml
middlewares:
  - import: nexau.archs.main_sub.execution.middleware.long_tool_output:LongToolOutputMiddleware
    params:
      max_output_chars: 10000
      head_chars: 5000
      tail_chars: 5000
      bypass_tool_names: ["read_file"]   # 与默认的 LoadSkill 取并集
```

> ⚠️ **合规写法是 `params: {}`**：官方白名单给 `LongToolOutputMiddleware` 的 `params_allowed` 是**空数组**，上面四个参数会各报一条 `middleware.params.unexpected`。其中前三个写的恰好就是默认值（`10000` / `5000` / `5000`），删掉行为不变；真正的改动只有 `bypass_tool_names`。没有硬需求就写 `params: {}`，见 `references/artifact-spec-checklist.md` §9.3。

### 3.3 RoundAndTokenReminderMiddleware

`before_model` 阶段往消息里追加「当前第几轮 / 还剩几轮 / token 预算」提示，防止长流程 agent 在迭代上限前瞎逛。`round_and_token_reminder.py:32-37`。

| 参数 | 类型 | 默认值 | 必填 |
|---|---|---|---|
| `max_context_tokens` | `int` | **无默认** | ✅ **真必填** |
| `desired_max_tokens` | `int` | `16384` | 否 |

⚠️ `max_context_tokens` 没有默认值、也没有 `**kwargs` 兜底 —— 漏传会在**实例化那一刻**炸：
`TypeError: __init__() missing 1 required keyword-only argument: 'max_context_tokens'` → `ConfigError: Error instantiating hook ...` → agent 启动失败。写配置示例时绝不能省。

行为细节：历史里还没有任何 assistant 消息时会跳过注入，避免开局噪声。

```yaml
middlewares:
  - import: nexau.archs.main_sub.execution.middleware.round_and_token_reminder:RoundAndTokenReminderMiddleware
    params:
      max_context_tokens: 128000     # 建议与 agent.yaml 顶层 max_context_tokens 保持一致
      desired_max_tokens: 16384
```

### 3.4 LLMFailoverMiddleware

通过 `wrap_model_call` 拦截 LLM 调用；主 provider 抛出匹配触发条件的异常时，按序试备用 provider。`llm_failover.py:203-232`。

| 参数 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `fallback_providers` | `list[dict]` | 无 | ✅ | 每项 `{name?: str, llm_config: {...}}`；`name` 缺省自动生成 `fallback-<i>`；`llm_config` 未指定的字段继承主配置 |
| `trigger` | `dict \| None` | `None` | 否 | `{status_codes: [...], exception_types: [...]}`；缺省时 `status_codes` 默认 `[500, 502, 503]`、`exception_types` 默认 `[]`（`llm_failover.py:210-217`） |
| `circuit_breaker` | `dict \| None` | `None`（不启用熔断） | 否 | `{failure_threshold: 3, recovery_timeout_seconds: 60}`，两项各自有默认值 |

触发匹配是 **OR** 逻辑：HTTP 状态码命中 或 异常类名命中。

```yaml
middlewares:
  - import: nexau.archs.main_sub.execution.middleware.llm_failover:LLMFailoverMiddleware
    params:
      trigger:
        status_codes: [500, 502, 503, 529]
        exception_types: ["RateLimitError", "InternalServerError"]
      fallback_providers:
        - name: backup-gateway
          llm_config:
            base_url: ${env.BACKUP_LLM_BASE_URL}
            api_key: ${env.BACKUP_LLM_API_KEY}
      circuit_breaker:
        failure_threshold: 3
        recovery_timeout_seconds: 60
```

> NAC 平台会给制品注入平台级 `LLM_BASE_URL` / `LLM_API_KEY`（见 `references/env-vars-and-secrets.md`）。**只有在你确实有第二个可达网关时才配这个中间件**，否则备用 provider 全挂只是把同一个错误再抛一遍。

### 3.5 RuntimeEnvironmentMiddleware

`before_agent` 阶段把运行时环境事实追加到**首条 SYSTEM 消息末尾**。幂等机制：注入时给那条消息打 `metadata[runtime_environment_injected] = True`，下次看到该标记就跳过（`runtime_environment.py:62-64`、`_append_to_message` 末尾）——即「只要那条带标记的 system 消息还在历史里就不会重复注入」，不依赖任何进程级状态。`runtime_environment.py:31-53`。

| 参数 | 类型 | 默认值 | 必填 |
|---|---|---|---|
| `template` | `str` | `DEFAULT_RUNTIME_ENVIRONMENT_TEMPLATE` | 否 |

默认模板（Jinja）：

```
# Runtime Environment

- Current directory: {{ current_directory or "Unknown" }}
- Operating system: {{ operating_system or "Unknown" }}
- Shell backend: {{ shell_tool_backend or "Unknown" }}
```

自定义 `template` 时可用的变量只有 5 个（其中 2 个是别名，`runtime_environment.py:82-94`）：`current_directory` / `working_directory`（同值）、`operating_system`、`shell_tool_backend` / `shell_backend`（同值）。三项都取自 `agent_state.get_context_value(...)`。

⚠️ 类 docstring（`runtime_environment.py:41-46`）明确说明：**刻意不注入日期、用户名、任意环境变量**——那些更易变，应该由你自己的 `system_prompt` 模板显式处理。别指望这个中间件给你注日期。

⚠️ 两个「装了没用」的静默前提（都直接 `return HookResult.no_changes()` / `""`，不报错）：
- 消息里**没有 SYSTEM 角色消息** → 什么都不注入（`runtime_environment.py:58-60`）。
- 三个 context 值（`working_directory` / `operating_system` / `shell_tool_backend`）**全为空** → 渲染结果为空串，不注入（`runtime_environment.py:78-79` `if not any(values.values()): return ""`）。这三个值由 executor 往 `agent_state` 的 context 里写，通常要求 agent 确实带沙箱 / shell 工具。

```yaml
middlewares:
  - import: nexau.archs.main_sub.execution.middleware.runtime_environment:RuntimeEnvironmentMiddleware
```

### 3.6 AgentEventsMiddleware —— 别在制品里写

| 参数 | 类型 | 默认值 | 必填 |
|---|---|---|---|
| `session_id` | `str` | 无 | ✅ |
| `on_event` | `Callable[[Event], None]` | `_noop_event_handler` | 否 |

`session_id` 是运行期才知道的值，YAML 里根本填不出来。NAC agent-runtime 在每次请求时自己构造并注入：`server.py:5896` 与 `:6832` 调 `AgentEventsMiddleware(session_id=session_id, ...)` 后交给 `TransportBase._recursively_apply_middlewares`。

⚠️ 该注入是 **`cfg_copy.middlewares.extend(middlewares)`**（`nexau/archs/transports/base.py:131`），即**追加在你 YAML 声明的所有中间件之后**，并且会递归应用到所有 sub_agent。对照 §4 的顺序规则：它在 `wrap_*` 洋葱里是最内层，在 `after_*` 里是最先执行的那个。

---

## 4. ⚠️ 执行顺序是洋葱模型，不是声明顺序

配置侧严格保序，不做任何重排（`config/config.py:667-681` 按 `enumerate` 顺序 `append`；`execution/executor.py:2325-2370` `combined = list(configured_middlewares)`，随后把 legacy 的 `before_model_hooks` / `after_model_hooks` / `before_tool_hooks` / `after_tool_hooks` 包成 `FunctionMiddleware` 追加到**末尾**）。

但 `MiddlewareManager` 各阶段的遍历方向不同（`execution/hooks.py`）：

| Hook 阶段 | 遍历方向 | 证据 |
|---|---|---|
| `before_agent` | **正向**（声明顺序） | `hooks.py:645-646` |
| `before_model` | **正向** | `hooks.py:691-698` |
| `before_tool` | **正向** | `hooks.py:784-786` |
| `stream_chunk` | **正向** | `hooks.py:821-825` |
| `wrap_model_call` | 洋葱：`invoke(0, params)` 递归，**index 0 在最外层** | `hooks.py:804-805` |
| `wrap_tool_call` | 同上 | `hooks.py:847-848` |
| `after_agent` | ⚠️ **倒序** `reversed(self.middlewares)` | `hooks.py:666-670` |
| `after_model` | ⚠️ **倒序** | `hooks.py:722-733` |
| `after_tool` | ⚠️ **倒序** | `hooks.py:759-767` |

**记忆法**：进洋葱按声明顺序从外到内，出洋葱按反方向从内到外。声明列表里**最后一个**中间件，是所有 `after_*` 里**最先**跑的。

**这在什么时候会咬你**：

- 想让 `SensitiveWordMiddleware` 在其他中间件改完 assistant 文本**之后**再扫 `after_model` → 必须把它声明在**前面**（倒序 → 后跑），不是想当然地摆最后。
- 想让 `LongToolOutputMiddleware`（`after_tool`）在别的 after_tool 中间件之前先截断 → 把它声明在**后面**。
- `before_model` 类（压缩、轮次提醒、敏感词输入侧）之间才是「声明在前 = 先跑」的直觉顺序。

多个中间件互相不依赖时（绝大多数制品），顺序随便写，不用纠结。

---

## 5. 内容安全护栏专章：SensitiveWordMiddleware

政企 / 信创场景刚需。`middleware/sensitive_word.py`，内置一个零依赖的 Aho-Corasick 自动机做多模式匹配。

> ✅ **可用性已核实**：cookbook 里「该中间件尚在 feat 分支、未合入 main」的说法**已过时**。当前 NAC 内置的 NexAU SDK（`0.5.0-11-g1cd84b61`，2026-07-07）已包含三次相关提交：新增中间件 + 通用强制停止通道、加 `OnHitAction`、`İ` 变长字符 mask 绕过修复，且 SDK 内配套有 `docs/advanced-guides/sensitive-word-middleware.md` 与 `examples/sensitive_word/` 可运行样例。

### 5.1 参数全集

`sensitive_word.py:394-461`。全部 keyword-only，普通 Python 类（不是 pydantic）。

| 参数 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| `lexicon_dir` | `str \| Path \| None` | `None` | 三选一 | 词库**目录**，遍历 `*.txt`，每个文件名（不含扩展名）= 该表的 category |
| `lexicon_file` | `str \| Path \| None` | `None` | 三选一 | 单文件词库，文件名 = category |
| `lexicon_words` | `list[str] \| None` | `None` | 三选一 | 直接内联词表，统一归入 `"explicit"` 类 |
| `extra_words` | `list[str] \| None` | `None` | 否 | 追加词，归入 `"extra"` 类 |
| `case_sensitive` | `bool` | `False` | 否 | 中文不受影响；英文词建议保持 `False` |
| `block_input` | `bool` | `True` | 否 | 扫 `before_model` 的入参消息 |
| `block_output` | `bool` | `True` | 否 | 扫 `after_model` 的模型可见正文（不动 reasoning） |
| `input_action` | `"terminate" \| "mask" \| "soft_reject"` | **`"mask"`** | 否 | 见 §5.2 |
| `output_action` | 同上 | **`"mask"`** | 否 | |
| `refusal_template` | `str` | 内置中文严厉文案 | 否 | 仅 `terminate` 用；占位符 `{source}`（渲染成「用户输入」/「模型输出」）/ `{category}` / `{hits}` |
| `soft_refusal_template` | `str` | 内置中文温和文案 | 否 | `soft_reject` 用；`mask` 的审计事件 message 字段也用它。支持同样三个占位符（`:773-777` 统一 `.format`），内置默认文案只用了 `{source}` |
| `mask_template` | `str` | `"***"` | 否 | 占位符 `{category}` / `{word}` / `{length}`。例：`"[<{category}>]"`、`"*{length}*"` |
| `scan_roles` | `list[Role] \| None` | `None` = `{USER, FRAMEWORK, SYSTEM, TOOL}` | 否 | 见 §5.3 坑 3 |
| `raise_on_block` | `bool` | `False` | 否 | 🚫 **保持 `False`（默认）**，见下方红框 |

**词库来源是硬校验**（`sensitive_word.py:412-416`）：`lexicon_dir` / `lexicon_file` / `lexicon_words` 三者**全空** → `ValueError: SensitiveWordMiddleware requires an explicit lexicon_dir, lexicon_file, or lexicon_words; no default sensitive lexicon is bundled.` → 启动失败。**框架不内置任何兜底词库**，别以为装上就自带。

> 「三选一」= **至少给一个**，不是互斥：三者可以同时给，会合并进同一张表（见下）。`extra_words` 不算数——只给它仍然报上面这个错。

🚫 **`raise_on_block: true` 会让护栏彻底失效，别开。** 它让 `before_model` / `after_model` 抛 `SensitiveContentBlockedError`（`sensitive_word.py:151` 继承 `RuntimeError`，`:668`、`:711` 抛出），而**全仓库没有任何地方 catch 它**——异常直接落进 `MiddlewareManager` 的兜底 `except Exception`（§1.4b），变成一条 `⚠️ Before-model middleware ... failed:` warning，然后**原始敏感内容原封不动继续送给 LLM / 返给用户**。想要「硬中断」请用 `input_action: terminate` / `output_action: terminate`，不要用 `raise_on_block`。

**词库文件格式**（`sensitive_word.py:291-346`）：UTF-8，一行一个词，空行和 `#` 开头的行跳过。四类来源汇总进同一个 `{归一词: category}` dict，同词后加入的 category 覆盖先加入的（顺序：`lexicon_words` → `lexicon_file` → `lexicon_dir` → `extra_words`）。

### 5.2 `OnHitAction` 三个值 —— ⚠️ 当前默认是 `mask` 不是 `terminate`

`sensitive_word.py:70-78`：

| 值 | 行为 | stop reason |
|---|---|---|
| `mask`（**默认**） | 把命中词就地替换成 `mask_template`，对话**继续**（输入侧改写 messages，输出侧改写末条 assistant） | 不停 |
| `terminate` | 追加/替换成 `refusal_template` 拒绝文案并终止本次 run | `ERROR_OCCURRED` |
| `soft_reject` | 用 `soft_refusal_template` 温和跳过本轮，**同时把历史里命中位置也 mask 掉** | `SUCCESS` |

⚠️ 该中间件的原始行为是 `terminate`，后续提交把默认值改成了 `mask`。如果需求是「命中就中断对话」，**必须显式写 `input_action: terminate` / `output_action: terminate`**，不能依赖默认。

命中时无论哪个 action，都会打一条 `logger.warning("[SensitiveWordMiddleware] HIT source=... action=... categories=... hits=[...]")`（`_build_notice`，`sensitive_word.py:759-765`）——**这条日志是无条件的，审计就认它**。另外还会发一个 `ContentBlockedEvent`，但那条**有前提**：`_emit_blocked` 在 `self._event_emitter is None` 时静默 return，emitter 由 executor 在链路里存在事件提供方（NAC 上就是自动注入的 `AgentEventsMiddleware`）时才注入。

### 5.3 四个必讲的坑

**坑 1 — `lexicon_dir` 相对路径 + 只扫顶层 `*.txt`，可能静默加载 0 词、护栏完全失效**

- `lexicon_dir` 的键名不以 `_path` / `_file` 结尾，**不享受**「相对 agent.yaml 目录解析」（§1.3），会按**进程 CWD** 解析。制品里必须写绝对路径，例如 `/agent/lexicon`。
- 目录不存在 → `FileNotFoundError: SensitiveWordMiddleware lexicon_dir is not a directory`（`sensitive_word.py:334-335`）→ 启动失败，这个是**响的**。
- 真正静默的是：**目录存在但没有顶层 `.txt` 文件**（`glob("*.txt")` 非递归，`:336`；词放在子目录、或用了 `.csv`/`.dict` 扩展名）→ `lexicon_size == 0` → `scan_text` / `scan_messages` 直接短路返回空（`:475-476`、`:503-504`），且 `before_model` / `after_model` 开头也有 `lexicon_size == 0` 早退（`:660`、`:702`），**中间件装了等于没装，一条日志错都不报**。
- **验收动作**：启动日志里必须看到 `[SensitiveWordMiddleware] loaded N words; ...`（`sensitive_word.py:453-461`）且 `N > 0`。只要 `N=0` 就是护栏失效，不要发布。

**坑 2 — `input_action: terminate` 下命中消息留在历史，后续每轮被同一个词反复拦截**

⚠️ **只在输入侧（`input_action`）成立**，输出侧无此问题（见下）。

`before_model` 每次都重扫**全量历史**（`scan_messages` 遍历所有 `scan_roles` 内的消息，`:498-524`）。而输入侧 `terminate` 分支只是 `new_messages = list(hook_input.messages)` 再 append 一条拒绝文案（`:680-683`），**没有改写那条违规消息**。于是同一会话的下一轮、下下轮……只要历史还在，同一个词会被一次次扫到、一次次终止 —— 用户会觉得「这个会话彻底废了」。

- 输入侧 `mask`（`:676-678`）和 `soft_reject`（`:688-690`）都会 `self._mask_message(m)` 改写命中位置（`soft_reject` 的注释明确写了这么做就是为了「避免下一轮 history 残留同一敏感词又触发，导致永远聊不下去」），所以它们没这个问题。
- 输出侧（`after_model`）三个 action 都不留原文：`mask` 就地脱敏末条 assistant（`:719-723`），`terminate` / `soft_reject` 直接**用拒绝文案替换**那条 assistant（`:727-731`）。而且输出侧扫的是本轮 `original_response` 单个字符串（`:705-706`），压根不重扫历史。
- **测试纪律**：验证敏感词拦截时**一个用例一个新会话**（新 `session_id`），否则上一个用例的命中会污染下一个用例。

**坑 3 — 默认 `scan_roles` 覆盖 SYSTEM 和 TOOL，且刻意不提供 allowlist**

默认 `frozenset({USER, FRAMEWORK, SYSTEM, TOOL})`（`sensitive_word.py:98`）意味着：

- **你自己的 system prompt 每轮都在被扫**。如果 prompt 里为了说明「不要讨论 X」而写了 X 本身，会被自己的词库击中。
- **工具结果在扫描面内**（专门写了 `_extract_scan_text` 去抽 `ToolResultBlock` 里的文本，`:480-496`）——知识库原文、检索结果、网页抓取内容全算。这是有意设计（拦 tool result 投毒），但也意味着做政策/法规类知识库时误杀率会很高。
- 中间件**没有任何 allowlist / 白名单机制**，命中即处理。误杀的唯一解法是**从词库里删词**，或者收窄 `scan_roles`（例如只扫用户输入：`scan_roles: [user]`）。

**坑 4 — 词库不支持热更新**

Aho-Corasick 自动机在 `__init__` 里一次性 `add()` + `build()` 完成（`sensitive_word.py:431-435`），此后不可追加。改词库文件对已运行的进程无效，**必须重新部署 / 重启 runtime pod 才生效**。

### 5.4 可直接抄的配置

```yaml
middlewares:
  # 内容安全护栏（政企合规）。lexicon_dir 必须绝对路径。
  - import: nexau.archs.main_sub.execution.middleware.sensitive_word:SensitiveWordMiddleware
    params:
      lexicon_dir: /agent/lexicon      # 目录下每个 *.txt 的文件名即 category
      case_sensitive: false
      block_input: true
      block_output: true
      input_action: mask               # 默认就是 mask；要中断必须显式写 terminate
      output_action: mask
      mask_template: "***"
      raise_on_block: false
```

> ⚠️ **`SensitiveWordMiddleware` 不在官方白名单**，抄这段会报 `middleware.not_allowed`。这属于**有意偏离**（政企合规场景往往必须有护栏，而白名单是平台有意收窄、不是滞后），交付前需要与对方确认或走白名单收录流程。判读口径见 `references/artifact-spec-checklist.md` §9.3。

制品里的词库目录布局（打包进 artifact，见 `references/nexau-json-and-packaging.md`）：

```
/agent/
├── nexau.json
├── agent.yaml          # 必须在制品根（官方规范 required_top_level_files）
├── systemprompt.md
└── lexicon/
    ├── 涉政.txt
    ├── 涉枪涉爆.txt
    └── 辱骂.txt
```

需要中断语义（该中间件的原始行为）时把两个 action 改成 `terminate`，并接受坑 2。

---

## 6. 选型建议

| 场景 | 建议组合 | 理由 |
|---|---|---|
| **纯对话 / 短任务** | 不写 `middlewares` | 每个中间件都是启动期风险面 + 每轮开销；没需求就别装 |
| **长对话（多轮会话、会话历史持续增长）** | `ContextCompactionMiddleware`（`tool_result_compaction` + `threshold: 0.75`） | 默认策略不调 LLM、成本可预测；对话文本本身很长时才换 `llm_summary` |
| **长流程（多工具、迭代多、会读大文件）** | `LongToolOutputMiddleware` + `RoundAndTokenReminderMiddleware` + `ContextCompactionMiddleware` | 先截断工具输出（治因），再提醒轮次预算，压缩兜底 |
| **政企 / 信创合规交付** | `SensitiveWordMiddleware`（+ 上面按需） | 见 §5；上线前必须核验启动日志的 `loaded N words` |
| **有第二个可达 LLM 网关且要求高可用** | `LLMFailoverMiddleware` | 只有一个网关时配了没用 |
| **模型需要知道 cwd / OS** | `RuntimeEnvironmentMiddleware` | 省得在 system_prompt 里手写；但它不注入日期/用户名 |

> 🚨 **上表推荐的组合里，只有 `ContextCompactionMiddleware`（仅 `threshold`）和 `LongToolOutputMiddleware`（`params: {}`）在官方白名单内**。`RoundAndTokenReminder`（第 3 行）/ `SensitiveWord`（第 4 行）/ `LLMFailover`（第 5 行）/ `RuntimeEnvironment`（第 6 行）都会报 `middleware.not_allowed` —— 选它们等于**有意偏离官方规范**，取舍表见 `references/artifact-spec-checklist.md` §9.3。

### 默认装配约定：长会话 / 长工具输出场景，默认先把这两个加上

平台散文规范 `artifact-hard-rules.md` §5.3 对**制品作者**（含生成制品的 agent）立了一条约定：

> 若任务可能产生**长会话 / 长工具输出 / 多轮 refine-verify**，`middlewares` 默认应优先加入
> `ContextCompactionMiddleware` 与 `LongToolOutputMiddleware`；只有在模板 / workflow 不兼容时
> 才可省略，并**记录原因**。

⚠️ **这是作者侧装配约定，不是 schema 硬约束**：静态校验只校验**已声明**中间件的写法是否合法（白名单 / 参数名），
**不把缺失当硬错误**。不写这两个既不会部署失败，也不会报一条 error —— 与本文其余「写了会坏」的规则（§1、§3）性质完全不同。
它约束的是判断力，不是语法。

**为什么默认是这两个**（各自堵的是一个框架里真的没有兜底的洞）：

| 不加会怎样 | 证据 |
|---|---|
| **不加 ContextCompaction**：框架**没有任何默认裁剪**。executor 发现 prompt 超 `max_context_tokens`（顶层默认 128000）时，只打一条 `⚠️ Prompt tokens (%d) exceed max_context_tokens (%d). Continuing model call.` **然后照发不误**。真正的兜底在中间件里 —— 认 provider 的 overflow 报错、紧急压一次再重试一次的逻辑，整段写在 `ContextCompactionMiddleware.wrap_model_call` 内。**没装它 = 这条兜底不存在**，provider 的 context overflow 直接冒上去打断本次 run | `executor.py:861-866`（同步 `execute()`）、`:1475-1480`（`_execute_iteration_async`）只 warning；`context_compaction/middleware.py:720-742`，overflow 判据是 `:54` 起的 `_CONTEXT_OVERFLOW_MARKERS` 文案匹配 |
| 同步 `execute()` 路径还有个**溢出前就开始的劣化**：`available_tokens = max_context_tokens - current_prompt_tokens` 随历史增长被压到 `max(1, ...)`，即回答越来越短、极端情况只剩 1 token（异步路径当前算完丢弃，注释写着 reserved for future use，无此劣化） | `executor.py:870-878`；异步 `:1482-1484` `_ = max(1, min(...))` |
| **不加 LongToolOutput**：框架对工具输出**没有任何默认截断**（`hooks.py:552` 那处 `truncated` 只截**日志预览**，不动进 history 的内容）。一次 `read_file` 大文件 / 长命令输出会整份原样进 messages，并**永久留在历史里**每轮重发 | `hooks.py:551-561` 只喂 `logger.info`（截到 `tool_preview_chars=500`，`:480`）；`long_tool_output.py` 是全仓唯一在 `after_tool` 改写工具输出本体的地方 |

**而且两者不能互相替代** —— 这是最容易想当然的一点：`ContextCompactionMiddleware` 默认策略
`tool_result_compaction` 的 `keep_iterations: 3` **保护最近 3 轮迭代的工具结果不被压缩**
（`compact_tool_result.py:38` 类 docstring、`:48` 默认值、`:124-134` 把最近 N 轮的下标塞进 `protected_indices`，`:150` 只压不在其中的 TOOL 消息），也就是说**「刚刚炸出来的那份超大输出」恰恰是压缩不会碰的那份**。
把它挡在 history 之外的只有 `LongToolOutputMiddleware` 的 `after_tool` 当场截断。反过来，
LongToolOutput 只管单条工具输出，管不住多轮对话文本自身的累积。**一个治单点尖峰，一个治总量增长。**

**与顶部白名单的关系（不是巧合）**：官方 `allowed-middlewares.json` 唯二放行的，正是这两个。
平台一边把它们定为默认装配项、一边在白名单里只留它们 —— 等于 **「平台推荐的标配」= 「白名单全集」**。
实践含义很省事：**按这条默认约定装配的制品天然 100% 合规**，完全不涉及 `references/artifact-spec-checklist.md` §9.3 那张「有意偏离」取舍表。
本文 §3 讲的其余 5 个中间件都在标配之外，用不用是另一码事。

**可直接抄（合规写法，两项都在白名单内）**：

```yaml
middlewares:
  # 默认装配项 ①：上下文压缩。白名单只允许 threshold 一个参数，且它是 params_required。
  - import: nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware
    params:
      threshold: 0.75          # 框架默认值。artifact-spec-checklist §9.2 示例写 0.6，只是取值不同，两者都合规
  # 默认装配项 ②：长工具输出截断。白名单 params_allowed 是空数组 —— 只能写 {}。
  - import: nexau.archs.main_sub.execution.middleware.long_tool_output:LongToolOutputMiddleware
    params: {}                 # 默认值：>10000 字符才截断，保留 head 5000 + tail 5000，全文落盘沙箱供 read_file
```

> 两条都不能省 `params` 键（§1.2 / `references/artifact-spec-checklist.md` §9.1）；
> `ContextCompactionMiddleware` 更是连空 `params: {}` 都会启动失败（§3.1 末尾），所以 `threshold` 那行**必须**写。
> 想调 §3.1 / §3.2 里其它参数之前，先看 `references/artifact-spec-checklist.md` §9.3 —— 那已经是有意偏离，不是调参。

**什么时候可以不加**（省了要能说出理由）：

| 情形 | 可省谁 | 理由 |
|---|---|---|
| 纯单轮短问答 / FAQ / 分类打标，没有跨轮上下文积累 | 两个都可省 | 就是上表首行的「纯对话 / 短任务」：中间件是启动期风险面 + 每轮开销，没需求别装 |
| 工具输出天然很短（只回状态码 / 少量字段的 API 封装、枚举结果） | 可省 `LongToolOutput` | 永远够不到 10000 字符阈值，装了纯空转 |
| 会话长但无工具 / 工具输出极短（增长来自对话文本本身） | 留 `ContextCompaction`，可省 `LongToolOutput` | 治的不是同一种增长 |
| 模板 / workflow 明确不兼容 | 按不兼容项省 | 规范要求**记录省略原因**，别静默省掉 |

> ⚠️ 有一种「不兼容」是硬的、不是选择：`llm_config.api_type == "generate_with_token"` 时声明
> `ContextCompactionMiddleware` 会在 agent 初始化阶段直接
> `ValueError: api_type='generate_with_token' does not support ContextCompactionMiddleware.`
> （`agent.py:783-795` `_validate_middleware_compatibility()`，由 `:751` 在初始化时调用）。制品里本来就**不该写 `api_type`**（平台按模型卡推导，见 `references/llm-config.md`），
> 所以正常路径遇不到；只有被明确要求走该 api_type 时才需要省掉压缩并注明。

---

一份「长流程 + 合规」的完整片段（顺序已按 §4 考虑过：敏感词声明在前，`after_model` 阶段最后跑，能扫到其他中间件改完的文本）。⚠️ **这份是框架层能力演示，不是合规制品**：它会报 2 条 `middleware.not_allowed`（SensitiveWord、RoundAndTokenReminder）+ 6 条 `middleware.params.unexpected`（ContextCompaction 的 `auto_compact`/`compaction_strategy`/`keep_iterations`、LongToolOutput 的三个）。合规版（只有两个中间件、`threshold` + `params: {}`）见 `references/artifact-spec-checklist.md` §9.2：

```yaml
middlewares:
  - import: nexau.archs.main_sub.execution.middleware.sensitive_word:SensitiveWordMiddleware
    params:
      lexicon_dir: /agent/lexicon
      input_action: mask
      output_action: mask

  - import: nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware
    params:
      auto_compact: true
      threshold: 0.75
      compaction_strategy: tool_result_compaction
      keep_iterations: 3

  - import: nexau.archs.main_sub.execution.middleware.long_tool_output:LongToolOutputMiddleware
    params:
      max_output_chars: 10000
      head_chars: 5000
      tail_chars: 5000

  - import: nexau.archs.main_sub.execution.middleware.round_and_token_reminder:RoundAndTokenReminderMiddleware
    params:
      max_context_tokens: 128000
```

---

## 7. 报错速查

| 报错 | 根因 | 修法 |
|---|---|---|
| `ConfigError: Could not import attribute from '...': Module 'nexau.archs.main_sub.execution.middleware' has no attribute 'XxxMiddleware'` | import 串只写到目录级（或类名拼错） | 补上模块文件名（§1.1） |
| `ConfigError: Could not import module from '...': No module named 'nexau.archs.main_sub.middleware'` | 少了 `execution` 层 | 见 §1.1 |
| `ConfigError: Error importing from '...': Import string must contain ':' separator` | 用 `.` 连接类名 | 改成 `:` |
| `ConfigError: Error instantiating hook '...': __init__() got an unexpected keyword argument 'xxx'` | 参数名拼错（6 个非-compaction 中间件） | 对 §3 参数表逐字核；**别去 grep pydantic ValidationError** |
| pydantic `ValidationError: Extra inputs are not permitted` | `ContextCompactionMiddleware` 参数名拼错（如 `threshold_ratio`、`window_size`） | 用 `threshold`；`window_size` 不存在 |
| `__init__() missing 1 required keyword-only argument: 'max_context_tokens'` | `RoundAndTokenReminderMiddleware` 漏参 | 必填，补上 |
| `ValueError: head_chars + tail_chars must be <= max_output_chars` | 只调小了 `max_output_chars` | 同步调小 head/tail_chars |
| `ValueError: Configuration parameters (kwargs) are required.` | `ContextCompactionMiddleware` 没给 `params` | 至少给一个字段 |
| `ValueError: Cannot set both keep_iterations and keep_user_rounds` | 两个保留策略都设了 | 用 `keep_user_rounds` 时别动 `keep_iterations` |
| `ValueError: SensitiveWordMiddleware requires an explicit lexicon_dir...` | 词库三选一都没给 | 见 §5.1 |
| `FileNotFoundError: SensitiveWordMiddleware lexicon_dir is not a directory` | `lexicon_dir` 写了相对路径或路径不存在 | 改绝对路径 `/agent/lexicon` |
| 敏感词中间件「装了但完全不拦」 | `loaded 0 words` | 目录里没有顶层 `*.txt`（§5.3 坑 1） |
| 同一会话每轮都被同一个词拦 | `input_action: terminate` 不改历史 | 换 `mask`/`soft_reject`，或换新会话（§5.3 坑 2） |
| `FutureWarning: compaction_strategy=sliding_window is deprecated` | 用了废弃别名 | 改 `llm_summary`（行为不变） |
| 日志里只有 `⚠️ Before-model middleware ... failed: ...`，请求却正常返回 | 中间件**运行期**抛异常被吞（§1.4b） | 按 warning 里的异常原文修；别指望它把请求打红 |
| `ConfigError: Invalid agent configuration: ... Extra inputs are not permitted` | 条目写了 `import` / `params` 以外的第三个键 | 删掉多余键（§1.2） |
| 敏感内容照样透传，日志里有 `⚠️ Before-model middleware ... failed: ... SensitiveContentBlockedError` | 开了 `raise_on_block: true`，异常被两层 `except Exception` 吞掉（`hooks.py:718-719` + `executor.py:1449-1450`） | 改回 `raise_on_block: false`，用 `input_action: terminate` 表达硬中断（§5.1） |

> 所有中间件**构造期**异常最终都会被 `config.py:682-684` 包成 `ConfigError: Skipped middleware <i>: <原因>`。启动日志里 grep `Skipped middleware` 直接定位是第几个条目出的问题（`<i>` 是 0-based 下标）。**运行期**异常不在这里，锚点是 `⚠️ ... middleware ... failed:`（§1.4b）。

---

## 未核实 / 边界说明

- `before_model` 中间件返回的 messages 是否**持久化**回会话历史（影响 `mask` 的改写是否跨请求生效），本文未追到底；`hooks.py:691-720` 与 `executor.py:1436-1462` 只能证明它在**本次 run 内**替换了 `state.messages`。§5.3 坑 2 的结论只依赖「`terminate` 分支不改写违规消息 + 每轮重扫全量历史」这两条已核实事实，不受此影响。
- `LLMFailoverMiddleware` 的熔断器状态机细节（CLOSED/OPEN/HALF_OPEN 转换时机）未逐行核，只核了构造参数与默认值。
- `block_output` 那句「不动 reasoning」：依据是输出侧扫的是 `AfterModelHookInput.original_response`，而它由 executor 赋成 `model_response.content`（`executor.py:1514`、`:952`）——即正文字段。thinking / reasoning 是否可能混进 `content` 未逐 provider 核。
- §1.1 / §1.2 的报错原文与 schema 行为是在本机 `.venv`（已安装当前 pinned 版 `nexau`）里实跑 `import_from_string` / `AgentConfigSchema.model_validate` 得到的；其余条目为逐行读码核实。
