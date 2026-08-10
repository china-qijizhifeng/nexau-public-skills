# 平台官方制品规范（静态校验器规则）

> **本文覆盖**：NAC 平台自带的**制品静态校验器**的全部规则——它比「框架能不能跑」严格得多，
> 是官方认可的制品写法。逐条给出规则、报错码、以及它与框架行为的差异。
> **什么时候读**：生成任何新制品之前（当作 checklist 用）；制品被判不合规时；
> 拿不准「这么写到底行不行」时。
>
> 事实源是平台自带的那套制品规则文件与校验器实现（随平台内置的 Agent4Agent 分发，不在你的制品里）：
> - `builder-static-rules.json` —— 主规则数据
> - `allowed-middlewares.json` —— **中间件白名单**（§9）
> - `builtin-tool-bindings.json` —— **canonical binding 映射**（§6.4）
> - `artifact-hard-rules.md` —— 平台的人工可读总表（⚠️ 见下方「已知自相矛盾」）
> - 校验器脚本本身 —— **实现（判定以它为准）**
>
> ### 🚨 已知自相矛盾：平台的散文规范与机器规则打架
>
> 平台自己的散文规范与自己的机器规则**在两处直接打架**，**且两处的正确一方相反**——
> 不要机械地「一律信校验器」或「一律信散文」：
>
> | 议题 | 散文 `artifact-hard-rules.md` 说 | 机器规则 + 校验器实现说 | 本 skill 采信 |
> |---|---|---|---|
> | `references/` 索引文件名 | 「**禁止**在 `references/` 或其子目录内生成 `SKILL.md`；子目录索引用 `index.md` / `overview.md`」 | 规则文件把 `index_file` 配成了 `SKILL.md`，校验器据此强制要求 `references/SKILL.md` 及每个非空子目录的 `SKILL.md` | ✅ **散文对，校验器配置错** → 用 `INDEX.md`，见 §8 |
> | `model` 写裸名 | 「裸名会**静默回落**项目默认」 | **校验器**：判 error `agent.llm_config.model.bare_name`，但它的报错文案跟着散文写「silently falls back」<br>**运行期**：sidecar 发现模型名没有 `provider_name/` 前缀就直接拒绝 → 每次 chat **422** | ✅ **运行期行为对，散文与校验器文案都错** → 裸名会 422、不回落（`llm-config.md` §3.2）。三方在「别写裸名」这个结论上一致，只有「后果是什么」有分歧 |
>
> **裁决方法**：第 2 条有**运行期行为**作证（sidecar 真的会拒），实测行为 > 任何声明；
> 第 1 条双方都只是「规范声明」、没有运行期行为可判，此时按**语义正确性**裁决（见 §8），
> 而 `index_file` 恰好只是一个可改的**配置值**，不是硬编码逻辑。
>
> ### 怎么自己跑这个校验器
>
> 校验器与规则文件随平台内置的 Agent4Agent 分发，不在你的制品里。**手上有这套脚本时**
> （`S` = 校验器脚本目录，`R` = 规则文件目录）：
>
> ```bash
> S=<校验器脚本目录>
> R=<规则文件目录>
> PYTHONPATH=$S python3 $S/validate_artifact_static.py \
>   --artifact-root <你的制品目录> --rules-root $R 2>/dev/null
> ```
>
> 输出 JSON：`pass` 布尔 + `errors[]`（含 `code` / `path` / `message`）。exit code 0=过 / 1=不过。
> ⚠️ 它会往 stderr 打一行 `E2B SDK not installed`，**解析 stdout 前记得 `2>/dev/null`**，否则 JSON 解析失败。

---

## 0. 先分清三层「合不合格」

制品有**三道互相独立**的关卡，报错完全不同，别混：

| 层 | 谁在管 | 不过会怎样 | 细节 |
|---|---|---|---|
| **① 上传硬门** | Backend | HTTP 400/413，制品根本进不来 | `nexau-json-and-packaging.md` §7 |
| **② 框架能不能加载** | NexAU `AgentConfigSchema` / builder | 加载期 `ConfigError`，pod 起不来 | `agent-yaml-fields.md` §6 |
| **③ 官方制品规范** | 平台静态校验器（本文） | **不是上传硬门**——上传照样过、也能跑，但不符合官方规范；由 Agent Debugger / A4A 检查制品时报 error | 本文 |

⚠️ **第 ③ 层比第 ② 层严格**：好几条在框架层完全合法的写法（`system_prompt_type: file`、
`skills` 用对象条目、省略 `binding`、写 `tracers`），静态校验器都判 **error**。
**要产出「官方规范制品」就按本文来。**

