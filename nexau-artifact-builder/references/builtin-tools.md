# 内置工具（builtin tools）参考

> **本文覆盖**：NexAU 框架自带的全部内置工具清单（工具名 / `binding` 串 / 用途）、按场景怎么选工具、`.tool.yaml` 从哪里复制、三个「框架自动注入、禁止手写」的工具，以及 `.tool.yaml` 的写法规范。
> **什么时候读**：在给 `agent.yaml` 的 `tools:` 列表挑工具、抄 `binding` 串、或写自己的 `.tool.yaml` 时读。
> **不覆盖**：自定义工具（custom_tools）的 Python 函数契约（进程边界 / 注入参数 / 返回值）见 `references/custom-tools.md`；MCP 工具见 `references/mcp-and-subagents.md`。

事实源：NexAU SDK `0.5.0`。文中所有结论都以该版本的实际运行行为为准。

---

## 1. 先决定：这个 agent 到底需要哪些工具

**不存在「所有制品标配 N 件套」。工具按场景选，越少越好——Agent 可见的工具越多，选错的概率越大。**

| 场景 | 建议工具集 | 说明 |
|---|---|---|
| **纯对话 / 纯 prompt 型** | `tools: []` | 完全合法。不要为了「以防万一」挂 `run_shell_command`，那是白送爆炸半径。 |
| **知识库检索（Agentic Search）** | `read_file` + `search_file_content` | 最小可用组合。`search_file_content` 走 ripgrep，是主力检索手段。 |
| ├ 知识库目录层级多 | 再加 `list_directory` | 让模型先看目录再决定读哪个文件，比猜文件名可靠。 |
| ├ 需按文件名 / 路径通配符定位 | 再加 `glob` | 只在真的要按名字匹配时才加。 |
| └ 一次要读一批同类文件 | 再加 `read_many_files` | 批量读，省往返。 |
| **要产出文件（报告 / 文档 / 代码）** | 上面的基础上加 `write_file`，改已有文件再加 `replace` | 多处改同一文件用 `multiedit_tool`；打 diff 补丁用 `apply_patch`。 |
| **要跑脚本 / 系统命令**（转换格式、调 CLI、`tar`/`chmod`） | 再加 `run_shell_command` | 只在真的需要系统命令时加。列目录别用它，用 `list_directory`。 |
| ├ 命令是长跑服务 / watcher | 再加 `BackgroundTaskManage` | 配合 `run_shell_command` 的 `is_background` 用。 |
| └ 只是想跑一段 Python | 用 `run_code_tool` 代替 shell | 直接在沙箱里执行 Python 代码块，不用手写临时脚本文件。 |
| **要读图片 / 视频** | `read_visual_file` | 只认图片（png/jpg/jpeg/gif/bmp/webp/tiff/tif/svg）和视频（mp4/avi/mov/mkv/webm/flv/wmv/m4v）两类扩展名，见 §2.1 的 🚫。 |
| **要读 PDF / Office 文档** | 🚫 **没有内置工具**，用 `run_shell_command` 在沙箱里跑解析脚本 | `read_file` 对 `.pdf/.docx/.xlsx/.pptx` 等直接返回 `BINARY_FILE` 错误，`read_visual_file` 也不认。沙箱镜像预装了 PyMuPDF / pdfplumber / python-docx / openpyxl 等解析库，见 `references/nexau-json-and-packaging.md` 的沙箱依赖清单。 |
| **要联网搜索**（需 `SERPER_API_KEY`） | `WebSearch` | 走 Serper API，**必须有 key**。见 §2.3。 |
| **要抓指定 URL**（只需出网，无需 key） | `WebFetch` | 直连 httpx GET，**不读 `SERPER_API_KEY`**。见 §2.3。 |
| **多轮长任务，需要待办/记忆/收尾** | `write_todos` / `save_memory` / `complete_task` | `complete_task` 常配 `stop_tools`（必须显式声明，见 `references/mcp-and-subagents.md`）。 |
| **需要向用户反问澄清** | `ask_user` | 见 §5 的 `type` 合法值。 |
| **外部服务 / 数据库** | 走 `custom_tools` 或 `mcp_servers`，不是内置工具 | 见 `references/custom-tools.md` / `references/mcp-and-subagents.md`。 |

