# 模板：REST API 工具封装（02-rest-api-tool）

> 把一个外部 REST API 的 N 个端点，批量包成 Agent 能调的工具。🟢 Level 1 入门 · 来源：nexau-cookbook《金融数据智能体》（Finnhub，18 端点）。

## 这个模板教你什么

1. **工具三件套的机械化复制**：`tools/<name>.tool.yaml`（schema） + `custom_tools/<mod>.py`（实现） + `agent.yaml` 的一条 `tools` entry（binding）。N 个端点 = 这三步重复 N 次，没有第四种写法。
2. **`extra_kwargs` 注入密钥**：API Key 不进 `input_schema`，模型看不见也编不出来；运行时 merge 进参数再调函数。⚠️ 代价是该工具的 `input_schema` **不能写 `additionalProperties: false`**（见「已知的坑」#1）。
3. **一个 HTTP helper 吃掉全部共性**：token 注入 / 空值过滤 / URL 编码 / 超时 / 错误归一，18 个业务函数因此各只有 2-3 行。
4. **「窄数据」而非原始响应**：在工具函数里限条数 + 限字段 + 限字长 + 回传 `total_available`/`showing` 元数据，让模型知道「还有更多，按需再查」。
5. **错误即数据**：任何异常都 `return {"error": "..."}`，绝不向外抛——模型能读懂错误并自行改参重试，栈回溯只会把它带偏。
6. **System Prompt 三段式**：工具地图（有什么）→ 场景映射表（何时用）→ **能力边界**（没有什么）。第三段是防幻觉的闸门，最容易被漏写。

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 替代 |
|---|---|---|
| 答案来自实时外部 HTTP API（行情、天气、工单、内部微服务） | ✅ 正是本模板 | — |
| 答案来自离线文档/法规/手册 | ❌ | `01-agentic-rag` |
| 答案来自关系型数据库 | ❌ | `03-text-to-sql` |
| 对方已经提供 MCP server，不想自己写 Python | ❌ | `04-mcp-server` |
| 需要向量检索的大规模知识库 | ❌ | `06-external-vector-kb` |
| 端点只有 1-2 个、且不带密钥 | ⚠️ 可用但偏重 | 直接给 `run_shell_command` + 一段 curl 说明也行 |
| 离线/内网无出网，API 在内网 | ✅ 可用 | 出网策略见 `../../references/env-vars-and-secrets.md` |

## 目录结构

```
02-rest-api-tool/
├── nexau.json                          # 项目清单：agents 映射 + excluded（打包端约定）
├── agent.yaml                          # 编排层：模型、8 个工具注册、中间件
├── systemprompt.md                     # 指挥官：角色 + 工作流 + 工具地图 + 场景表 + 能力边界（jinja 模板）
├── custom_tools/
│   └── finnhub_api.py                  # 实现层：1 个 HTTP helper + 18 个端点函数（全量保留）
└── tools/
    ├── _FULL-TOOL-LIST.txt             # 裁剪前 21 个 .tool.yaml 的完整文件名清单
    ├── finnhub_quote.tool.yaml         # ↓ 5 个 Finnhub 工具 schema（代表样本，带 extra_kwargs）
    ├── finnhub_symbol_lookup.tool.yaml
    ├── finnhub_company_profile.tool.yaml
    ├── finnhub_basic_financials.tool.yaml
    ├── finnhub_company_news.tool.yaml
    ├── read_file.tool.yaml             # ↓ 3 个内置工具 schema（不带 extra_kwargs）
    ├── search_file_content.tool.yaml
    └── run_shell_command.tool.yaml
```

⚠️ `custom_tools/finnhub_api.py` 里是**全量 18 个函数**，而 `tools/` 只裁剪保留了 **5 个** schema、`agent.yaml` 只注册了这 5 个。
**没有 `.tool.yaml` + 没在 `agent.yaml` 注册的函数 = 模型完全够不着**（它只是躺在那儿当端点参考）。要启用第 6 个：补 schema → 注册 → systemprompt 两张表补行，三处缺一不可。

## 复制后必须改的地方

按顺序改，每步都会影响下一步。