> 校验器是 A4A（Agent4Agent）的一个 skill，**不在上传链路上**——制品上传时平台不会调用它。

### 0.1 ② 层也能在上传前自查（别只等 pod 起不来）

框架层「能不能加载」不必等部署完看 pod 日志，本地跑一行就行（需要能 `import nexau` 的环境）：

```bash
# 在制品根目录下跑；三个占位变量只为过 ${env.X} 插值，值随便填
cd <artifact-root> && LLM_MODEL=x LLM_BASE_URL=http://x/v1 LLM_API_KEY=sk-x \
  python -c "from pathlib import Path; from nexau.archs.main_sub.config.config import AgentConfig; \
  c=AgentConfig.from_yaml(Path('agent.yaml')); print('OK', c.name, len(c.tools))"
```

- ⚠️ **必须传 `Path` 不能传 `str`** —— 框架拿 `config_path.parent` 作相对路径基准，传字符串会 `AttributeError: 'str' object has no attribute 'parent'`。
- ⚠️ 用 `AgentConfigSchema.from_yaml` 是**弱版本**：它只做 pydantic 结构校验 + `${env}` 插值，**不解析任何相对路径**，`yaml_path` 写错它照样返回 OK。要预检就用上面的 `AgentConfig.from_yaml`。

它能抓：`${env.X}` 漏建（报出变量名，正好当变量清单对账）、`system_prompt` / `yaml_path` / `skills[]` / `sub_agents[].config_path` 的相对基准写错、`.tool.yaml` 结构错、binding 真实 import 失败（含自定义 binding）、middlewares 实例化参数错。
它抓不到：沙箱路径、平台侧覆盖行为、以及第 ③ 层的官方规范类问题（那层交给静态校验器）。

> 两件工具**有重叠但不等价**：静态校验器已覆盖 `yaml_path` 存在性（`tool.yaml_path.missing`）与内置 binding 的 canonical 性（`tool.binding.non_canonical_builtin`）；`${env.X}` 是否已在平台建好、自定义 binding 的真实可 import 性，只有上面这条命令能替你先探一遍。

---

## 1. 顶层文件与制品闭包

**三个文件必须在制品顶层**（`required_top_level_files`）：

```
nexau.json
agent.yaml
systemprompt.md
```

⚠️ 含义：官方规范假定的是**单 agent、扁平布局**。把 agent.yaml 塞进 `agents/` 子目录
（框架完全支持）不符合这条。

**顶层闭包**（`artifact-hard-rules.md` §1）：

- `nexau.json.agents` 的唯一 agent key **必须等于** `agent.yaml.name`
  （不等 → `nexau_json.agent_name.mismatch`）
- `nexau.json.agents[*]` 指向的 YAML、`agent.yaml.system_prompt` 指向的文件都必须存在，
  且解析后**不得逃逸制品根**
- **制品必须是部署自包含单元**：prompt / skills / tools / custom tools / 脚本 / 知识文件全在制品根内
- 🚫 不得通过 `../`、绝对路径、软链接、或"文案里让模型去读某个开发机路径"依赖制品外的东西

### 1.1 「自包含」具体禁什么：四类逃逸，各由不同的关卡（或没人）拦

平台散文把禁令写成一句话（`artifact-hard-rules.md` §1 / SKILL.md 规则 #4）：不得依赖
**workspace、模板库私有路径、run 临时目录、开发机绝对路径**。落到实处是四类，**归谁管完全不同**——
第 ④ 类没有任何静态关卡，是最该盯的：

| # | 逃逸形式 | 谁会抓到 | 典型踩法 |
|---|---|---|---|
| ① | **归档条目**路径含 `../` 或以 `/` 开头 | **上传 400**（上传期路径规范化就拒） | 在父目录 `tar -czf x.tar.gz my-agent/`（多包一层还带路径前缀）；用绝对路径打包 |
| ② | **归档里有软链接** | **上传 400**：`unsupported tar entry <path>: only regular files and directories are allowed`（zip 走 unix mode 的文件类型位检查） | 为了"共用"把 `skills/common` 软链到模板库或另一个项目目录；`ln -s ~/kb data` |
| ③ | **agent.yaml / nexau.json 声明的路径**解析后逃出制品根 | **静态校验器**四个 error：`nexau_json.agent_yaml.path_escapes_artifact_root` / `agent.system_prompt.path_escapes_artifact_root` / `tool.yaml_path.path_escapes_artifact_root` / `skills.entry.path_escapes_artifact_root`。⚠️ 上传门只兜住其中**第一条**：`nexau.json.agents` 声明的 yaml 在归档里找不到 → 上传 400 `agent yaml files declared in nexau.json not found or empty in artifact`（见 `nexau-json-and-packaging.md` §2.0）。**`agent.yaml` 内部那三条（`system_prompt` / `tools[].yaml_path` / `skills[]`）上传期完全不读，只有校验器管** | `system_prompt: ../shared/systemprompt.md`；`skills: [/Users/me/skills/labor_law]`；从模板库复制 `agent.yaml` 时留着指回模板库的 `yaml_path` |
| ④ | **文案指令**：prompt / SKILL.md / 索引 / 工具描述里让模型去读制品外的路径 | 🚫 **没有任何静态关卡**（详见下方） | systemprompt 写「知识库在 `/Users/me/kb/`，需要时用 `read_file` 读」；SKILL.md 写「完整表结构见 `~/work/schema.md`」；索引里留着生成流程用的 `/tmp/run-xxxx/` 中间产物路径 |