参照系（本 skill 的 cookbook 模板实际用量）：`09-content-guardrail` 只挂 `read_file` 一个；`01-agentic-rag` 挂 3 个；`05-native-driver-airgap` 只挂 1 个自定义工具、零内置工具；`04-mcp-server` 的 agent.yaml **根本没有 `tools:` 键**、全走 `mcp_servers:`；只有 `10-reference-skeleton` 才挂到 11 个内置工具。

---

## 2. 完整内置工具清单

`binding` 串必须逐字照抄，大小写敏感。解析规则：按**最后一个 `:`** 切成模块路径 + 属性名，import 模块后先查模块命名空间，找不到再回落模块的 `__getattr__`——所以走 `__getattr__` 懒加载导出的函数也能正常绑定。

### 2.1 file_tools（9 个）

`nexau.archs.tool.builtin.file_tools` 的包级导出，`__all__` 9 项全部可绑。

| 工具名 | binding | 用途 |
|---|---|---|
| `read_file` | `nexau.archs.tool.builtin.file_tools:read_file` | 读单个**文本**文件，支持 offset/limit 分页。默认一次 2000 行、文件 >10MB 直接拒。二进制/PDF 见下方 🚫 |
| `write_file` | `nexau.archs.tool.builtin.file_tools:write_file` | 创建 / 覆盖文件 |
| `replace` | `nexau.archs.tool.builtin.file_tools:replace` | 单文件内精确字符串替换 |
| `apply_patch` | `nexau.archs.tool.builtin.file_tools:apply_patch` | 应用 unified diff 补丁 |
| `glob` | `nexau.archs.tool.builtin.file_tools:glob` | 按 glob 模式找文件，按 mtime 倒序。**函数名固定小写**，见 §4 |
| `list_directory` | `nexau.archs.tool.builtin.file_tools:list_directory` | 列目录内容。**是一等内置工具**，见 §4 提示 |
| `read_many_files` | `nexau.archs.tool.builtin.file_tools:read_many_files` | 批量读多个文件 |
| `search_file_content` | `nexau.archs.tool.builtin.file_tools:search_file_content` | 目录内正则搜索内容，底层 ripgrep，见 §5 |
| `read_visual_file` | `nexau.archs.tool.builtin.file_tools:read_visual_file` | 读图片 / SVG / 视频帧 |

⚠️ `read_visual_file` **只从 `file_tools` 子包导出**，`builtin` 包顶层的 `__all__` / `__getattr__` 里没有它——写成 `nexau.archs.tool.builtin:read_visual_file` 会 `AttributeError`。

🚫 **`read_file` / `read_visual_file` 都读不了 PDF 和 Office 文档**，别按「反正有读文件工具」规划制品：

| 扩展名 | `read_file` 行为 | `read_visual_file` 行为 |
|---|---|---|
| `.pdf` `.doc` `.docx` `.xls` `.xlsx` `.ppt` `.pptx` `.odt/.ods/.odp` `.zip/.tar/.gz` `.db/.sqlite` `.whl/.jar` 等 | 命中内置的「不支持的二进制扩展名」黑名单，返回 `{"error": {"type": "BINARY_FILE"}}`、**一个字节内容都不给模型** | 被判成 `unknown` 类型（它只认图片 / 视频两类扩展名白名单），同样读不了 |
| `.mp3` `.wav` `.aiff` `.aac` `.ogg` `.flac` 音频 | 返回占位文本 `Read binary file (.mp3) - content not displayed to model`，**内容不进模型**——不是「支持音频」 | 不认 |
| `.svg` | 自动委派给 `read_visual_file`（`.svg` 不需要 `enable_visual`） | 需要沙箱内装了 **Inkscape** 才能栅格化，否则抛 `SvgConversionUnavailableError` |
| 图片 / 视频 | 只有显式传 `enable_visual=true` 才委派 | 正常处理。**图片** >10MB 拒；**视频**走 ffmpeg 流式抽帧、无大小上限，默认每 5 秒 1 帧、最多 10 帧 |
| 任意类型 | 先过 **10MB** 总大小闸（超了返回 `FILE_TOO_LARGE`） | — |