| # | 文件:字段 | 改成什么 |
|---|---|---|
| 1 | `nexau.json:agents` | `{"<你的agent名>": "agent.yaml"}`，key 必须等于 `agent.yaml` 的 `name` |
| 2 | `agent.yaml:name` / `description` | 你的 agent 名（snake_case）与一句话职责；`description` 会进模型上下文，写清楚能干嘛 |
| 3 | `custom_tools/finnhub_api.py` → 重命名为 `custom_tools/<你的api>_api.py` | 改 `_BASE_URL`；改 `_finnhub_get` 的鉴权方式（query token → 若你的 API 用 Header，改成 `req.add_header("Authorization", f"Bearer {api_token}")`）；删掉 18 个 finnhub 函数，按你的端点重写 |
| 4 | `tools/*.tool.yaml` | 一个端点一个文件。`name` = Python 函数名；`properties` 的 key = 函数形参名（**必须逐字对应**）；`description` 用「用户会怎么问」的口吻写，不要抄 API 文档 |
| 5 | `tools/*.tool.yaml:input_schema` | 带 `extra_kwargs` 的工具**不要加** `additionalProperties: false`；不带的（如内置三件套）保留即可 |
| 6 | `agent.yaml:tools` | 每个端点一条 entry：`name` / `yaml_path` / `binding: custom_tools.<模块名>:<函数名>` / `extra_kwargs`。删掉用不到的 Finnhub entry |
| 7 | `agent.yaml:tools[*].extra_kwargs` | `api_token: ${env.<你的密钥名>}`，并把该变量配到 **runtime scope**（不是 sandbox scope，见下） |
| 8 | `agent.yaml:llm_config.temperature` | 数据类场景保持 `0.2`；创意/文案类可调高 |
| 9 | `agent.yaml:max_iterations` | 多工具综合分析留足预算，`50` 是本例经验值；工具少可降到 `20` |
| 10 | `systemprompt.md` 的两张表 + `# 功能限制` | **三处同步**：工具地图表、场景映射表、能力边界。能力边界要按你的 API 套餐/权限真实写，写空 = 模型必幻觉 |
| 11 | `systemprompt.md:{{ date }}` | 涉及日期参数的 API **必须保留**（配合 `system_prompt_type: jinja`），否则模型用训练截止日期算「最近 7 天」 |
| 12 | 需要额外 pip 依赖时 | 走 `nexau.json` 的 `setup`（离线 whl），见 `../../references/nexau-json-and-packaging.md` |

## 关键设计要点

### 密钥走 extra_kwargs，不进 schema

反例（tutorial 明确点名的两个风险）：把 `api_token` 写进 `input_schema` 让模型填 →
① 泄露：token 进 tool_call JSON → 进对话历史 → 进日志；② 幻觉：模型自己编一个 token 字符串塞进去。

正解就是模板现在的写法——`.tool.yaml` 里只有业务参数，`agent.yaml` 里 `extra_kwargs: api_token: ${env.X}`。

**⚠️ 两条互不可见的密钥通路，别配错 scope：**

| 代码跑在哪 | 读哪个 scope | 本模板 |
|---|---|---|
| `custom_tools/*.py` 函数 → **agent-runtime 进程** | **runtime scope** 环境变量（`${env.X}` 也从这里取值） | ✅ 用这条 |
| `run_shell_command` 起的脚本/CLI → **沙箱** | **sandbox scope** 环境变量 / 单请求 `variables.sandbox_env` | 本模板不涉及 |

cookbook 原教程让你把 `X_FINNHUB_SECRET` 配到「运行配置 → 沙箱环境」，对本模板是**错的**——`extra_kwargs` 的值在 runtime 侧解析，沙箱变量它读不到。详见 `../../references/env-vars-and-secrets.md`。

### 窄数据：工具的责任是「喂」不是「倒」

| 端点特征 | 策略 | 本模板实例 |
|---|---|---|
| 条目多（新闻、交易流水） | 截前 N 条 + 回传 `total_available` / `showing` | `finnhub_company_news` 取 10；`finnhub_market_news` 取 15；`finnhub_insider_transactions` 取 20 |
| 字段多 | 二十几个字段里只挑 3-5 个 | company_news 只留 headline/source/datetime/summary/url |
| 单字段过长 | 截断加省略号 | summary 截到 200 字 |
| 内嵌巨型对象 | 只回 keys 摘要 + 「要详情按 key 再查」提示 | `finnhub_financials_reported` 的 `report_sections`；`finnhub_basic_financials` 的 `series_summary` |

### 错误即数据

`_finnhub_get` 的 4 个 except 分支全部 `return {"error": ...}`。理由：抛异常 → 框架把栈回溯塞进模型上下文（又长、又暴露内部实现、还让模型以为「工具坏了」而放弃任务）；返回 error 字典 → 模型能读懂 `HTTP 401` 是 token 问题、`404` 该换个代码重试，并向用户解释。
配套：systemprompt 的「错误处理：如果工具返回错误，解释发生了什么并建议替代方案」必须留着。

### 能力边界是防幻觉第一闸

没有 `# 功能限制` 那一节时：用户问「给我苹果过去一年 K 线」→ 模型没有对应工具，就会**乱选一个**（比如 `finnhub_quote`），拿一次实时报价冒充 K 线交差。有了这一节，它会明说「不在工具范围内，可以用 xxx 近似替代」。
你换 API 后必须重写这一节；套餐升级解锁新端点了，记得回头删对应限制行。

### ContextCompactionMiddleware：工具密集型必挂

