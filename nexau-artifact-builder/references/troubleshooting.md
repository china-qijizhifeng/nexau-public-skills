# 排障速查表（NexAU/NAC 制品）

本文覆盖**制品从打包上传到线上跑起来全过程的失败模式**：错误信息/症状 → 根因 → 具体修复动作。
**什么时候读它**：制品上传被拒、部署 failed、pod 起不来、chat 报错、或者「没报错但行为不对」时。
写制品之前也值得扫一遍「表 D：不报错但行为不对」——那一类是最贵的，事后查不出来。

分组按失败发生的**层**，不是按时间：
| 表 | 层 | 你会在哪看到 |
|---|---|---|
| A | 加载期（agent-runtime 解析 agent.yaml / 构建 Agent） | pod 日志、deploy_status=failed、readiness 失败 |
| B | 上传/部署期（Backend 校验制品） | HTTP 4xx + JSON error body，制品根本没进平台 |
| C | 运行期（chat 请求路径） | chat 响应 4xx/5xx、SSE error 事件、工具返回 error |
| D | 不报错但行为不对 | 只能靠对照本表发现 |

时间顺序其实是 **B → A → C**（先上传、再起 pod、再对话）。排障顺序见文末。

---

## 表 A：加载期失败（agent 起不来）

典型外层包装：`Error loading configuration from /agent/agents/x.yaml: <具体原因>`（`nexau/archs/main_sub/config/schema.py:180-183`，并会 `traceback.print_exc()`）。看到这串就去掉外层，只看冒号后面。