要处理 PDF / Office：挂 `run_shell_command` 在沙箱里跑 PyMuPDF / pdfplumber / python-docx 脚本，或写 `custom_tools`（agent-runtime 进程内也装了 PyMuPDF，见 `references/custom-tools.md`）。

也可以直接指子模块（等价，两种都能解析）：`nexau.archs.tool.builtin.file_tools.glob_tool:glob`。本 skill 统一用包级导出写法。

### 2.2 shell_tools（1 个函数）

| 工具名 | binding | 用途 |
|---|---|---|
| `run_shell_command` | `nexau.archs.tool.builtin.shell_tools:run_shell_command` | 在沙箱里 `bash -c <command>` 执行命令 |

⚠️ **`run_shell_command_sync` 不是第二个函数**。`shell_tools` 子包只导出 `run_shell_command` 一个函数。`run_shell_command_sync.tool.yaml` 只是**同一个 binding 的另一份描述**：删掉了 `is_background` 参数、描述改成「同步执行、必须跑完才返回」（两份 yaml 的 `name:` 都是 `run_shell_command`）。想禁掉后台执行就用 sync 那份 yaml，binding 完全一样。

### 2.3 web_tools（2 个）

| 工具名 | binding | 用途 |
|---|---|---|
| `WebSearch`（常注册成 `web_search`） | `nexau.archs.tool.builtin.web_tools:google_web_search` | 联网搜索 |
| `WebFetch`（常注册成 `web_fetch`） | `nexau.archs.tool.builtin.web_tools:web_fetch` | 抓取网页正文 |

⚠️ **两个工具的外部依赖不一样，不要一起判死刑**：

| 工具 | 依赖 | 缺依赖时的行为 |
|---|---|---|
| `WebSearch` → `google_web_search` | **必须** `SERPER_API_KEY`（读的就是这个环境变量名；没有它，内部搜索客户端一构造就 `raise ValueError("Serper API key is required")`） | **不抛异常，静默降级成一条错误文本**：异常被兜住转成 `{"status": "error", "note": "Make sure SERPER_API_KEY environment variable is set"}`，再转成工具返回值 `{"content": "Error: Serper API key is required", "error": {"type": "WEB_SEARCH_FAILED"}}`。模型每次调用都白烧一轮 |
| `WebFetch` → `web_fetch` | **不读 `SERPER_API_KEY`**。仅在 `BP_HTML_PARSER_URL` / `BP_HTML_PARSER_API_KEY` / `BP_HTML_PARSER_SECRET` 三个 env **全都有**时才走 HTML 解析服务，否则回落 `httpx` 直连 GET | 只要沙箱能出网就能用；不能出网才失效 |

⚠️ **名字带 Google，实现是 Serper**，不是 Google 官方 Search API。key 走 runtime scope 环境变量注入（见 `references/env-vars-and-secrets.md`）。

结论：离线 / 气隙部署 **两个都别挂**（没出网）；有出网但没买 Serper key 的环境，**`WebFetch` 可以挂，`WebSearch` 不要挂**。

### 2.4 session_tools（4 个）

`nexau.archs.tool.builtin.session_tools` 的包级导出，4 项全部可绑。