**为什么 ④ 静态抓不到**：校验器只扫**两类文档**——每个 skill 根目录的 `SKILL.md`，
以及 `references/` 下的索引文件；**`systemprompt.md` 一个字都不扫**。而且扫 `SKILL.md` 时还有一道
过滤：目标串里不含 `references/` 且不以 `../` / `./references/` 开头就直接跳过。所以 `SKILL.md` 里写
`` `/Users/me/kb/data.md` `` 是零告警通过的。

同理，下面这几处的路径**也没人扫**，只能自己核：

- `custom_tools/*.py` 里硬编码的开发机路径 —— 校验器只 import 模块、取 symbol（§6.1c），**不看函数体**，
  写死 `open("/Users/me/data/x.json")` 照样 `pass: true`
- `middlewares[].params` 里的路径（如 `lexicon_dir`）—— 校验器只查白名单与参数名（§9）
- `sub_agents[].config_path` / `mcp_servers` 的启动命令 —— **校验器对这两个键零覆盖**

**④ 的运行期表现最阴**：它不像 ③ 那样在加载期 `ConfigError` 把 pod 打挂，而是等模型真去读的时候
`read_file` 返回「文件不存在」，模型多半改口凭记忆现编——**回答看着正常、内容是幻觉**，
比直接崩溃难发现得多。

**正面口径**：制品里凡是要模型去读的路径，合法形状只有两种——

| 读什么 | 写成 | 依据 |
|---|---|---|
| skill 自带资料 | `/home/user/.skills/<skill 目录 basename>/…`（取值以 `LoadSkill` 返回的 `<SkillFolder>` 为准） | `nexau-json-and-packaging.md` §9.1 |
| 制品内其他文件 | `/agent/…`（只读） | 同上 §8 |

`/agent/skills/...` 是**错的**（那是制品源路径，沙箱里不存在）；相对路径也别写（cwd 是 `/home/user`，不是 `/agent`）。

### 1.2 多个 skill 要同一套资料：抽成共享 skill，别互相 cross-link

**硬规则**：一个 skill 的索引 / SKILL.md **不得指向另一个 skill 的 `references/`**，
报 `skills.references.private_external_reference`（error，由 §8 表里的
`forbid_cross_skill_private_references` 开关控制）。
判定逻辑很直白：目标落在 `<制品根>/skills/` 下、**不在**当前 skill 目录内、
且相对 `skills/` 的路径片段里出现 `references` —— 三条同时成立就判 error。

**推荐做法（装配约定，不是 schema 硬约束）**：同一套 source set 被两个以上 skill 需要时，抽成一个独立的共享 skill。三步——

1. **新建目录** `skills/<shared-name>/`：`SKILL.md`（frontmatter 带 `name` / `description`，§7.2）+ 它**自己的** `references/`，
   把公共资料整体搬进去，各级 `INDEX.md` 按 §8.1 补齐。
2. **在 `agent.yaml` 的 `skills:` 里与其它 skill 并列注册**（字符串路径，§7.1）。
   ⚠️ **不注册就等于不存在**：只有注册过的 skill 才会被上传进沙箱、才有
   `/home/user/.skills/<basename>`（`nexau-json-and-packaging.md` §9.1）。
   光建目录不写进 `skills:`，运行期读它必然失败。
3. **原来 cross-link 的那几个 skill，把路径链接删掉**，改成引导模型自己去加载：
   > 本主题的判例 / 表结构资料在共享 skill `<shared-name>` 中。需要时先 `LoadSkill` 它，
   > 再以返回的 `<SkillFolder>` 为基准拼路径，不要凭记忆猜。