| 错误信息 / 症状 | 根因 | 修复动作 | 细节 |
|---|---|---|---|
| `Environment variable 'X' is not set` | `${env.X}` 在 agent.yaml 里出现但 pod 环境无此 key。替换是**在 `yaml.safe_load` 之前对整份文件做正则替换**（`common.py:84-95`），所以**注释里的 `${env.X}` 一样会炸** —— 把配置注释掉不能让它失效 | ① 要么在版本/环境 env vars 里建这个 key（**runtime scope**）并 Redeploy；② 要么把那一行**真的删掉**（不是注释掉）。`${env.X:-default}` 不是默认值语法、`$${env.X}` 不是转义 | `env-vars-and-secrets.md` |
| `Environment variable 'LLM_API_TYPE' is not set` | 平台**已不再注入** `LLM_API_TYPE`（scheduler 只注入 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`） | 直接删掉 `api_type` 那一行 —— 平台会按命中的模型卡派生 api_type，写了也会被覆盖 | `llm-config.md` |
| `Environment variable 'LLM_MODEL' is not set` | `LLM_MODEL` **只在能解析出兜底模型时才注入**（`runtime_env.rs:534-537`）。项目一张可见/已授权的模型卡都没有时，这个 env 不存在 | 给项目授权至少一张模型卡（或解锁隐藏卡），或整段省略 `llm_config`（runtime 会在内存补一份） | `llm-config.md` |
| `llm_config is required in agent configuration` | `AgentConfigSchema` 的 model_validator 硬要求（`schema.py:135-139`）。**NAC 只为 `nexau.json` 里列出的顶层 agent 自动补默认**（cli.py:160-199）；**sub-agent 的 yaml 走 `AgentConfig.from_yaml` → `AgentConfigSchema.from_yaml` 递归加载，不经过那段补默认**（`config/config.py:947-953` → `config.py:220`） | **每个 sub-agent yaml 都要自己写 `llm_config`**，最省事写 `llm_config: {model: ${env.LLM_MODEL}}` | `mcp-and-subagents.md` |
| `Invalid agent configuration: <key>: Extra inputs are not permitted` | **顶层** key 拼错。`AgentConfigBase.model_config = ConfigDict(extra="forbid")`（`config/base.py:57-61`） | 按 `agent-yaml-fields.md` 的字段表核对拼写。注意：这个保护**只对顶层生效**，`tools:` / `skills:` 条目内部拼错是静默的（见表 D） | `agent-yaml-fields.md` |
| `'variables' must be a mapping if provided in YAML` | 顶层 `variables:` 写成了标量/列表（`common.py:104-105`） | 改成 mapping | `agent-yaml-fields.md` |
| `Variable 'x' is not defined in 'variables'` | `${variables.x}` 引用了本文件顶层 `variables:` 块里没有的 key（`common.py:118`）。**注释里的一样会炸**。注意：文件里**完全没有** `variables:` 块时反而不报错、静默留字面量（`common.py:100-102`） | 补上 key，或删掉引用。`variables` **不跨文件继承**，sub-agent yaml 要自己再写一份 | `agent-yaml-fields.md` |
| `Variable 'x' resolves to a non-scalar value and cannot be embedded in a string` | `variables:` 里那个 key 的值是 dict/list，而 `${variables.x}` 是**文本宏**、只能插标量（`common.py:120-123`） | 把值改成标量；要复用一整块结构就直接写进 YAML，别用 `${variables.*}` | `agent-yaml-fields.md` |
| `ScannerError: mapping values are not allowed here` / `ComposerError: found undefined alias` / 结构莫名多出一个顶层 key | env 值被**文本注入**后把 YAML 结构搞坏：值里含 `: `、换行、` #`、开头的 `*`/`&`、双引号 | 一律写成 `key: "${env.X}"`（加引号）；值里含双引号的场景改用其它通道（runtime_vars / sandbox_env）传 | `env-vars-and-secrets.md` |
| `ModuleNotFoundError: No module named 'nexau.archs.main_sub.middleware'` | middleware import 路径漏了 `execution` 这一层。`nexau/archs/main_sub/execution/middleware/` 目录**没有 `__init__.py`**，必须写到具体模块文件 | 改成 `nexau.archs.main_sub.execution.middleware.<模块名>:<类名>`，例如 `...execution.middleware.context_compaction:ContextCompactionMiddleware` | `middlewares.md` |
| `Extra inputs are not permitted` **且报错来自 pydantic ValidationError** | `ContextCompactionMiddleware` 的参数名写错。它把 `**kwargs` 整体喂给 `CompactionConfig`，而 `CompactionConfig.model_config = ConfigDict(extra="forbid")`（`execution/middleware/context_compaction/config.py:31`）。最常见：写了 `threshold_ratio`，正确是 `threshold` | 按 `middlewares.md` 的参数表核对。**只有 ContextCompaction 是这个报错形态** | `middlewares.md` |
| `TypeError: __init__() got an unexpected keyword argument 'xxx'` | 其余 6 个中间件（AgentEvents / LLMFailover / LongToolOutput / RoundAndTokenReminder / RuntimeEnvironment / SensitiveWord）都是普通 Python 类，构造函数是显式 keyword-only 参数、**没有 `**kwargs` 兜底**（已逐个核实 `__init__` 签名） | 同上核对参数名。**别按 pydantic 报错的思路找**——形态不同但性质一样 | `middlewares.md` |
| `TypeError: __init__() missing 1 required keyword-only argument: 'max_context_tokens'` | `RoundAndTokenReminderMiddleware.max_context_tokens` **真必填、无默认**（`round_and_token_reminder.py:32-37`） | `params:` 里补 `max_context_tokens: <数字>` | `middlewares.md` |
| `SensitiveWordMiddleware requires an explicit lexicon_dir, lexicon_file, or lexicon_words; no default sensitive lexicon is bundled.` | 三个词库来源一个都没给。**框架不带任何内置词库**（`sensitive_word.py:412-416`） | 三选一必填，推荐 `lexicon_dir: /agent/lexicon`（绝对路径） | `middlewares.md` |
| `FileNotFoundError: SensitiveWordMiddleware lexicon_dir is not a directory: <path>` | `lexicon_dir` 指到了不存在的路径。**相对路径按进程 CWD `/home/user` 解析**，不是按 agent.yaml 目录 | 改绝对路径 `/agent/<目录>`。⚠️ 注意：cookbook 说「相对路径会静默加载 0 词」——**当前代码不是静默，是 FileNotFoundError**（`sensitive_word.py:333-335`）。真正静默 0 词的是「目录存在但没有 `.txt` 文件」，见表 D | `middlewares.md` |
| `Tool definition of 'x' contains 'agent_state' field in <yaml>, which will be injected by the framework, please remove it` | `.tool.yaml` 的 `input_schema` **顶层**出现了保留名 `agent_state` / `global_storage` / `ctx`（`tool/tool.py:357-373`） | 从 input_schema 里删掉；这些参数只靠 Python 函数签名注入，不进 schema | `custom-tools.md` |
| `Tool configuration missing 'name' field` / `Tool 'x' missing 'yaml_path' field` | tools 条目里 builder 手动 `dict.get()` 的**只有这两个键**，缺了才硬失败（`config/config.py:1171-1173`、`:1188-1189`） | 补齐。除这两个键外，tools 条目的其它 key 拼错是**静默**的（表 D） | `agent-yaml-fields.md` |
| sub_agents / mcp_servers 条目报 `Extra inputs are not permitted` | 这两个是**真严格**的：`SubAgentConfigEntry` / `MCPServerBaseModel` 都是 `extra='forbid'` 且被泛型/显式声明真正应用（`schema.py:49-56`、`schema.py:59-93,124`） | sub_agents 条目只能有 `name` / `config_path` / `source_id`；MCP 条目字段见 `mcp-and-subagents.md` | `mcp-and-subagents.md` |
| `ModuleNotFoundError` 指向你自己的 `custom_tools.xxx` | `binding` 的 import 根是**制品根目录**（runtime 把 `/agent` 与 `/agent/src` 前插进 `sys.path`，`cli.py:148-158`），不是 agent.yaml 所在目录 | binding 一律写成从制品根算起的模块路径（`custom_tools.finnhub_api:finnhub_quote`）。注意这与 `yaml_path` / `system_prompt` / `skills` 的基准（**agent.yaml 所在目录**）是两套 | `custom-tools.md` |
| `ValueError: No agents found in <project_dir>` | `nexau.json` 的 `agents` 指的文件全都不存在（单个找不到只 warning 跳过，全空才抛，`cli.py:206-278`） | 核对 `agents` 里的相对路径；路径基准是**制品根**。⚠️ **不要指望「省略 `agents` 就自动扫描」**——`config.get("agents", {})`（`cli.py:230`）在 key 缺失时返回 `{}`，`{}` 仍是 dict → 走 dict 分支 → 零个 agent → 就是这个错。自动扫 `agents/*.yaml` 的 `else` 分支（`cli.py:267-274`）**只在 `agents` 的值既不是 dict 也不是 list 时**才走到（如显式写 `"agents": null`），别依赖这个隐藏行为。补充：在 NAC 上你其实碰不到这个错——更早一道门是**上传期 400** `Artifact validation failed: nexau.json missing or invalid 'agents' field (expected non-empty object)`（两条上传路径 `:1104` / `:1788` 都过这道校验）；只有本地直跑 runtime 才会看到 `No agents found` | `nexau-json-and-packaging.md` §2 |
| Rust runtime（`backend: nexau-rs`）readiness 失败：`missing required environment variables referenced by \`${env.*}\`: A, B`（只缺一个时名词是单数 `environment variable`，**没有 `variable(s)` 这种写法**，grep 时别带括号） | Rust runtime 在 readiness 阶段一次性预检所有 `${env.*}`（ `validate_required_env_placeholders`，文案 `:269-279`） | 按提示把这些 key 加到 version/environment 的 **runtime scope** env vars 并 Redeploy。⚠️ Rust 侧是「解析后逐值插值」，**注释里的 `${env.X}` 不会被它统计**，但同一份 yaml 在 Python runtime 上仍然会炸——两条链路对注释判定不一致 | `env-vars-and-secrets.md` |

---

## 表 B：上传 / 部署期失败（HTTP 4xx）