| 工具名 | binding | 用途 |
|---|---|---|
| `write_todos` | `nexau.archs.tool.builtin.session_tools:write_todos` | 维护待办清单 |
| `complete_task` | `nexau.archs.tool.builtin.session_tools:complete_task` | 标记任务完成。**要真正终止循环必须同时写进 `stop_tools:`** |
| `save_memory` | `nexau.archs.tool.builtin.session_tools:save_memory` | 写入会话记忆 |
| `ask_user` | `nexau.archs.tool.builtin.session_tools:ask_user` | 结构化向用户提问，见 §5 |

### 2.5 builtin 顶层其它工具（3 个）

⚠️ 这三个的 binding 路径**形状不一致，必须逐个照抄，不要套统一公式**。

| 工具名 | binding | 用途 |
|---|---|---|
| `multiedit_tool` | `nexau.archs.tool.builtin.multiedit_tool:multiedit_tool` | 单文件多处原子编辑，全成功或全不改 |
| `run_code_tool` | `nexau.archs.tool.builtin.run_code_tool:run_code_tool` | 在沙箱里直接执行 Python 代码块，不是 shell 的别名 |
| `BackgroundTaskManage` | `nexau.archs.tool.builtin:background_task_manage_tool` | 管理 `run_shell_command` 起的后台任务：`status` / `kill` / `list`。**注意是包顶层路径，不带子模块名** |

以上三条 binding 逐字照抄，不要套 §2.1 的路径写法自己推。

### 2.6 不属于内置工具清单的东西（避免误列）

| 东西 | 为什么不在清单里 |
|---|---|
| MCP 工具 | 走 `agent.yaml` 顶层 `mcp_servers:` 自动发现注册，**不在 `tools:` 里写 binding**。见 `references/mcp-and-subagents.md` |
| AgentTeam 工具族（`spawn_teammate` / `create_task` / `broadcast` 等 11 个） | 平行体系，由框架另行动态加载，不属于 `nexau.archs.tool.builtin` 命名空间，也不用你写 binding |
| SDK 内另一处同名的 `read_file` | 同名但完全无关（pandas 格式化用途），没有任何 `.tool.yaml` / binding 引用它，是历史遗留死代码。**别和 `file_tools:read_file` 搞混** |
| 框架包内自带的那份内置工具 REFERENCE 文档 | 它本身已过时（只列 4 类，漏了 `read_visual_file` / `multiedit_tool` / `run_code_tool` / `BackgroundTaskManage` 等）。以本文为准 |

---

## 3. 三个自动注入的工具：`Agent` / `LoadSkill` / `ToolSearch`

🚫 **这三个绝对不要手写进 `tools:`**。它们由框架在三处**不同**代码里按条件自动追加，手写会重复注册或引入不一致的描述。

| 工具 | 自动注入条件 | binding（仅供理解，别抄进 yaml） |
|---|---|---|
| `Agent` | `sub_agents` 非空 | `nexau.archs.tool.builtin.agent_tool:call_sub_agent` |
| `LoadSkill` | `skills` 非空 **或** 任意工具 `as_skill: true` | `nexau.archs.main_sub.skill:load_skill` |
| `ToolSearch` | 存在 `defer_loading: true` 的工具（deferred 数量 > 0） | `nexau.archs.tool.builtin.tool_search:tool_search` |

要点：

- 三者的描述 yaml 由框架**在包内自带并直接读取**，随 pip 包发布，**不需要你复制到制品里**。
- 参数形状（用于写 systemprompt 时对齐）：
  - `Agent`：`{sub_agent_name: string, message: string, sub_agent_id?: string}`，required = `[sub_agent_name, message]`
  - `LoadSkill`：`{skill_name: string}`，required = `[skill_name]`
  - `ToolSearch`：`{query: string, max_results?: integer(default 5)}`，required = `[query]`
- `LoadSkill` 有去重守卫（检测到已有同名工具就跳过注入），`Agent` **没有**——手写一个 `name: Agent` 的工具会和自动注入的那个共存。
- `ToolSearch` 只在真有 deferred 工具时才注册，目的就是避免模型 payload 里出现无用工具。

---