⚠️ **抽完之后仍然不能从 A 的索引里链到共享 skill 的 `references/` 文件** ——
校验器不认识"共享"这个概念，只看目标路径是不是落在别的 skill 里。所以第 3 步必须是
**文字引导 + `LoadSkill`**，不能是路径链接，否则照样吃 `private_external_reference`。

⚠️ 共享 skill 的**目录 basename 要在整个制品内唯一** —— 沙箱路径按 basename 拼，
重名会和别的 skill 撞同一个 `/home/user/.skills/<basename>`（`nexau-json-and-packaging.md` §9.4）。

> 两条尺度提醒：
> - 判定只覆盖 `<制品根>/skills/` 下的目录。`skills[]` 指到别处（如 `./kb/xxx`）这条抓不到——
>   **那是判定盲区，不是合规解法**，别拿它绕过。
> - 抽共享 skill 会让模型多一次 `LoadSkill` 往返。**确实多个 skill 都要**才抽；
>   只有两处、各自几行的小抄，各留一份反而更省。校验器只在你真的 cross-link 时才报错，
>   不会因为"没抽共享 skill"扣分。

### 1.3 🚫 原始 PDF 不得进制品

用户上传的 PDF 在进制品前**必须先转成 Markdown / 文本 / 结构化结果**，
原始 `.pdf` 不放进生成的制品，并要记录来源与用途（平台散文规范 `artifact-hard-rules.md` §6）。

> 顺带一个框架事实：内置工具**读不了 PDF**——`read_file` 把 `.pdf`/Office 列入
> `UNSUPPORTED_BINARY_EXTENSIONS` 直接返回 `BINARY_FILE` 错误，`read_visual_file` 只认图片/视频。
> 要在沙箱里解析 PDF 得用 `run_shell_command` + 沙箱预装的 `PyMuPDF`/`pdfplumber`。见 `builtin-tools.md`。

---

## 2. agent.yaml 必须钉死的三个值

`required_agent_fields`：

| 字段 | 必须等于 | 与框架行为的差异 |
|------|---------|-----------------|
| `type` | `agent` | 框架层 `type` **可省略**（`Literal["agent"] \| None = None`），规范要求必写 |
| `system_prompt_type` | `jinja` | 框架层 `file` 与 `jinja` **代码等价**，规范只认 `jinja` |
| `tool_call_mode` | `structured` | 框架层默认就是 `structured`，但规范要求**显式写出来** |

## 3. agent.yaml 禁写字段

`forbidden_agent_fields` → 报 `agent.field.forbidden`（error）：

| 字段 | 为什么 |
|------|--------|
| `sandbox_config` | 平台注入是「你没写才注入」，写了平台就不注入 → 沙箱必炸。**框架层也确实会坏** |
| `tracers` | ⚠️ **注意差异**：运行期平台 tracer 与制品自带 tracers 其实是**合并**的（平台侧实测行为），功能上写了能用；但**官方规范判 error**。结论：**别写**，观测交给平台 |

`llm_config` 另有**两条**专门规则（都是 error）：

| 报错码 | 触发条件 | 豁免 |
|---|---|---|
| `agent.llm_config.model.bare_name` | `model` 是字符串且不含 `/`（没有 `provider/` 前缀） | 值里含 `${`（即 `${env.LLM_MODEL}` 这类占位）时**不判** |
| `agent.llm_config.api_key.literal` | `api_key` 是非空字符串 | 同样是含 `${` 就豁免 |

两条都只扫**顶层** `agent_yaml.get("llm_config")`，中间件 params / `fallback_providers` 里的同名字段扫不到。
机理与运行期后果见 `llm-config.md` §3.2 / §7.1，以及本文开头「已知自相矛盾」第 2 行。

## 4. 三个列表键必须存在

`required_list_fields`：`tools` / `skills` / `middlewares`

⚠️ **哪怕是空的也要写出来**：

```yaml
tools: []
skills: []
middlewares: []
```

框架层这三个键都有默认值、可以整个省略；规范要求显式声明。

---

## 5. systemprompt.md 必须包含的话术

`required_systemprompt_patterns` —— 正则：

```
(?i)skills\s*根目录位于\s*`?/home/user/\.skills/?`?
```

即 systemprompt 里必须出现类似这句：

```markdown
skills 根目录位于 `/home/user/.skills/`
```

**这就是为什么本 skill 要求 systemprompt 显式写出 skills 根目录**，而不是只说「用 LoadSkill 返回值」。
两者都要写：路径形状固定（满足规范），取值以 `LoadSkill` 返回的 `<SkillFolder>` 为准（保证正确）。

---

## 6. tools 条目与 .tool.yaml

### 6.1 `tools[]` 条目必填字段