一次综合分析可能连调 6 个工具、每个返回几 KB JSON，再叠多轮追问就顶到 context 上限。`threshold: 0.6` 偏激进，适合工具输出多的 agent；对话密集、工具输出少的用 `0.7~0.8`。参数全集见 `../../references/middlewares.md`。

## 已知的坑

1. ⚠️ **`extra_kwargs` × `additionalProperties: false` 必炸（P0，本模板中招过）**
   框架先 `merged_params = {**extra_kwargs, **params}`，再做 jsonschema 校验，而校验前**只剔除** `agent_state / global_storage / sandbox / ctx` 这 4 个注入键，**不剔除 `extra_kwargs`**。
   报错原文：`ValueError: Invalid parameters for tool 'X': Additional properties are not allowed ('api_token' was unexpected)`。
   **修法：该工具的 `input_schema` 删掉 `additionalProperties: false`。**
   ❌ 不要改成「把 `api_token` 补进 `properties`」——那样模型就看得见密钥参数、还能覆盖它，等于绕回了泄露/幻觉。
   ✅ 只声明 `agent_state` / `sandbox` 注入而**没有** `extra_kwargs` 的工具（本模板的内置三件套）不受影响，`additionalProperties: false` 可以留。

2. ⚠️ **`agent.yaml` 注册了但 `tools/` 里没有对应 `.tool.yaml` → 加载期 `FileNotFoundError: Tool YAML file not found`**，整个 agent 起不来。裁剪工具时必须成对删。

3. ⚠️ **中间件 import 路径必须带 `execution` 这一层**：`nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware`，漏了直接 import 失败。

4. ⚠️ **`${env.X}` 是加载期对 agent.yaml 全文做正则替换**（在 `yaml.safe_load` 之前），**连 YAML 注释里的 `${env.X}` 也会被解析**；变量未设置 = 加载期 `ConfigError` 硬失败，不支持默认值语法、不支持转义。
   → 在 agent.yaml 里写注释时，别顺手举 `${env.某变量}` 的例子。
   → `${env.LLM_MODEL}` 依赖平台注入；**项目一张可见模型卡都没有时该变量不会被注入**，agent 加载即 ConfigError。

5. ⚠️ **打包硬约束**：压缩包 ≤ 100 MiB（超限 413）；归档只允许普通文件和目录，**含符号链接必 400 失败**；必须含 `nexau.json`。

6. ⚠️ **`nexau.json` 的 `excluded` 平台完全不解析**，只是打包端约定。别指望它替你把 `.env` 挡在包外——密钥不入包要靠打包时自己确认。

7. **返回体积要实测**。工具返回值最终 100% 进模型上下文；上线前用真实调用测一次单次返回 token 数，过大就在函数里再加一层摘要。

8. ✅ **本模板已通过平台的制品静态校验器**（实测 `pass: true`、0 error、0 warning）。
   曾经卡住的两条已修（改法见下方改动表）：

   | error code | 曾经的现状 | 现在的写法 |
   |---|---|---|
   | `agent.system_prompt.required_pattern_missing` | `systemprompt.md` 没写「skills 根目录位于 `/home/user/.skills/`」 | 校验器**无条件**要这句，哪怕一个 skill 都没挂 → 已在 `# 运行时路径约定` 一节写入，并说明「以 `LoadSkill` 返回的 `SkillFolder` 为权威路径」 |
   | `skills.invalid_type` | `agent.yaml` 没有 `skills` 键 | 已补 `skills: []`。⚠️ 必须写显式 `[]`，只写 `skills:` 加一行注释会被 YAML 解析成 `null`，照样报 `skills.invalid_type` |

   两条都**不影响运行**（框架允许无 skills、systemprompt 内容自由），但你自己改造本模板时别把它们删回去——平台校验流水线会拦。