| HTTP + 错误信息 | 根因 | 修复动作 |
|---|---|---|
| **413** `Agent Artifact exceeds the 100MB compressed archive size limit.` | 压缩包超过 **100 MiB** | 瘦身：把大知识库拆到独立版本 / 删掉离线 whl 里用不到的平台变体 / 去掉 `.git`、`node_modules`、`__pycache__`、`.venv`。⚠️ **别拿 500MB 当上限** —— 那是 Backend 全局 body 限制，是另一层 |
| **400** `unsupported tar entry \`X\`: only regular files and directories are allowed` | 归档里有**符号链接 / 设备文件 / FIFO**。归档条目只允许普通文件和目录（`artifacts.rs:130-154`，zip 同规则 `:156-180`） | 打包前 `find . -type l` 排查；`tar -czf` 直接打 `node_modules` / `venv` 必失败。用 `tar --exclude` 或 `zip -r ... -x` 排除，或用 `tar -h`（解引用软链，注意会撑大体积） |
| **400** 路径被拒（非 UTF-8 / 绝对路径 / 含 `..` / 反斜杠 / NUL / Windows 盘符 / 空路径） | 两处把关：**非 UTF-8** 由 `artifacts.rs:133-137` 的 `path.to_str()` 拒（文案 `tar entry path must be valid UTF-8`）；其余由 `normalize_artifact_path` 拒（各自独立文案如 `absolute paths are not allowed` / `parent traversal is not allowed`） | 在制品根目录内 `tar -cf ../x.tar .`，别用绝对路径打包；别在 Windows 上直接打 zip |
| **400** `Artifact validation failed: nexau.json is required` | 归档里找不到 `nexau.json`（`artifacts.rs:677`） | 压缩的必须是**含 `nexau.json` 的那一层**。多包了一层目录时上传仍会过（init 脚本有「单顶层目录压平」），但别依赖它 |
| **400** `nexau.json.backend (...) is inconsistent with runtime.flavor (...)` | 同时写了 `backend` 和 `runtime.flavor` 且不一致（`artifacts.rs:773-800`） | 只写一个。Python 用 `"backend": "nexau"`（或整个省略） |
| 上传成功但 **Playground 里 agent 列表不对 / 少了 agent** | 制品里有多份 `nexau.json`，Backend 按「**最浅路径优先、同深度字典序**」择一（`artifacts.rs:602-655`），可能取到了子目录那份 | 制品里只留一份 `nexau.json`（子目录里的示例/子项目 manifest 要删或改名） |
| 建 env var 时 **400** `'LANGFUSE_X' is managed by the platform ...` | `LANGFUSE_*` 在**任何 scope** 都禁止用户设置 | 不要设；Langfuse 凭证由 sidecar 注入 |
| 建 env var 时 **400** `'LLM_API_KEY' is consumed by the LLM sidecar and must be in Runtime scope` | `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 只允许 runtime scope（`env_vars.rs:89-97`） | 改 runtime scope。但注意即便建成 runtime scope 也会被平台值覆盖（`runtime_env.rs:280-293`），基本没意义 |
| 建 env var 时 **400** key 格式 | key 只允许 ASCII 字母/数字/下划线，非空且 ≤255 字符（`env_vars.rs:65-76` `validate_env_var_key`） | 改 key 名，别用 `-` / `.` |
| **改了 env var，行为没变** | version 是 immutable 的，env 变更要重新 Redeploy 才进 pod | 改完 env var 必须 Redeploy 该环境 |

---

## 表 C：运行期失败（chat 路径）

| 错误信息 / 症状 | 根因 | 修复动作 | 细节 |
|---|---|---|---|
| 每次 chat 都 **422** `{"code":"LLM_PROVIDER_UNROUTABLE", ...}`，但**部署是绿的** | 上传/部署期**完全不校验** model 可路由性，sidecar 在每次请求时才拒（ → `:886-895`）。触发条件：`llm_config.model` 的全键不在项目可见卡片表里，**且**没能走成回落（回落要求 `providers_meta` 非空且 `LLM_MODEL` 已注入，`server.py:1466-1494`） | ① 核对 `provider/model_name` 全键拼写；② 确认该卡对本项目**可见且已授权**（隐藏卡要 admin 解锁）；③ 想跟随项目默认就写 `${env.LLM_MODEL}` 或整段省略 `llm_config`。⚠️ **「项目一张授权卡都没有」（路由表整个为空）也是走这条 422，不是 503** —— body 里有 `model` 字段就一定进 `resolve()` → 查不到 → Reject | `llm-config.md` |
| 同上 422，但 `model` 写的是**裸名**（如 `gpt-4o`，没有 `provider/` 前缀） | 裸名**比写错全键更糟**：sidecar 见无前缀直接 Reject，**不走回落**（`proxy_routers.rs:1177-1187`）；A4A 静态校验器也把它列为 error | model 必须是 `provider/model_name` 全键，或 `${env.LLM_MODEL}` | `llm-config.md` |
| chat **503** 纯文本 `no LLM provider configured` | ⚠️ **不是「路由表为空」这么简单**：503 只在走到 `Fallback` 分支且路由表为空时才出（`proxy_routers.rs:868-878`），而 Fallback 只由「请求体不是合法 JSON」或「请求体压根没有 `model` 字段」产生（`:1152-1171`）；非 chat 端点（`/v1/embeddings`、`/v1/models`）路由表为空也是 503（`:898-911`）。**带 `model` 的 chat 请求即使路由表为空也是 422**（见上两行） | 制品作者日常几乎碰不到。真见到就先确认自己是不是在直调 sidecar 的非 chat 端点、或发了畸形 body；不要一看到 503 就去动模型卡 | `llm-config.md` §3.3 |
| chat **503** `{"code":"UPSTREAM_5XX_CIRCUIT_OPEN", "retry_after_secs": N}` | 该 provider 的**熔断器打开**（`proxy_routers.rs:920-932`）——上游连续 5xx 触发。熔断键是 `全键 ‖ 上游 endpoint`，所以只熔这一张卡这个端点 | 等 `retry_after_secs` 冷却，或修上游；同样不要去改模型卡配置 | `llm-config.md` |
| chat **400** `Multiple agents registered, 'agent' parameter required` | `nexau.json` 的 `agents` 声明了 **≥2 个** agent，而请求没带 `agent` 字段。Runtime 只在**恰好 1 个** agent 时才自动选中 | 每次 chat 都带 `agent: "<agent 名>"`（名字含义见下一行）；或者制品只声明 1 个 agent | `nexau-json-and-packaging.md` §2 |
| chat **404** `Agent 'x' not found` | 带了 `agent` 字段但查不到（`server.py:3302-3303`）。**别和上面的 400 混**：400 = 没传，404 = 传错。⚠️ Runtime 注册表的 key 是 **agent.yaml 顶层的 `name`**（`server.py:3088-3090` `self._agents[agent.name]`），**不是** `nexau.json` 里的 key —— 两者写得不一样时，按 `nexau.json` 的 key 调就 404 | 让 **agent.yaml 的 `name` 与 `nexau.json` 的 key 完全一致**（本 skill 所有模板都这么做），否则调用方按哪个名字调全靠猜 | `nexau-json-and-packaging.md` §2 |
| 工具每次调用都返回 `Invalid parameters for tool 'x': Additional properties are not allowed ('api_token' was unexpected)` | **`extra_kwargs` 与 `additionalProperties: false` 互斥**。执行时 `merged_params = {**extra_kwargs, **params}`，而送去 jsonschema 校验的 `validation_params` **只剔除 4 个框架注入名**（agent_state/global_storage/sandbox/ctx），**不剔除 extra_kwargs**（`tool/tool.py:52,548,572` + `:731-742`） | ① **推荐**：这个工具的 `input_schema` **删掉 `additionalProperties: false` 这一行**（密钥仍对模型不可见）；② 或把该 key 声明进 `properties`（但模型就能看见并覆盖它 —— `params` 在后会赢，密钥场景不可接受） | `custom-tools.md` |
| 工具返回 `{"error": "...", "error_type": "...", "traceback": "...", "tool_name": "..."}` 给模型 | 工具函数内部抛了异常，被框架吞成结构化返回，agent **不会崩**（`tool.py:626-637`） | 这是正常语义，不是框架 bug。看 `error_type` 定位真因。注意 **schema 校验失败不走这条**（`validate_params` 在 try 之前，直接抛 ValueError） | `custom-tools.md` |
| custom tool 里 `open(path)` 报 `FileNotFoundError`，但 agent 明明刚写了这个文件 | **进程边界**：custom tool 的 Python 函数在 **agent-runtime 进程内**直接调用（`tool.py:540-577`），裸 `open()` 看到的是**只读的 `/agent` 制品目录**；agent 用 `read_file` / `run_shell_command` 操作的文件在**沙箱** `/home/user` | 函数签名加 `sandbox=None`（框架按名字注入），或加 `agent_state=None` 再 `from nexau.archs.tool.builtin._sandbox_utils import get_sandbox, resolve_path`，然后 `sandbox.read_file(...)` | `custom-tools.md` |
| custom tool 写文件报 `OSError: [Errno 30] Read-only file system` | `/agent` 对 Python Runtime 是**只读挂载** | 写 `/tmp` 或 `/home/user`；产物要给 agent 看就写进沙箱 | `nexau-json-and-packaging.md` |
| pod 日志里 `WARNING: setup command failed: <cmd>`，**但部署状态是成功的**，随后 import 时才炸 | setup 命令是 `eval "$cmd" \|\| log "WARNING: ..."`（`scripts.rs:225-237`），**失败不中断部署** | ① 在 `setup` 末尾追加自检命令（如 `python -c 'import dmPython'`），失败虽仍不阻断部署但日志更可读；② 报 failed 时**去 pod 日志 grep `setup command failed`**，别只看部署状态 | `nexau-json-and-packaging.md` |
| setup 里 `pip install --target /agent/...` 报 `Read-only file system` | 同上，`/agent` 只读（只有 Rust runtime 镜像才可写） | 装进 runtime 已有解释器：`/usr/local/bin/uv pip install --python /opt/venv/bin/python --no-index --find-links /agent/<whl目录> <pkg>` | `nexau-json-and-packaging.md` |
| setup 里 `export PATH=...` / `cd` / `source venv/bin/activate` 全都不生效 | setup 跑在 `echo ... \| while read` 的**子 shell** 里，runtime 进程最后 `cd /home/user` 才启动（`scripts.rs:230-235,273-276`） | 不要靠 export 让依赖生效，直接装进目标解释器 | `nexau-json-and-packaging.md` |
| 沙箱里 shell 读 `$MY_TOKEN` 是空 / CLI 报 `missing API token`（本地跑同一套却正常） | ⚠️ **旧结论「需平台侧支持注入」是错的，能力早就有**。真因是沙箱是另一台机器：E2B 沙箱下发的 env 只有 `self.envs + per-call envs`（`base_sandbox.py:519-535` `_merge_envs`，调用点 `e2b_sandbox.py:674` `commands.run(..., envs=self._merge_envs(envs))`），**不继承 runtime 进程环境**；而本地 `LocalSandbox` 会 `{**os.environ, **merged}`（`local_sandbox.py:147-163`）——**本地能读到 ≠ 云上能读到** | 把这个 key 建成 **sandbox scope** env var（`?scope=sandbox`，`env_vars.rs:81-118`），或按请求走 `variables.sandbox_env`。链路：Gateway merge → `Sandbox.create(envs=)` → sandboxd `command.env(k,v)` | `env-vars-and-secrets.md` |
| `RuntimeError: Session is bound to sandbox <id>, but Runtime could not connect to it. Clear the session sandbox binding or create a new session before retrying.` | 沙箱是 **session 级实体**：会话已绑定某个沙箱，但这次 resume 连不上（沙箱被回收/被清理/集群侧异常）。这时 Runtime **刻意不新建替代沙箱**，直接报错（`server.py:4605-4625`），避免静默换一台机器导致上一轮产物凭空消失 | 换一个新 `session_id` 重试（= 全新空沙箱，`/home/user` 下的中间产物全丢）；跨会话要留东西只能落外部存储 | `nexau-json-and-packaging.md` §8 |
| 沙箱里自己 `nohup` 起的守护进程读不到 sandbox_env | K8s 非 DevBox 沙箱**不会**把 sandbox_env 写进 Pod 容器 env：`build_pod`全段不读 `config.env_vars`，只有 DevBox 分支 `build_devbox_pod` 才把它铺进容器 env（`k8s.rs:1963`）。普通沙箱走的是**每条命令的 per-command envs** | 只对经 SDK 工具（`run_shell_command` 等）启动的进程可见。守护进程要用变量就在启动它的那条命令里显式传 | `env-vars-and-secrets.md` |
| `Path is not a directory: <p>` | 对**文件**路径用了 `search_file_content`（`search_file_content.py:290`）或 `list_directory`（`list_directory.py:80`） | 改用 `read_file`。systemprompt 里写清「目录用 list_directory，文件用 read_file」 | `builtin-tools.md` |
| `Path is a directory, not a file: <p>` | `read_file` 指到了目录（`read_file.py:252`） | 改用 `list_directory` | `builtin-tools.md` |
| `Path does not exist: <p>` | 路径猜错（最常见是 skills 路径猜成 `/agent/skills/...`，或猜了不存在的文件名） | systemprompt 里写死：skills 根目录是 `/home/user/.skills/`，且**必须先 LoadSkill 拿返回的 `<SkillFolder>` 当权威路径**。禁止猜 `/agent/skills/...` | `nexau-json-and-packaging.md` |
| Agent 搜索卡死 / 请求超时 | 对含数千文件的 `references/` **根目录**做 `search_file_content` | systemprompt + SKILL.md 两处写「**禁止对知识库根目录搜索**，必须先按索引定位到分类子目录再搜」，并用 `include` 缩范围。（cookbook 劳动法篇实测过） | `builtin-tools.md` |
| 模型收到工具结果 `{"status":"error","error_type":"ValueError","error":"Sub-agent 'x' not found"}`；pod 日志同时有 `❌ Sub-agent 'x' not found` | 调用时用的名字不是 `sub_agents` 条目里的 `name`（条目 `name` 会**覆盖**子 agent yaml 自己的 name）。抛点 `execution/subagent_manager.py:111-114`（`raise ValueError`），被 `tool/builtin/agent_tool.py:92-100` 吞成结构化 tool result | 以主 agent yaml 里 `sub_agents[].name` 为准；systemprompt 里写死这个名字。⚠️ grep 日志用 `Sub-agent '`，**不要 grep `SubAgentNotFoundError`** —— 这个类名在代码里根本不存在（只出现在框架自带的过时文档 `nexau/archs/main_sub/CLAUDE.md:506`），`error_type` 实际是 `ValueError` | `mcp-and-subagents.md` |
| 用户看到「数据库查询未返回结果」这类**兜底回答**，日志里没有显式报错 | MCP 连不上（如 `host.docker.internal` 在真集群解析不到）。**DNS/连接错误会被当成 tool 结果回灌给 LLM**，模型于是编一句兜底回答 | 部署前 sanity check：pod 内 `getent hosts <mcp-host>` + `curl -m 5 -sI <url>`（期望 200/405）。集群内用 `http://<svc>.<ns>.svc.cluster.local:<port>/mcp` | `mcp-and-subagents.md` |
| MCP 返回 **421 Invalid Host header** | MCP server 开了 DNS rebinding 防护，要求特定 Host | headers 里加 `Host: localhost:8000`（仅本机调试需要，上正规域名后删掉）；`Accept` 写 `application/json, text/event-stream` | `mcp-and-subagents.md` |
| 同一会话里，第一次被敏感词拦之后**每一轮都被拦** | 命中的消息仍留在会话历史，而中间件**每轮扫全量历史** | 验证时**一用例一新会话**；线上引导用户重置会话 | `middlewares.md` |
| 自家 system prompt / 知识库原文被敏感词误杀 | 默认 `scan_roles` 覆盖 SYSTEM 和 TOOL；中间件**刻意不提供 allowlist** | 只能从词库删词，或用 `scan_roles` 缩小扫描面 | `middlewares.md` |
| 从沙箱读回的 PDF/DOCX/ZIP 解析报「missing bytes」 | 忘了 `binary=True`。`binary=False` 走的是**文本模式**：读用 `open(path, encoding=...)`（`local_sandbox.py:802-804`），写用 `content.decode(encoding)`（`local_sandbox.py:858-860`）—— 二进制字节按 UTF-8 解不动就抛 `UnicodeDecodeError`，被包成 `SandboxStatus.ERROR` / `Failed to read file: 'utf-8' codec can't decode byte ...`（注意：合法 UTF-8 的中文文本不受影响，出事的是真二进制） | 读写二进制一律 `read_file(path, binary=True)` / `write_file(path, data, binary=True)`。⚠️ **旧 skill 教的 base64 中转已经没必要**：sandboxd 的二进制截断 bug 早已修复（当前  用 `multer` 流式原样落盘，并有 Rust 单测 + e2e 双层回归守卫） | — |
| 请求跑到 **~5 分钟**处断开，Gateway 返回 **502** `Failed to communicate with Agent Runtime`，但 pod 健康、trace 里 agent 还在继续跑 | **非流式请求有一道 Gateway 整请求超时**：`stream: false` 走 `state.http_client`，该 client 带 `.timeout(request_timeout_secs)`，默认 **300s**（生产环境也是 300）。`stream: true` 走 `runtime_stream_client`——**只限 connect timeout、无整请求超时**（`lib.rs:228-238`，分支在 `handlers/chat.rs:791-796`） | 长任务一律用 `"stream": true`（平台前端与官方调用脚本都是流式）。⚠️ **别去调 agent.yaml 的顶层 `timeout`**，那是死配置（见表 D）；这一层的旋钮是部署侧的 `NEXAU_AGENT_GATEWAY_REQUEST_TIMEOUT_SECS`，制品作者改不了 | `agent-yaml-fields.md` §8 |
| 沙箱脚本 `ModuleNotFoundError: requests` / `fitz` | ⚠️ **cookbook 的「NAC sandbox 只有 Python 标准库」已过时**。沙箱镜像预装了 venv `/opt/sandbox-python`（PATH 已前置），含 requests / httpx / aiohttp / PyMuPDF / pdfplumber / pandas / numpy / Pillow / python-docx / openpyxl / beautifulsoup4 / playwright 等 | 先确认脚本是不是被别的解释器跑了；确实缺的包走 `nexau.json` 的 `setup` 装离线 whl。**custom_tools 跑在 agent-runtime 进程，依赖集是另一套** | `custom-tools.md` |