## 4. 工具名有三层，`agent.yaml` 那层说了算

判断「LLM 最终看到的工具名叫什么」，**只能看 `agent.yaml` 的 `tools[].name`**。

```
.tool.yaml 文件名          →  只是文件名，框架完全不看
.tool.yaml 内部 name:      →  source_name，仅在 agent.yaml 没写 name 时生效
agent.yaml tools[].name    →  effective_name，LLM 实际看到的工具名（优先级最高）
```

换句话说：`agent.yaml` 里写了 `name` 就以它为准，没写才回落到 `.tool.yaml` 里的 `name`。

### ⚠️ Glob 的真相

- **文件名**是 `Glob.tool.yaml`（大写 G，历史习惯）——`examples/nexau_building_team/.../tools/Glob.tool.yaml`；另一个样例目录 `examples/cc_agent/tools/` 里同一个工具的文件名就是小写 `glob.tool.yaml`。
- **yaml 内部 `name:` 是小写 `glob`**（两个样例目录都一样）。
- **Python 函数名是小写 `glob`**，binding 里写 `:Glob` 会 `AttributeError`。
- 官方样例里**从来没有**把它注册成大写 `Glob` 过。

所以正确写法是全小写：

```yaml
  - name: Glob                               # ← 用 canonical 表的 key（大写 G）
    yaml_path: tools/Glob.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:glob   # ← binding 的函数名是小写 glob
```

⚠️ **大小写不是风格问题，决定校验器怎么判**（三种组合已实测）：

| `agent.yaml` 的 `name` | `.tool.yaml` 内的 `name` | 校验器 | 为什么 |
|---|---|---|---|
| `Glob` | `glob` | ❌ `tool.name.mismatch` | 两边必须一致：`.tool.yaml` 里写了 `name` 且与 `agent.yaml` 的不同，校验器直接报错 |
| `glob` | `glob` | ⚠️ 装了 nexau 的机器上 PASS，**但脆** | canonical 表按 agent.yaml 的 `name` 查，而表里的 key 是 `Glob` → 小写查不到 → 被当**自定义工具**，import 失败会判 **error** 而不是内置工具的 warning |
| **`Glob`** | **`Glob`** | ✅ **PASS** | 命中 canonical 表，走内置分支（import 失败只 warning） |

**结论：agent.yaml 与 `.tool.yaml` 两边都写 canonical 表里的 key（`Glob`），`binding` 的函数名保持小写 `glob`。**
本 skill 打包的 `templates/_builtin-tool-yamls/Glob.tool.yaml` 已改成 `name: Glob`，直接复制即可
（cookbook 原版是 `name: glob`，从原仓拿要自己改）。
LLM 看到的工具名会是 `Glob`——systemprompt 里也按 `Glob` 描述。

> 这条只有 `Glob` 特殊（canonical 表的 key 大写而函数名小写）。其余 16 个内置工具 key 与常用写法一致。

同类例子：官方样例里有 agent 用 `yaml_path: WebSearch.tool.yaml`（内部 `name: WebSearch`）但顶层写 `name: web_search`，最终 LLM 看到的是 `web_search`。

> **顺带纠正一条旧说法**：「NexAU 不提供 `list_directory`，目录浏览用 `run_shell_command`」是**错的**。`list_directory` 是完整支持的一等内置工具（在 `file_tools` 的 `__all__` 里，官方 `.tool.yaml` 也有）。用 `run_shell_command` 跑 `ls` 替代它是更差的选择：爆炸半径大得多、多一次 shell 往返、输出没结构化。

---

## 5. 两条高频用法要点

### 5.1 检索优先用 `search_file_content`（走 ripgrep）

`search_file_content` 先探测 `rg --version`，可用就走 `rg -n -H -i --no-heading --color never --max-count N`，不可用才降级到纯 Python 实现。

**性能顺序：`search_file_content` ≫ `glob` + 逐个 `read_file` ≫ `run_shell_command` 跑 `grep`。**