`required_tool_entry_fields`：`name` / `yaml_path` / **`binding`**

⚠️ 框架层 `binding` 是可选的（`str | None = None`），规范要求**每个工具都写 binding**。

### 6.1b 内置工具的 binding 必须与 canonical 映射逐字一致

`builtin-tool-bindings.json` 是 canonical 表（17 条）。**写错 canonical → error；canonical 正确但本地 import 失败 → 只 warning**（允许本地没装 `nexau` 也能做静态闭包检查）。
⚠️ **这条 warning 豁免只对内置工具成立**——自定义工具 import 失败是 **error**，见 §6.1c。

```
read_file             nexau.archs.tool.builtin.file_tools:read_file
write_file            nexau.archs.tool.builtin.file_tools:write_file
replace               nexau.archs.tool.builtin.file_tools:replace
search_file_content   nexau.archs.tool.builtin.file_tools:search_file_content
list_directory        nexau.archs.tool.builtin.file_tools:list_directory
Glob                  nexau.archs.tool.builtin.file_tools:glob
read_many_files       nexau.archs.tool.builtin.file_tools:read_many_files
read_visual_file      nexau.archs.tool.builtin.file_tools:read_visual_file
apply_patch           nexau.archs.tool.builtin.file_tools:apply_patch
run_shell_command     nexau.archs.tool.builtin.shell_tools:run_shell_command
BackgroundTaskManage  nexau.archs.tool.builtin:background_task_manage_tool
WebSearch             nexau.archs.tool.builtin.web_tools:google_web_search
WebFetch              nexau.archs.tool.builtin.web_tools:web_fetch
write_todos           nexau.archs.tool.builtin.session_tools:write_todos
complete_task         nexau.archs.tool.builtin.session_tools:complete_task
ask_user              nexau.archs.tool.builtin.session_tools:ask_user
save_memory           nexau.archs.tool.builtin.session_tools:save_memory
```

⚠️ 左列是 `agent.yaml` 里 `tools[].name` 应写的值（canonical 表的 key）。注意 `Glob` 大写 G，
而其 binding 的函数名是小写 `glob`。

⚠️ **`.tool.yaml` 内部的 `name` 必须与 `agent.yaml` 的 `name` 一致**，否则 `tool.name.mismatch`（error）。
而 canonical 表按 `agent.yaml` 的 `name` 查——**写小写 `glob` 会查不到表 → 该工具被当成自定义工具
处理**（import 失败从 warning 升级成 error）。
所以 `Glob` 这一个要两边都写大写。完整三组合实测对照见 `builtin-tools.md`。

### 6.1c 自定义工具的 binding 规则

- 形如 `python.package.module:symbol`，校验器会在制品根作用域内**真的 import 一遍**
- **必须指向实际定义该 symbol 的最终模块**，不能省掉最后一层实现模块
  （`custom_tools/foo.py` 里的 `run` → `custom_tools.foo:run`）
- 想写成包路径（`custom_tools.pkg:review`），那个包的 `__init__.py` 必须显式 re-export
- `.tool.yaml` 的 `name` 必须与 `agent.yaml.tools[].name` 一致
- `yaml_path` 必须在制品根内，不得用 `../` 或绝对路径逃逸
- **import 失败是 error**（`tool.binding.import_error`），直接把制品判成 `pass: false` —— 与内置工具的 import 失败只报 warning（§6.1b）**不同**。import 成功后还会 `getattr(module, symbol)`，取不到报 `tool.binding.symbol_missing`
- ⚠️ **这一遍 import 跑在你执行校验器的那台机器上**，不是 runtime 镜像里。自定义工具在**模块顶层** `import` 第三方依赖（`httpx` / `pymysql` / `dmPython` 等，**即使已经写进 `nexau.json` 的 `setup`**）时，本地缺包就会吃这条 error。两个解法：① 在装齐依赖的环境里跑校验器；② 把第三方依赖改成**函数内延迟 import**（`templates/05-native-driver-airgap/custom_tools/dameng_sql.py` 就是这么写的——它本意是先 preload 达梦动态库，顺带也躲开了这条误报）。stdlib-only 的工具不受影响（见 `templates/06-external-vector-kb/custom_tools/_map_client.py` 顶部注释）

### 6.2 `.tool.yaml` 必填字段

`required_tool_yaml_fields`：`type` / `name` / `description` / `input_schema`

### 6.3 ⚠️ `.tool.yaml` 是字段白名单

`allowed_tool_yaml_fields` —— **只允许**这 12 个键，写别的会报错：

```
type, name, description, input_schema, skill_description,
disable_parallel, lazy, defer_loading, search_hint,
template_override, builtin, binding
```