---

## 表 D：不报错，但行为不对（最难查的一类）

| 症状 | 根因 | 怎么确认 / 怎么修 | 细节 |
|---|---|---|---|
| `extra_kwargs` 没传进去 / 某个工具选项完全没生效，**日志一句话都没有** | ⚠️ **`tools:` / `skills:` 的条目完全不校验**：`base.py:70,72` 把它们声明成 `list[Any]`，没真正用泛型参数化，所以 `ToolConfigEntry` 的 `extra='forbid'` 在列表元素上**不起作用**——拼错的 key（`extra_args`、`path`、`lazy_load`…）被**静默忽略**，也不进 skipped_components | 逐字符核对字段名：`name` / `yaml_path` / `binding` / `lazy` / `as_skill` / `defer_loading` / `extra_kwargs` / `source_id`。**真正会报错的只有缺 `name` 和缺 `yaml_path`** | `agent-yaml-fields.md` |
| 自定义工具读用户上传的文件恒报「文件不存在」，但文件确实上传成功了；**runtime 日志零 warn/error、sandbox-proxy 无请求记录、trace 里也没有失败 span** | 工具签名写成 `(*args, **kwargs)` → 四个保留注入参数**全部拿不到**（`inspect.signature` 只产出 `args`/`kwargs`，`tool.py:562` 静默 `pop`），代码于是回落到裸 `pathlib`，在 **runtime 容器**里找沙箱的 `/home/user/uploads/...`。返回的是普通 dict 而非异常，所以整条链路可观测层面完全静默 | 把注入参数改成具名形参（keyword-only 也行）：`def f(*args, agent_state=None, **kwargs)`；再走 sandbox 句柄读文件。自查命令见 `custom-tools.md` §3 | `custom-tools.md` §1/§3 |
| 自定义工具报告文件「已生成」（`created: true` / size > 0），但用户下载不到、`run_shell_command` 也 `ls` 不出来 | 工具用裸 `open()` / `zipfile.ZipFile(path)` 写盘 → 写进了 **runtime 容器**的 `/home/user`（真实存在且可写），本地 `path.exists()` 自然为真，于是「成功」被自证。沙箱里根本没有这个文件 | 写盘走 `sandbox.write_file(path, raw, binary=True)`，并以返回的 `status` / `sandbox.get_file_info()` 为判据，不要用本地 `path.exists()` 自证。二进制先在 `io.BytesIO` 里打包 | `custom-tools.md` §1/§11 |
| Agent 用的模型不是 yaml 里写的那个，**而且 temperature / max_tokens / thinking 全部失效** | model 全键查不到卡片时，runtime 判定整段 `llm_config` 不可信，**重建一个只含 model/base_url/api_key 的干净 LLMConfig**，采样/推理参数**全丢**（`server.py:1466-1489`，单测 `test_p3b_invalid_model_discards_agent_llm_config`）。前提是 `providers_meta` 非空且 `LLM_MODEL` 已注入，否则不回落、直接每次 422（见表 C） | 「模型名打错一个字母 → 采样参数静默全丢」。核对全键拼写与卡片授权 | `llm-config.md` |
| 换了项目默认模型后，agent 跟着漂了（或没跟着漂） | `${env.LLM_MODEL}` / 省略 model / 省略整段 `llm_config` 都会被标记 **follow-default**，Gateway 缓存刷新后跟随项目/环境默认模型；写死全键则钉死（`llm_model_provenance.py:157-175`） | 这是**选择题**不是风格问题：要跟随写 `${env.LLM_MODEL}`，要锁定写全键 | `llm-config.md` |
| agent.yaml 里写的 `base_url` / `api_key` / `api_type` / `stream` 一点效果没有 | 全被平台覆盖：`base_url`/`api_key` 被 `_inject_llm_config` 无条件覆盖（`server.py:1956-1957`）；`api_type` 被模型卡派生值覆盖（`server.py:1496-1510`）；`stream` 在流式路径被强制 True（`transports/base.py:134-135`） | 删掉这些行（噪声）。**唯一真禁**的是字面量 `api_key`——凭证进制品是安全事故，A4A 静态校验器直接 error。想接自己的 LLM 网关只能走 per-request `override_llm_configs`，不是 agent.yaml | `llm-config.md` |
| 沙箱创建失败 / 路由到奇怪的地方，配置看着都对 | **你自己在 agent.yaml 里写了 `sandbox_config`**。平台只在 `agent_config.sandbox_config is None` 时才注入自己那份（`server.py:2215-2216`），你一写平台就不注入了 | 删掉 `sandbox_config`（这是「写了必坏」的两个字段之一） | `agent-yaml-fields.md` |
| `${env.X:-default}` 没有取到默认值，配置里出现一串垃圾文本 | 正则只认 `\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}`，`:-default` 不匹配 → **不报错、静默留字面量**（`common.py:84`）。危害比 fail-fast 更大（比如 model 字段变成垃圾串，要到调 LLM 才暴露） | 没有默认值语法。要默认值就在平台建 env var | `env-vars-and-secrets.md` |
| `${env.MY-KEY}` 没被替换 | env 名正则不允许连字符，静默留字面量 | key 只用字母/数字/下划线（平台建 key 时也是这个约束） | `env-vars-and-secrets.md` |
| `${variables.x}` 没被替换 | 文件里**完全没有** `variables:` 块时，函数提前 return，所有 `${variables.x}` 静默留字面量（`common.py:100-102`） | 补 `variables:` 块。另注意：`${variables.x}` **只替换一趟不递归**，variables 之间互相引用只能生效一层 | `agent-yaml-fields.md` |
| 在 `tools/*.yaml` / `SKILL.md` frontmatter / `nexau.json` 里写 `${env.X}`，它就是不解析 | **插值只对 agent.yaml 家族生效**。tool yaml 是裸 `yaml.safe_load`（`tool/tool.py:334`），SKILL.md frontmatter 同（`skill.py:95`），nexau.json 是 `json.load`（`cli.py:226-227`） | 密钥走 agent.yaml 的 `extra_kwargs: {key: ${env.X}}` 注入，不要试图在 tool yaml 里插值 | `custom-tools.md` |
| 模型的 tool schema 里冒出了 `agent_state` / `sandbox`，还会去填它 | `.tool.yaml` 的保留字守卫**只检查 `input_schema` 的顶层 key**（`tool.py:357-373`）；写在 `properties:` 下面能**静默通过**并泄漏进模型可见 schema | 这四个名字（agent_state / global_storage / sandbox / ctx）**任何层级都不要写进 input_schema**，只写进 Python 函数签名 | `custom-tools.md` |
| `extra_kwargs` 里用了 `sandbox` 当 key，行为诡异 | extra_kwargs 的保留键守卫只有 `{agent_state, global_storage, ctx}`（`tool.py:291-296`），**`sandbox` 不在里面**，会和框架注入撞车 | 换个 key 名 | `custom-tools.md` |
| 子代理调了 `complete_task` 却不结束，`result` 也没成为返回给主 agent 的答案 | **`stop_tools` 必须显式声明**（默认空集，`base.py:74` + `config.py:584`）。只有 `tool_name in self.stop_tools` 才会打 `_is_stop_tool` 标记（`tool_executor.py:342-347`），`complete_task` 的 `result` 才会被提为 final_response（`executor.py:1795-1807`） | 子 agent yaml 里加 `stop_tools: [complete_task]`。（cookbook 的 file_classifier 就漏了这条） | `mcp-and-subagents.md` |
| 设了 `max_running_subagents` 但并发一点没变 | 这是个**空旋钮**。它确实被一路传下去（`config/config.py:441` → `agent.py:765` → `executor.py:245`），并在 `executor.py:291` 存成 `self.max_running_subagents`，但**该属性此后再无任何读取点**（全包 grep `self.max_running_subagents` 只有这一处赋值），没有任何限流逻辑消费它 | 别承诺「设它能限并发」；要控并发靠 prompt 里的调度规则 | `mcp-and-subagents.md` |
| 设了顶层 `timeout` 但请求没按它超时 | 顶层 `timeout`（默认 300，`config/base.py:97`）**当前未接线**：它只被填进 `ExecutionConfig.timeout`（`config/config.py:427,444`），而 `agent.py:754-780` 构造 `Executor(...)` 时**没有传 timeout**，`Executor.__init__` 也**没有 timeout 形参** | 制品能控的只有 `llm_config.timeout`（每次 LLM 请求级；未写时平台兜底 300s）。⚠️ 还有**第三层不在 agent.yaml 里**：非流式请求受 Gateway 整请求超时约束（默认 300s，见表 C「~5 分钟处断开」那行）——整轮跑太久要靠 `stream: true`，不是靠这个字段 | `agent-yaml-fields.md` |
| `nexau.json` 里写了 `excluded`，文件还是被打进去了 | **平台完全不解析 `excluded`** —— backend / scheduler / runtime / sandbox-manager / artifact-init 与 nexau SDK 都没有解析代码，它只是被原样存进 `project_versions.config` | 排除是**打包端**（CLI / DevBox 导出）的行为。手工打包就自己 `tar --exclude` / `zip -x` | `nexau-json-and-packaging.md` |
| 敏感词护栏装了，但一个词都拦不住；日志 `[SensitiveWordMiddleware] loaded 0 words` | `lexicon_dir` **存在但目录下没有 `.txt` 文件**（只遍历 `*.txt`，`sensitive_word.py:336`），或只传了 `extra_words`。（路径**不存在**是 FileNotFoundError，不是这一条） | 部署后**必须核对启动日志的 `loaded N words`**，N=0 就是没生效。词库文件扩展名必须是 `.txt` | `middlewares.md` |
| 改了词库文件，重新部署前不生效 | Aho-Corasick 自动机在中间件初始化时一次性构建，**不支持热更新** | 改词 = 重新打包上传部署 | `middlewares.md` |
| `bypass_tool_names` 设了却发现 `LoadSkill` 也在 bypass 列表里 | `LongToolOutputMiddleware.bypass_tool_names` 是**追加**语义（与默认 `{'LoadSkill'}` 取并集），不是覆盖 | 这是预期行为，别当 bug | `middlewares.md` |
| 模型看到的工具名和 `.tool.yaml` 里写的不一样 | agent.yaml 的 tools 条目 `name:` 会**覆盖** tool.yaml 内部的 `name`（`tool.py:340-346`） | **判断模型最终看到什么名字必须看 agent.yaml 那一层**。另注意 `Glob`：本 skill 打包的 `templates/_builtin-tool-yamls/Glob.tool.yaml` 内部 `name:` 已统一成**大写 `Glob`**（校验器 canonical 表的 key），agent.yaml 那层也写 `Glob`；**cookbook 原版是小写 `glob`**，从原仓直接拿会与 agent.yaml 对不上（`tool.name.mismatch`）。`binding` 的函数名始终是小写 `glob` | `builtin-tools.md` |
| Agent 不加载 skill，直接凭记忆回答 | systemprompt 没有强制检索。SKILL.md 是**两级懒加载**：只有 name/description 常驻，正文靠 LoadSkill，references 从不自动加载（`skill.py:186-215`） | systemprompt 里写死：「**禁止立刻回答，必须先 LoadSkill / 先检索知识库**」，并给出「查资料而不是背资料」的规则 | — |
| Agent 跳过索引，直接猜文件名，然后报「文件不存在」 | 实测高频：看到子目录 `合同纠纷/` 就猜 `违法解除劳动合同纠纷处理.md`（真名 `违法解除劳动合同.md`） | systemprompt **和** SKILL.md 两处都写：「🚫 禁止跳步：看到子目录必须先读该目录的索引文件；**禁止凭猜测构造文件名**，只读索引里明确列出的文件；报错就回上级索引核对」 | — |
| Agent 回答「无法访问参考文件」 | skill 有 `references/` 但 agent.yaml 没给 `read_file` 工具 | 有 references 的 skill 必须配 `read_file`（通常再配 `search_file_content`） | `builtin-tools.md` |
| SKILL.md 教 Agent 调某个工具，运行时说没这个工具 | **SKILL.md 与 agent.yaml 漂移**（cookbook 现成反例：住房公积金的 `pdf_to_md/SKILL.md` 教调 `pdf_to_md` 工具，那份 agent.yaml 根本没注册它） | 收尾自检：把 SKILL.md 里出现的每个工具名和 agent.yaml 的 `tools:` 对一遍 | — |
| LoadSkill 调不到 skill，但文件路径明明对 | **两个名字不是一回事**：沙箱里的目录名 = 本地 skill **目录的 basename**（`base_sandbox.py:998-1005` `upload_skill`：`Path(work_dir)/".skills"/os.path.basename(local_folder)`，`work_dir` 默认 `/home/user`，`base_sandbox.py:169`）；LoadSkill 用的是 **SKILL.md frontmatter 的 `name`**。cookbook 就有目录 `pdf_to_md` / name `pdf-to-md` 的现成坑 | 建议目录名与 frontmatter name 保持一致；不一致时 systemprompt 里要分别写清「调用名」和「路径」 | `nexau-json-and-packaging.md` |
| **本地跑通，上云就挂** | 最常见三种：① `LocalSandbox` 继承 `os.environ`（`local_sandbox.py:147-163`）而云端 E2B 沙箱只下发 `self.envs + per-call envs`（`base_sandbox.py:519-535`）；② 本地没有 `LLM_BASE_URL` 时 `_inject_llm_config` 整个跳过、agent.yaml 的 base_url/api_key 原样生效（`server.py:1423-1425`、`server.py:1916-1917` `if env_llm_config is None: return agent_config`），云上必被覆盖；③ 本地 `/agent` 是普通目录、云上是只读挂载 | 上云前对照这三点自查；密钥统一走 **sandbox scope**，不要依赖「本地 shell 能读到」 | `env-vars-and-secrets.md` |
| 打印 `LLM_API_KEY` 得到 `placeholder-sidecar-injected` / `sk-placeholder` | 设计如此。注入 runtime 的 `LLM_API_KEY`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY` 都是占位串，`LLM_BASE_URL` 是 `http://localhost:<sidecar_port>/v1`；真凭证只在 sidecar 容器 | 别当 bug 排查 | `env-vars-and-secrets.md` |
| 建的 runtime env var 被「吞了」，pod 里是另一个值 | `merge_runtime_env` 先铺 user_env 再用 platform_base 覆盖写（`runtime_env.rs:280-293`），撞上 `PATH` / `PORT` / `LLM_*` / `NEXAU_*` 等平台保留键会被**静默覆盖** | 换个 key 名，别用平台前缀 | `env-vars-and-secrets.md` |