- 找**内容**：`search_file_content`。
- 找**文件名 / 路径**：`glob`。
- 看**目录结构**：`list_directory`。
- 以上都不合适、确实需要 `tar` / `chmod` / 调 CLI：才用 `run_shell_command`。

### 5.2 `ask_user` 的 `type` 合法值只有三个

`questions[].type` 的枚举**固定为 `choice`（默认）/ `text` / `yesno`**，没有第四个值。
yaml 侧写作 `enum: [choice, text, yesno]`、`default: choice`；Python 侧的常量与这三个值一一对应，没有别的分支。

写 `.tool.yaml` 描述时必须强调（本 skill 打包的 `ask_user.tool.yaml` 已经强化过这段文案）：

- **总是显式写 `type`**，不要依赖 default。
- 没有固定的 2–4 个选项（用户得自己输路径 / 任意值）→ **必须用 `type: text`**。
- **绝不能发 `type: choice` 且 `options` 为空**，会被拒：Python 侧的选项校验要求 `options` **至少 2 项**、超过 4 项也拒；每个 option 的 `label` 和 `description` 都必填。凑不出至少 2 个真实选项就改用 `text`。
- `header` 必填且最长 32 字符——**Python 侧真会拒**，yaml 侧也有 `maxLength: 32`。
- 一次最多 4 个问题：**这条只由 yaml 的 `maxItems: 4`（jsonschema 校验）兜住**——Python 侧那段 4 题上限检查是**被注释掉的死代码，根本不执行**。如果你自己写的 `.tool.yaml` 漏了 `maxItems: 4`，超过 4 题不会报错。直接用打包版 yaml 就不用操心。

> 注意：本 skill 打包版与官方示例工程里那份 `ask_user.tool.yaml` **schema / enum 完全一致，差异只在 description 文案**。不要把「描述被加强」误传成「新增了枚举值」。

---

## 6. `.tool.yaml` 从哪里抄

### 6.1 优先：本 skill 已打包的副本

```
templates/_builtin-tool-yamls/
```

20 个文件（含 `agent_tool.yaml` / `skill_tool.yaml` 两份**仅供阅读**的自动注入工具描述，别复制进制品）：

```
apply_patch.tool.yaml          ask_user.tool.yaml             BackgroundTaskManage.tool.yaml
complete_task.tool.yaml        Glob.tool.yaml                 list_directory.tool.yaml
read_file.tool.yaml            read_many_files.tool.yaml      read_visual_file.tool.yaml
replace.tool.yaml              run_shell_command.tool.yaml    run_shell_command_sync.tool.yaml
save_memory.tool.yaml          search_file_content.tool.yaml  WebFetch.tool.yaml
WebSearch.tool.yaml            write_file.tool.yaml           write_todos.tool.yaml
agent_tool.yaml (Agent, 只读)  skill_tool.yaml (LoadSkill, 只读)
```

用法：复制到制品的 `tools/` 目录，然后在 `agent.yaml` 的 `tools[].yaml_path` 里指向它。

### 6.2 上游事实源（NexAU 官方示例工程）

这些 `.tool.yaml` 的上游出处是 NexAU 官方示例工程里的两份工具集：

```
examples/nexau_building_team/skills/nexau-agent/builtin_tools/tools/    # 18 个
examples/cc_agent/tools/                                               # 19 个
```

> 拿不到示例工程也没关系：常用的那些**本 skill 的 `templates/_builtin-tool-yamls/` 已经打包好**（见 §6.1），直接复制即可。