⚠️ **框架侧 `ToolYamlSchema` 还有第 13 个字段 `formatter`**，白名单**没有收录**它。
写了会被判 `tool.yaml.unexpected_field`（error），
而且**报错文案会宣称「Tool YAML field is not supported by NexAU ToolYamlSchema: formatter」——那句是错的**
（框架明明支持），别按它去翻框架源码。不写时框架自动回落 `markdown` formatter，绝大多数场景不需要它。

---

## 7. skills 条目与 SKILL.md

### 7.1 `skills[]` 条目必须是字符串路径

`required_skill_entry_kind: "string_path"`

```yaml
skills:
  - ./skills/my-domain          # ✅ 规范要求的写法
  # - { name: x, path: ./skills/my-domain }   # ❌ 框架支持，但规范判不合规
```

### 7.2 SKILL.md frontmatter 必填

`required_skill_frontmatter_fields`：`name` / `description`

---

## 8. ⚠️ references/ 的索引规则（最容易踩）

`skill_reference_rules`：

| 规则 | 含义 | 报错码 |
|------|------|--------|
| `index_file` | 索引文件名。**规则文件里当前配的是 `SKILL.md` —— 这是错的，见下** | — |
| `require_root_index_when_nonempty` | `references/` 非空就必须有根索引 | `skills.references.index_missing` |
| `require_directory_indexes` | **每个非空子目录**都要有自己的索引 | `skills.references.directory_index_missing` |
| `require_referenced_paths_exist` | 索引里引用的路径必须真实存在 | `skills.references.path_missing` |
| `require_referenced_paths_inside_skill_root` | 引用不能逃出 skill 根目录 | `skills.references.path_escapes_skill_root` |
| `require_referenced_paths_inside_references_dir` | 引用必须落在 `references/` 里 | — |
| `forbid_cross_skill_private_references` | 禁止引用别的 skill 的私有文件 | — |

「每层都要有索引」这条本身是对的、必须遵守。**有争议的只有索引文件叫什么名字。**

### 8.1 ✅ 本 skill 的约定：整个 skill 只有一个 `SKILL.md`，内层一律 `INDEX.md`

```
skills/my-domain/
├── SKILL.md                      ← 唯一的 SKILL.md：skill 入口，框架靠它加载
└── references/                   ← 以下都是知识库层级，不是 skill
    ├── INDEX.md                  ← 根索引（必须）
    ├── 主题A/
    │   ├── INDEX.md              ← 子目录索引（必须）
    │   └── 具体文件.md
    └── 主题B/
        ├── INDEX.md
        └── ...
```

**理由（语义）**：`SKILL.md` 是 skill 的入口文件，框架 `Skill.from_folder` 只在 skill 根目录找它。
`references/` 底下是**知识库**，不是 skill，不该占用 skill 专用的文件名——否则「哪个 `SKILL.md`
才是入口」永远靠位置去猜。

与 `skill-knowledge-organizer` skill 的产出**完全一致**（它产出的就是 `INDEX.md`，不用改名）。

⚠️ 与平台散文规范只是**部分**一致，别夸大：`artifact-hard-rules.md` 原文是
「禁止在 `references/` 或其子目录内生成 `SKILL.md`；子目录如需索引用 `index.md` / `overview.md`」——
它在「**references 内不该出现 `SKILL.md`**」这一点上和我们同调，但推荐的具体拼写是小写 `index.md`。
本 skill 取 `INDEX.md`（与 organizer 对齐、大写在文件列表里也更醒目）。**分歧只在拼写，不在原则。**

> 遗留风险（需与平台裁定）：若平台按自己的散文把 `index_file` 改成小写 `index.md` 而不是 `INDEX.md`，
> 本 skill 产出的历史制品还要再改一次名。拼写这件事值得早点跟平台对齐。

### 8.2 ⚠️ 但校验器当前会因此报错——这是平台缺陷，改一行就好

规则文件把索引名配成了 `SKILL.md`：

```jsonc
// builder-static-rules.json 里的 skill_reference_rules 段
"skill_reference_rules": {
  "references_dir": "references",
  "index_file": "SKILL.md",        // ← 这一行应为 "INDEX.md"
  "require_root_index_when_nonempty": true,
  "require_directory_indexes": true,
```

于是 `INDEX.md` 版会被判：1 条 `skills.references.index_missing` + 每个非空子目录 1 条
`skills.references.directory_index_missing`。

**这是配置值的问题，不是校验器逻辑的问题** —— 索引文件叫什么名字完全由规则文件里的
`index_file` 驱动，校验器只是照着读，改这一个值就够了。