---

## 排障顺序建议

**第一步：先定位"卡在哪一层"，别一上来翻 agent.yaml。**

| 观察到的 | 说明卡在 | 下一步看 |
|---|---|---|
| 上传/发布就返回 4xx | B 层，制品根本没进平台 | 直接看 HTTP body 里的 message，对表 B。**不要去看 pod 日志——pod 还不存在** |
| 部署状态 failed / pod CrashLoop / readiness 一直不过 | A 层 | `kubectl logs <runtime-pod> -c <runtime容器>`，grep `Error loading configuration from` 与 `Traceback`。有 setup 的还要 grep `setup command failed` |
| 部署绿了，一发 chat 就报错 | C 层 | 看 chat 响应体的 `code` 字段（`LLM_PROVIDER_UNROUTABLE` 之类）；再看 runtime pod 日志同一时刻的记录 |
| 部署绿、chat 也 200，只是答得不对 | D 层 | 对表 D 逐条排。**这一层不要指望日志报错** |

**第二步：区分加载期 vs 运行期失败的判据。**

- **加载期失败 = pod 起不来 / 每次请求都同样地失败在第一步**。特征：日志里有 `Error loading configuration from <path>:`，或 `ModuleNotFoundError` / `TypeError: __init__()`，且**发生在收到任何 chat 请求之前**。这类失败对**所有会话**一视同仁。
- **运行期失败 = pod 是 Ready 的，失败挂在具体一次调用上**。特征：能看到 chat 请求进来、有 trace/span、失败带 session 维度。422 `LLM_PROVIDER_UNROUTABLE` 是典型 —— 它每次请求都发生，看着像"部署坏了"，但 pod 完全健康。

**第三步：常见误判纠正。**

1. **「部署成功」≠「模型配对了」** —— 上传/部署期完全不校验 model 可路由性（`versions.rs:1296-1299`）。模型问题只会在 chat 期暴露。
2. **「setup 没报错」≠「依赖装上了」** —— setup 失败只打 WARNING。必须 grep pod 日志。
3. **「本地跑通了」≠「云上能跑」** —— 沙箱 env 继承、LLM 注入、`/agent` 只读三处行为都不同。
4. **「YAML 里注释掉了」≠「失效了」** —— Python runtime 在 `safe_load` 之前对全文替换 `${env.X}` / `${variables.X}`，注释里的照样解析。要真删。
5. **看不到任何报错，不代表配置对了** —— `tools:` / `skills:` 条目拼错是**完全静默**的。改完配置没效果时，第一件事是逐字符核对字段名，而不是怀疑平台。
6. **别把「模型编了个兜底回答」当成「工具没被调用」** —— MCP/HTTP 连接错误会被当 tool 结果回灌给 LLM，表现为一句含糊的"未查到结果"。要看 trace 里那次 tool call 的原始返回。

**第四步：定位到具体一行后，去对应的 references 看机制**（每行末列已标）。