- 🚫 有些旧文档给的复制路径指向一个**并不存在的目录**（形如 `.../building-team/skills/nexau-agent/builtin_tools/tools/`），别照抄。
- `apply_patch.tool.yaml` / `multiedit_tool.tool.yaml` / `run_code_tool.tool.yaml` / `glob.tool.yaml`（小写文件名）只在 `examples/cc_agent/tools/` 有；`run_shell_command_sync.tool.yaml` / `read_file_with_visual_support.tool.yaml` 只在 `nexau_building_team` 那份有。
- ⚠️ **`multiedit_tool.tool.yaml` 和 `run_code_tool.tool.yaml` 没有被打进 §6.1 的 `templates/_builtin-tool-yamls/`**。§1 场景表里如果选了这两个，必须从 NexAU 官方示例工程的 `examples/cc_agent/tools/` 手动复制。
- ⚠️ **各 examples 目录之间同名文件的内容不完全一致**（描述文案有差异）。复制前认准**一个**目录做唯一事实源，不要东抄一个西抄一个。

### 6.3 ⚠️ nexau pip 包本身不带这些 yaml

nexau pip 包本体（排除示例工程）**一个 `*.tool.yaml` 都没有**。随包发布的只有三份内部描述文件——`Agent` / `LoadSkill` / `ToolSearch` 那三个自动注入工具的描述——而这三份是框架自己读的，你既不需要也不应该复制。

**结论：内置工具的 `.tool.yaml` 必须由你自己打进制品的 `tools/` 目录，不能指望运行时从包里找到。**

---

## 7. `.tool.yaml` 写法规范

`.tool.yaml` 由一个 pydantic schema 严格解析，且**声明了 `extra="forbid"` —— 顶层写了未知 key 直接 ValidationError 硬失败**。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `type` | `"tool" \| None` | 否 | 写就必须是字面量 `tool`。建议写上（可读性 + 静态校验器友好） |
| `name` | `str` | **是** | source_name；会被 `agent.yaml` 的 `tools[].name` 覆盖（见 §4） |
| `description` | `str` | **是** | 给 LLM 看的工具说明。这是选对工具的关键，写清楚「什么时候用 / 什么时候不用」 |
| `input_schema` | `dict` | 否（默认 `{}`） | 标准 JSON Schema。见下方警告 |
| `skill_description` | `str \| None` | 否 | `as_skill: true` 时用的简述 |
| `disable_parallel` | `bool` | 否（默认 false） | 禁止与其它工具并行调用 |
| `lazy` | `bool` | 否（默认 false） | 🚫 **写在 `.tool.yaml` 里没用**，见下方说明。要开延迟 import 只能写在 `agent.yaml` 的 `tools[].lazy` |
| `defer_loading` | `bool` | 否（默认 false） | 置 true 会触发 `ToolSearch` 自动注入（见 §3）。写在 `.tool.yaml` **有效**（与 `lazy` 不同） |
| `search_hint` | `str \| None` | 否 | 配合 ToolSearch 的检索提示 |
| `template_override` / `formatter` | `str \| None` | 否 | 结果渲染定制 |
| `binding` | `str \| None` | 否 | yaml 内也可写 binding；`agent.yaml` 没给 binding 时才回落到它 |
| `builtin` | `str \| None` | 否 | schema 接受，但框架加载工具时**从不读它**。**写了不报错也不生效，别写** |

### 🚫 `lazy` 与 `defer_loading` 的覆盖行为不对称（易踩）

两者的合并规则本身是一样的——「`agent.yaml` 那层传进来的值是 `None` 才回落 `.tool.yaml`」——但 `agent.yaml` 未写这两个键时传进来的默认值不一样：

| 字段 | `agent.yaml` 未写时传入的值 | 结果 |
|---|---|---|
| `lazy` | **`False`（不是 `None`）** | 永远走「用传入值」那条分支 → **`.tool.yaml` 里的 `lazy: true` 被无声覆盖成 `False`** |
| `defer_loading` | **`None`** | 回落到 yaml 值 → `.tool.yaml` 里的 `defer_loading: true` **生效** |

所以：想让某个工具延迟 import，**必须写在 `agent.yaml` 的 `tools[].lazy: true`**，写进 `.tool.yaml` 等于没写（也不会报错）。

最小骨架：