**已实测**：把这一行改成 `"INDEX.md"` 后，`INDEX.md` 版的层级化知识库制品
**0 error 通过校验**（用 `templates/01-agentic-rag` 的 `INDEX.md` 版验证）。

> ⚠️ `builder-static-rules.json` 是**平台侧受控的规则文件**，要改得由平台维护者走变更流程。
> **制品作者 / 生成 agent 不要为了让自己这一份制品过检就地编辑它** —— 那会静默改变所有使用者的
> 校验口径，而且很难追溯。在平台修掉之前，把这 N+1 条 error 当**已知噪声**即可。

> 判读口径：这两类 error（`skills.references.index_missing` / `skills.references.directory_index_missing`）
> 属于**校验器配置缺陷**——平台自己的散文和自己的机器规则打架，不是你写错了。
> **注意它与 §9.3 的中间件白名单 error 性质完全不同**：那一类是规范与实现一致、偏离的是你，
> 不能用「都是已知 error」一把放过。

**若交付方硬要「校验器全绿」的截图**：可以把内层索引改名成 `SKILL.md`（实测索引类 error 归零）——
但这会违反 `artifact-hard-rules.md` 的散文禁令，等于**换一头违规**，不是免费的绿灯。
两条路各违平台规范的一头，选哪条要跟交付方讲清楚，别当成「有个零成本合规解没告诉我」。

### 8.3 ⚠️ 索引正文里不要裸写反引号文件名

校验器会把索引正文里 `` `xxx.md` `` 形式的东西**当成路径引用**去解析，解析不到就报
`skills.references.path_missing`。所以下面这句会炸：

```markdown
本目录存放大块资料；上一层 `SKILL.md` 只做概览。   ← ❌ 被解析成 references/SKILL.md，不存在
```

改成不带反引号的自然表述即可：

```markdown
本目录存放大块资料；上一层的 skill 入口文件只做概览。   ← ✅
```

**规律**：索引里的反引号文件名只用来指**本目录下真实存在的文件**；提到别处的文件（skill 入口、
上级目录、未随附的资料）一律用自然语言描述，别加反引号。

---

## 9. middlewares：白名单 + `params` 必填

### 9.1 条目结构

`required_middleware_entry_fields`：`import` / **`params`** —— `params` 必填，没参数也要写 `{}`。

### 9.2 ⚠️ 只允许两个中间件，且参数受限

`allowed-middlewares.json` 全文就这么点（"middleware 不允许自由创新，只能从模板允许项复制"）：

| import | `params_required` | `params_allowed` |
|--------|------------------|-----------------|
| `nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware` | `threshold` | **只有** `threshold` |
| `nexau.archs.main_sub.execution.middleware.long_tool_output:LongToolOutputMiddleware` | 无 | **一个都不允许**（`params: {}`） |

合规写法：

```yaml
middlewares:
  - import: nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware
    params:
      threshold: 0.6
  - import: nexau.archs.main_sub.execution.middleware.long_tool_output:LongToolOutputMiddleware
    params: {}
```

### 9.3 ⚠️ 白名单窄是**平台有意收窄**，不是没跟上

框架实际有 **7 个**可用中间件（见 `middlewares.md`），白名单只放行 2 个；
`LongToolOutputMiddleware` 的 7 个真实参数在白名单里**一个都不允许**。

**别把这当成「规范滞后可以无视」**——平台散文规范 `artifact-hard-rules.md` §5.1 标题就是
**「不允许自由创新」**，正文「middleware 不允许自由创新，只能从 `allowed-middlewares.json`
中的模板允许项复制」。这是**刻意的策略**（约束制品生成 agent 乱发挥），不是忘了更新的清单。

所以用白名单外的中间件 = **有意偏离官方规范**，这是一个需要你自己承担的取舍，不是「误报」：

| 你想用 | 校验器会说 | 取舍 |
|--------|-----------|------|
| `SensitiveWordMiddleware`（内容安全护栏） | `middleware.not_allowed` | 框架层完全可用（`templates/09-content-guardrail` 就是它）。政企合规场景往往**必须**有护栏，此时可以有意偏离——但要清楚制品不符合官方规范，交付前跟对方确认 |
| `RoundAndTokenReminder` / `RuntimeEnvironment` / `LLMFailover` | `middleware.not_allowed` | 同上，且这几个的收益通常没到「值得偏离规范」的程度，**优先考虑不用** |
| 给 `LongToolOutputMiddleware` 调参 | `middleware.params.unexpected` | **优先写 `params: {}` 用默认值**；默认值确实不够用再考虑偏离 |

**判断口径**：拿到一片红色 error 时先分清三类，处置完全不同——