## 本模板相对 cookbook 原版的改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `tools/finnhub_{quote,symbol_lookup,company_profile,basic_financials,company_news}.tool.yaml` | 删除 `additionalProperties: false`；`input_schema` 上方加 2 行 ⚠️ 注释 | **P0，实测必炸**：这 5 个工具都带 `extra_kwargs: api_token`，该键会被 merge 进参数后参与 jsonschema 校验 |
| `agent.yaml` | `llm_config` 收敛为 `model` + `max_tokens` + `temperature`，删除 `api_type` / `base_url` / `api_key` / `stream`，并加注释说明「本地裸跑 NexAU 需自行补 base_url / api_key」 | NAC 上 `base_url`/`api_key` 被平台无条件覆盖、`api_type` 被模型卡派生值覆盖、`stream` 在流式路径强制 True——写了是噪声，会误导读模板的人以为这些能配 |
| `agent.yaml` | 删掉重复的 `max_iterations: 300`（第 7 行），只留 `max_iterations: 50` | 原版同一文件里 `max_iterations` 出现两次，YAML 后者覆盖前者 → 显眼的 `300` 其实**静默无效**，纯误导 |
| `agent.yaml` | `tools` 从 18 个 Finnhub entry 裁到 5 个（内置 3 个不变）；补裁剪说明注释 | 与裁剪后的 `tools/` 对齐。不裁的话 13 个 entry 指向不存在的 `.tool.yaml`，**加载期 FileNotFoundError，模板开箱即坏** |
| `agent.yaml` | 加注释：env 占位符读 **runtime scope**；中间件 import 必须带 `execution` 层；内置三件套可保留 `additionalProperties: false` | 把三条易错点钉在使用现场 |
| `systemprompt.md` | 工具地图表 18 行 → 5 行；场景映射表 18 行 → 5 行；「多工具综合分析」6 步 → 4 步；各加 HTML 注释说明裁剪与「三处同步」规则 | prompt 里宣传了 13 个未注册的工具，模型会去调用不存在的工具并报错；保留分组结构以留住教学价值 |
| `custom_tools/finnhub_api.py` | 只改模块 docstring：`${env.X-Finnhub-Secret}` → `X_FINNHUB_SECRET`；删掉「Only stdlib modules are used so the code runs inside a NexAU sandbox」；补「custom_tools 跑在 agent-runtime 进程内 / runtime 镜像已带 httpx、requests / 只有 5 个函数被注册」 | ① 原变量名写错，与 agent.yaml 不一致；② **「沙箱只有 Python 标准库」已过时**：custom_tools 根本不在沙箱里跑，且 agent-runtime 镜像自带 httpx/requests、沙箱也预装了 `/opt/sandbox-python` venv（requests/httpx/pandas/PyMuPDF/playwright 等）。函数体沿用 urllib 无害，故未动代码 |
| `nexau.json` | **未改**（逐字保留） | `excluded` 平台不解析，但作为打包端约定无害；`start.py` 是原样例遗留 |
| `tools/read_file`、`search_file_content`、`run_shell_command`.tool.yaml | **未改**（保留 `additionalProperties: false`） | 这三个不带 `extra_kwargs`，其注入参数 `agent_state`/`ctx` 在校验前会被剔除，不触发 P0 |
| `agent.yaml` | 在 `tools` 与 `middlewares` 之间补 `skills: []`（含「只留注释会被解析成 null」的提醒注释） | 消除平台静态校验 `skills.invalid_type`：`skills` 是必需的列表字段，本模板不挂 skill 故为空列表 |
| `systemprompt.md` | 新增 `# 运行时路径约定` 一节（在 `# 功能限制` 与 `# 上下文` 之间）：说明本 Agent 未挂 skill，但 skills 根目录位于 `/home/user/.skills/`，且读取 skill 内文件以 `LoadSkill` 返回的 `SkillFolder` 为权威路径 | 消除平台静态校验 `agent.system_prompt.required_pattern_missing`：校验器无条件正则匹配这句话。写成一段带上下文的说明而非孤零零一行，避免对模型产生「我有 skill 可用」的误导 |
| `custom_tools/__pycache__/` | 删除（`finnhub_api.cpython-312.pyc`） | 本地运行遗留的字节码产物，不该进模板/制品包；`nexau.json` 的 `excluded` 只是打包端约定、平台不解析，靠它挡不住 |

**裁剪掉的文件**：13 个 Finnhub `.tool.yaml`（earnings_calendar / earnings_surprises / esg / financials_reported / insider_sentiment / insider_transactions / ipo_calendar / lobbying / market_news / market_status / peers / recommendation / sec_filings）。
完整文件名清单见 `tools/_FULL-TOOL-LIST.txt`；**对应的 18 个 Python 实现全部保留在 `custom_tools/finnhub_api.py`**，照着任一现存 `.tool.yaml` 的形状补写 schema 即可恢复。原始完整目录见 nexau-cookbook《金融数据智能体》/`finnhub-agent/`。

## 延伸

- 工具字段全集与 `binding` 写法 → `../../references/custom-tools.md`
- 内置工具清单与 schema → `../../references/builtin-tools.md`（现成 schema 在 `../_builtin-tool-yamls/`）
- 密钥 scope、`${env.X}` 语义、注入时机 → `../../references/env-vars-and-secrets.md`
- `llm_config` 各字段在 NAC 上的实际命运 → `../../references/llm-config.md`
- `ContextCompactionMiddleware` 参数全集 → `../../references/middlewares.md`
- 打包/`nexau.json`/`setup` 离线依赖 → `../../references/nexau-json-and-packaging.md`
- 报错速查 → `../../references/troubleshooting.md`
- 相关模板：`04-mcp-server`（对方已有 MCP 就别自己写工具）、`03-text-to-sql`（数据源是 DB）、`01-agentic-rag`（数据源是文档）