```yaml
type: tool
name: my_tool
description: >-
  一句话说清这个工具做什么。然后写：什么输入下用它、什么情况下不要用它、
  返回什么形状。描述写得越准，模型选错工具的概率越低。
input_schema:
  type: object
  properties:
    query:
      type: string
      description: 参数说明也要写清楚，模型是照着这个填参的。
  required:
    - query
```

### 🚫 `additionalProperties: false` 与 `extra_kwargs` 互斥

**如果这个工具在 `agent.yaml` 里配了 `extra_kwargs:`，`input_schema` 里就绝对不能写 `additionalProperties: false`——每次调用必抛异常。** 报错原文（框架把 `jsonschema.ValidationError` 包成 `ValueError` 抛出）：

```
ValueError: Invalid parameters for tool '<工具名>': Additional properties are not allowed ('<extra_kwargs 里的键名>' was unexpected). params={...}
```

机制：每次调用时框架先把 `extra_kwargs` 和本次入参合并成一份 params，送进 `jsonschema.validate` 之前**只剔除四个注入参数**（`agent_state` / `global_storage` / `sandbox` / `ctx`）——`extra_kwargs` 的 key **不被剔除**，原样参与校验。

正确做法：**用了 `extra_kwargs` 就把 `additionalProperties: false` 这一行删掉。** 完整机制、两种写法的取舍、以及 `extra_kwargs` 的保留键限制，见 `references/custom-tools.md`。

### ⚠️ 保留参数名的守卫只查 `input_schema` 顶层

框架只检查 `input_schema` 的**顶层 key** 里有没有 `global_storage` / `agent_state` / `ctx`（有就 raise）。写在 `properties:` 下面**能静默通过**并泄漏进模型 schema。这四个保留名（含 `sandbox`）一律不要出现在 `input_schema` 的任何层级。

---

## 8. 可直接抄的 `agent.yaml` 片段

```yaml
tools:
  # —— 知识库检索最小组合 ——
  - name: read_file
    yaml_path: tools/read_file.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:read_file
  - name: search_file_content
    yaml_path: tools/search_file_content.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:search_file_content

  # —— 目录层级多时再加 ——
  - name: list_directory
    yaml_path: tools/list_directory.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:list_directory

  # —— 需要按文件名匹配时再加（注意全小写 glob）——
  - name: glob
    yaml_path: tools/Glob.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:glob

  # —— 需要产出文件时再加 ——
  - name: write_file
    yaml_path: tools/write_file.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:write_file
  - name: replace
    yaml_path: tools/replace.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:replace

  # —— 确实需要跑系统命令时才加 ——
  - name: run_shell_command
    yaml_path: tools/run_shell_command.tool.yaml
    binding: nexau.archs.tool.builtin.shell_tools:run_shell_command
```

⚠️ `tools` 列表的条目**不做 schema 级严格校验**（配置模型里就把它声明成 `list[Any]`）：**框架不认识的 key 会被静默忽略、不报错**——写错 `bindings:` / `yamlpath:` / `extra_kargs:` 都不会有任何提示。真正会 `ConfigError` 硬失败的只有下面这几条显式检查：

- 缺 `name`
- 缺 `yaml_path`
- `lazy` 不是 bool
- `defer_loading` 既非 null 也非 bool
- `extra_kwargs` 不是 dict（报 `... must be a dictionary`）
- `extra_kwargs` 含保留键 `agent_state` / `global_storage`（**注意：只查这两个，`sandbox` / `ctx` 不查**）
- `permissions` 不是 dict

`binding` 拼错的表现尤其绕：`agent.yaml` 没给 `binding` 时会回落到 `.tool.yaml` 里的 `binding`，两边都没有才在**第一次被 LLM 调用时**抛 `ValueError: Tool '<名字>' has no implementation`——加载期完全不报。

调试「工具没生效 / `extra_kwargs` 没传进去」时先逐字核对字段名拼写。详见 `references/agent-yaml-fields.md` 的校验强度分层。