| 类别 | 典型报错码 | 性质 | 该怎么办 |
|---|---|---|---|
| ① **校验器配置缺陷** | `skills.references.index_missing` / `directory_index_missing` | 平台散文与自家机器规则打架（§8.2） | 默认当已知噪声；**别去编辑平台的规则文件**。交付方硬要全绿时另有一条换名的路，代价见 §8.2 |
| ② **你有意偏离规范** | `middleware.not_allowed` / `middleware.params.unexpected` | 规范和实现一致，偏离的是你 | 自己承担取舍，交付前跟对方确认 |
| ③ **校验环境不完整** | `tool.binding.import_error` 且括号里是 `No module named 'X'` | 既不是滞后也不是偏离，是跑校验器的机器缺包（§6.1c） | 装上 X，或把该依赖改成函数内延迟 import。**不要动 binding、不要拆模块、更不要删依赖** |

②这一类要不要偏离取决于业务，但**不能当成「无害误报」一笔带过**。

---

## 10. 工具与 stop_tools 的联动

`required_stop_tools_by_tool`：

| 挂了这个工具 | 就必须把它写进 `stop_tools` |
|------------|---------------------------|
| `ask_user` | `stop_tools: [ask_user]` |

> 同理（框架语义，非本校验器规则）：子代理挂了 `complete_task` 也必须写进
> `stop_tools`，否则不会结束——见 `mcp-and-subagents.md`。

---

## 11. 一份「官方规范」骨架

把上面全部规则落到一起，最小合规 agent.yaml：

```yaml
type: agent                        # §2 必须
name: my_agent
description: 一句话说明

system_prompt: ./systemprompt.md
system_prompt_type: jinja          # §2 必须是 jinja，不能是 file

llm_config:
  model: ${env.LLM_MODEL}
  max_tokens: 8192
  temperature: 0.2

tool_call_mode: structured         # §2 必须显式写

tools:                             # §4 三个列表键都要在（空也要写）
  - name: read_file
    yaml_path: ./tools/read_file.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:read_file   # §6.1 binding 必填
skills:
  - ./skills/my-domain             # §7.1 必须字符串路径
middlewares: []

stop_tools: []                     # 挂了 ask_user 就要写 [ask_user]（§10）

# 🚫 不写 sandbox_config、不写 tracers（§3）
```

配套 `systemprompt.md` 里必须出现：

```markdown
skills 根目录位于 `/home/user/.skills/`；加载 skill 后以 LoadSkill 返回的 SkillFolder 为准。
```

---

## 12. 自查

```
- [ ] 顶层有 nexau.json / agent.yaml / systemprompt.md 三个文件
- [ ] agent.yaml 写了 type: agent、system_prompt_type: jinja、tool_call_mode: structured
- [ ] agent.yaml 没有 sandbox_config、没有 tracers、没有字面量 api_key
- [ ] llm_config.model 是 provider/model_name 全键或 ${env.LLM_MODEL}，不是裸名
      （裸名：校验器 error `agent.llm_config.model.bare_name` + 运行期每次 chat 422）
- [ ] tools / skills / middlewares 三个键都存在（空也写）
- [ ] 每个 tools 条目都有 name + yaml_path + binding
- [ ] 每个 .tool.yaml 有 type/name/description/input_schema，且没有白名单外的键（含 `formatter`，§6.3）
- [ ] skills 条目都是字符串路径
- [ ] 每个 skill 入口 SKILL.md（技能根目录下那一个）frontmatter 有 name + description
- [ ] references/ 非空 → 有 references/INDEX.md；每个非空子目录也有 INDEX.md
      （⚠️ 校验器规则文件把 index_file 配成 SKILL.md，会因此误报——见 §8.2）
- [ ] 索引里引用的路径都真实存在、且都在本 skill 的 references/ 内；提到别处的文件不加反引号（§8.3）
- [ ] 没有 skill 的索引链到别的 skill 的 references/（公共资料抽成已注册的共享 skill + LoadSkill 引导，§1.2）
- [ ] 制品内没有软链接、没有 ../ 或绝对路径的声明路径；**且** systemprompt / SKILL.md / 索引 /
      custom_tools 代码 / middleware params 里没有开发机、workspace、模板库、/tmp/run-* 路径
      （④ 类文案指令静态零告警，只能人工过一遍，§1.1）
- [ ] 每个 middlewares 条目都有 import + params（没参数写 {}）
- [ ] 挂了 ask_user 就写了 stop_tools: [ask_user]
- [ ] systemprompt.md 里出现了「skills 根目录位于 /home/user/.skills/」
```
