# 模板：层级化知识库问答（01-agentic-rag）

> 无向量库的 Agentic RAG：知识存成层级化 Markdown 树，Agent 用 `read_file` 逐层「翻目录」定位原文。
> 难度 🟢 Level 1（最基础的模板，其余模板多是在它之上扩规模 / 换产出形态）。
> 来源：nexau-cookbook《劳动法问答 · 劳动法层级化 QA》（tutorial-agentic-rag-agent.md）。

## 这个模板教你什么

1. **不用向量库做 RAG**：每个目录放一个 `INDEX.md` 当索引，Agent 读索引 → 缩小范围 → 读叶子文件，3 跳定位到几十上百个文件中的某一条。
2. **三层职责分离**：`systemprompt.md` 管流程与导航规则、`skills/*/SKILL.md` 管知识框架、`references/**` 管知识原文。知识更新只换 `references/` 下的文件，Agent 配置一行不动。
3. **Agentic RAG 的标配三件套工具**：`read_file` + `search_file_content` + `run_shell_command`，三个 binding 全走平台内置，`.tool.yaml` 抄现成的不手写（本模板沿用 cookbook 版本；`search_file_content` / `run_shell_command` 与 `../_builtin-tool-yamls/` 逐字一致，`read_file` 是删掉了图片/音视频/PDF 参数的精简版——要完整能力就换成 `../_builtin-tool-yamls/read_file.tool.yaml`）。
4. **`ContextCompactionMiddleware` 是本模板的必需件不是可选件**：多跳 `read_file` 会持续堆积工具输出，不压缩迟早撑爆上下文。
5. **针对 LLM 具体坏习惯做 prompt 防御**：跳步猜文件名、不加载 skill 就读路径、在大目录根上全局 grep、凭记忆不查资料——四类都在 systemprompt 里有对应的硬禁令。
6. **输出格式当质量闸门**：强制「结论 → 依据（精确到条款号）→ 注意事项」，把「散文式看起来很完整但无法验证」的回答挡在外面。

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 替代 |
|---|---|---|
| 静态文档 / 法规 / 手册 / 制度库问答，几十~几千个文件 | ✅ 首选 | — |
| 知识随制品一起发布、离线可用、不想引外部依赖 | ✅ | — |
| 知识每天变、必须查实时数据 | ❌ | `02-rest-api-tool`（调后端 API） |
| 答案要从结构化表里算出来（销售额、库存） | ❌ | `03-text-to-sql` |
| 知识量极大（万级）且要语义近似召回、已有向量库 | ❌ | `06-external-vector-kb` |
| 只需要一个能力已被外部 MCP 服务覆盖 | ❌ | `04-mcp-server` |
| 产出是文档 / 报告而不是问答 | ❌ | `07-doc-generation` |
| 需要输出前做内容合规过滤 | ➕ 叠加 | `09-content-guardrail` 的中间件 |
| 只想要一个空骨架自己填 | ❌ | `10-reference-skeleton` |

## 目录结构

```
01-agentic-rag/
├── nexau.json                     # 制品清单：agents 映射（唯一被平台消费的关键字段）
├── agent.yaml                     # 骨架：模型、三件套工具、skills、中间件
├── systemprompt.md                # 指挥官：工作流程 + 导航规则 + 禁止跳步 + 结构概览表 + 工具使用规则表 + 🚫 禁止操作
├── tools/                         # 三个内置工具的 .tool.yaml（从平台内置库复制，勿手写）
│   ├── read_file.tool.yaml
│   ├── search_file_content.tool.yaml
│   └── run_shell_command.tool.yaml
└── skills/
    └── labor-lawyer-cn/           # ⚠️ 目录 basename 决定运行时路径
        ├── SKILL.md               # skill 入口：frontmatter(name/description) + 触发条件 + 导航指引
        ├── scripts/
        │   └── calculate_compensation.py   # 领域计算脚本，靠 run_shell_command 在沙箱里跑
        └── references/            # 知识原文，共 47 个文件 = 14 个各层索引 INDEX.md + 33 篇叶子，3 层树
            ├── INDEX.md           #   根索引：5 大主题
            ├── 法律条文/{INDEX.md, 合同与用工/, 保障与保险/, 争议解决/}
            ├── 赔偿计算/{INDEX.md, 经济补偿金计算.md, …}
            ├── 纠纷处理/{INDEX.md, 合同纠纷/, 待遇纠纷/, 特殊情形/}
            ├── 证据与维权/{INDEX.md, 证据收集/, 维权程序/}
            └── 地方差异/{INDEX.md, 法律适用差异.md, …}
```

## 复制后必须改的地方

按顺序做，每步都精确到 `文件:字段`。

1. **`nexau.json` → `agents` 的 key**：`labor_law_qa` → 你的 agent 名（**下划线**命名，不能有横杠/空格）。value 保持 `agent.yaml`。
2. **`agent.yaml:name`**：改成与第 1 步 **完全一致** 的字符串。两处不一致 = 平台按 `nexau.json` 的 key 找不到 agent。
3. **`agent.yaml:description`**：写清这个 agent 干什么，会出现在平台列表里。
4. **`agent.yaml:llm_config.temperature`**：知识问答保持 `0.1–0.3`。要「创造性」输出才调高——本模板要求精确引用原文，调高就是自找幻觉。
5. **`agent.yaml:llm_config.model`**：保留 `${env.LLM_MODEL}`（跟随项目默认模型）。⚠️ 项目里一张可见模型卡都没有时该 env 不会被注入，agent 加载直接 `ConfigError`——先在平台配好模型卡。
6. **`agent.yaml:skills[0]`**：`./skills/labor-lawyer-cn` → `./skills/<你的知识库目录名>`。
7. **重命名 `skills/labor-lawyer-cn/` 目录**：⚠️ **目录 basename 决定运行时路径**（部署后是 `/home/user/.skills/<basename>`）。同时改 `skills/<你的目录>/SKILL.md` frontmatter 的 `name`（它决定 Agent 用什么名字调 `LoadSkill`，与 basename 可以不一致，但不一致会给自己找麻烦，建议对齐）。
8. **`skills/<你的目录>/SKILL.md`**：改 frontmatter 的 `description`（这是 skill 的触发条件，写「用户问到 X/Y/Z 时立即使用」，越具体越容易被触发）、「适用场景」「处理流程」「引用规范」四段。
9. **替换整个 `references/` 树**：换成你的知识文件，并**为每一层目录都写 `INDEX.md`**（构建方法见下节「关键设计要点 · 如何建层级」）。
10. **`systemprompt.md` 的「知识库结构概览」表**：逐行改成你的顶层主题目录 + 一句话内容描述。**这张表不能省**——没有它 Agent 每次都要先读根 `INDEX.md`，白白多一跳。
11. **`systemprompt.md` 的导航示例**：把「第1/2/3 跳」里的 `赔偿计算/经济补偿金计算.md` 换成你知识库里**真实存在**的一条路径。写不存在的路径 = 教 Agent 猜文件名。
12. **`systemprompt.md` 里 `/home/user/.skills/labor-lawyer-cn`**：改成你的目录名。⚠️「skills 根目录位于 `/home/user/.skills/`」这句话**必须原样保留**（平台静态校验器有正则硬检查，见「已知的坑」）。
13. **`systemprompt.md` 的角色定义 + 回复准则 + 输出结构**：改成你的领域。保留「结论 → 依据 → 注意事项」这个骨架和「引用必须具体到出处」这条。
14. **`systemprompt.md` 的「工具使用规则」表 + 「🚫 禁止操作」**：只改路径与脚本名，**别删**。其中「禁止对 `references/` 根目录 `search_file_content`」这条按 §5 要求在 `systemprompt.md` 与 `skills/<你的目录>/SKILL.md` **两处都要有**，改一处漏一处等于没写。
15. **`skills/<你的目录>/scripts/`**：不需要领域计算就整个删掉——同时删掉 `systemprompt.md` 工具表里 `run_shell_command` 那一行和 `SKILL.md` 的「计算脚本」小节，否则 Agent 会去调用不存在的脚本（工具本身可以留着，也可以把 `agent.yaml:tools` 里的 `run_shell_command` 一并删掉）；需要就换成你的脚本（沙箱里跑，依赖见「已知的坑」第 6 条），并同步改这两处里的脚本名与调用方式。
16. **删掉本 `TEMPLATE.md`**：它是模板元数据，不属于制品。
17. **`agent.yaml:max_iterations`**：默认 50。知识树 ≥ 4 层或一次问答要读 10+ 文件时上调。
18. **打包前自检**：压缩包 ≤ 100 MiB；归档里**不能有符号链接**（含软链必 400）；根目录必须有 `nexau.json`。

## 关键设计要点

### 为什么是「查资料」而不是「背资料」

| | 塞进 Prompt 让 Agent 背 | 存文件让 Agent 查（本模板） |
|---|---|---|
| 回答依据 | 记忆中的大意 | 原文 |
| 数字 / 条款号 / 公式 | 极易出错 | 精确 |
| 知识规模上限 | 受 context 限制 | 无上限（只加载需要的部分） |
| 知识更新 | 要重测整个 Agent | 换 `references/` 下的文件即可 |
| 代价 | — | 多几次 `read_file`（可接受） |

### 为什么是层级而不是扁平

| | 扁平知识库 | 层级化知识库 |
|---|---|---|
| Agent 行为 | 一次加载全量索引（可能数千条） | 每跳只读当前层索引（几十条） |
| Token | 索引本身就占大量上下文 | 按需加载 |
| 精度 | 关键词匹配，易命中无关内容 | 逐层缩小，精准定位 |
| 扩展 | 新文件只能扔进扁平列表 | 归入对应层级 |

原案例实测：改造前 6 个大文件（7 部法律挤在 `core_laws.md` 里），改造后 47 个文件 / 3 层，定位《劳动合同法》第 47 条从「搜全部」变成「3 跳直达」。

### 如何把扁平文件建成层级（BFS 三步法）

1. **初始化**：所有知识文件丢进 `references/`，生成一份列全部文件的 `INDEX.md`。
2. **BFS 逐层优化**，对每个文件三选一，并同步更新受影响的所有 `INDEX.md`：

   | 情况 | 决策 |
   |---|---|
   | 一个文件含多个独立主题 | **拆分**成独立文件 |
   | 当前目录 > 20 个文件 | **下沉**，按主题建子目录 |
   | 文件明确属于某已有分类 | **下沉**到该子目录 |
   | 目录 ≤ 20 个文件且主题一致 | 停止下沉 |
   | 已达 3–5 层深度上限 | 停止下沉 |

3. **一致性检查**：每个目录都有 `INDEX.md` / 每个 `INDEX.md` 准确覆盖本目录全部文件与子目录 / 无残留引用（提到已删文件）/ 无孤立文件（磁盘上有但索引没记）。

> 知识文件多、需要自动化建树时，直接用 skill `skill-knowledge-organizer`，别手搓。

### 每层 INDEX.md 的固定写法

```markdown
# 主题名称

一段话描述本目录覆盖的知识范围。

## 子目录
- `劳动争议/` — 劳动仲裁、诉讼程序、举证规则（35 件）   ← 写清范围 + 数量，Agent 不进去就能判断相关性

## 本级文件
- `劳动合同法.md` — 涵盖合同订立、履行、解除、终止      ← 写内容摘要，别只重复文件名

## 交叉引用
- 工伤认定标准 → 见 `../工伤保险/工伤认定标准.md`      ← 文件只放最相关的一处，其余目录用引用指过去
```

文件名必须可读：`劳动合同法.md` ✅ / `ff8081818c91.md` ❌——Agent 是靠文件名 + 描述做路由决策的。

### 四条防御式 prompt（都是实际部署踩出来的）

| Agent 的坏习惯 | 防御写法（systemprompt 与 SKILL.md **两处都要写**） |
|---|---|
| 看到子目录名就猜文件名（猜 `违法解除劳动合同纠纷处理.md`，实际叫 `违法解除劳动合同.md`） | 「看到子目录名后必须先读该子目录的 INDEX.md，禁止凭猜测构造文件名；报错文件不存在就回上一级核对」 |
| 不加载 skill 就读路径（猜 `/agent/skills/…`） | 工作流程**第一步**写死「加载技能获取路径」，并声明 skills 根目录 `/home/user/.skills/` |
| 在 `references/` 根上全局 `search_file_content`（文件多会超时） | 「禁止对 references/ 根目录搜索，搜索必须指定到分类子目录」 |
| 跳过检索凭记忆回答 | 「禁止凭记忆回答，必须先查阅知识库、基于原文回答」 |

## 已知的坑

1. ⚠️ **`systemprompt.md` 必须原样含有「skills 根目录位于 `/home/user/.skills/`」**。平台静态校验器 `builder-static-rules.json` 有正则 `(?i)skills\s*根目录位于\s*` + `/home/user/.skills/` 硬检查，缺了就报 `systemprompt.md must explicitly state that the skills root directory is /home/user/.skills/`。同时静态校验还要求 `type: agent` / `system_prompt_type: jinja` / `tool_call_mode: structured` 三项、`tools`+`skills`+`middlewares` 三个列表字段都存在、且**禁止**出现 `sandbox_config` / `tracers`。
2. ⚠️ **运行时路径由目录 basename 决定，不是 frontmatter 的 `name`**。部署后 = `/home/user/.skills/<skills 下的目录名>`。权威取值方式仍是 `LoadSkill` 返回的 `Skill Folder`，systemprompt 里写死的路径只是给 Agent 兜底和过静态校验。
3. ⚠️ **`ContextCompactionMiddleware` 两个必坑**：import 路径中间有 `execution` 一层（`nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware`，少一层直接启动失败）；参数名是 `threshold` 不是 `threshold_ratio`——该中间件的配置模型是 `extra="forbid"`，传错参数名直接 pydantic 报错。
4. ⚠️ **`${env.X}` 是加载期对 agent.yaml 全文做正则替换**（在 `yaml.safe_load` 之前），所以**连 YAML 注释里的 `${env.X}` 也会被解析**；变量没设置 = 加载期 `ConfigError` 硬失败；不支持默认值语法、不支持转义。写注释时不要顺手举 `${env.某某}` 的例子。
5. ⚠️ **`${env.LLM_MODEL}` 的前提是项目里至少有一张可见模型卡**，否则该 env 不注入，agent 加载失败。
6. ⚠️ **`scripts/` 下的脚本跑在沙箱里，不是 agent-runtime 进程里**：沙箱预装了 venv `/opt/sandbox-python`（PATH 已前置），含 requests / httpx / pandas / numpy / matplotlib / PyMuPDF / pdfplumber / openpyxl / python-docx 等，直接 `python xxx.py` 即可；要额外依赖走 `nexau.json` 的 `setup`（离线 whl）。密钥同理分两条通路——沙箱脚本只能读 **sandbox scope** 环境变量，读不到 runtime scope。详见 `../../references/env-vars-and-secrets.md`。
7. ⚠️ **cookbook 原版里 `scripts/calculate_compensation.py` 没有任何索引指向它**（`references/赔偿计算/INDEX.md` 只在 `综合计算示例.md` 的描述里含糊提了「Python 计算工具代码」），Agent 大概率永远不会调用它。**本模板已修**：systemprompt 的「工具使用规则」表和 `SKILL.md` 的「计算脚本」小节都显式写出了调用方式。你换成自己的脚本时，这两处要一起改。
   附带一个真坑：该脚本**只认 `--help`，不带参数直接跑会进入 `while True: input()` 交互模式**，在 `run_shell_command` 下会挂住等 stdin 直到超时。模板里给的调用方式是 `python3 -c "... from calculate_compensation import calculate_n ..."` 直接调函数——你自己写脚本时最好做成纯 CLI 参数式，别留交互模式。
8. ⚠️ **三个 `.tool.yaml` 里的 `additionalProperties: false` 在这里是安全的**，因为这三个工具在 `agent.yaml` 里都**没有** `extra_kwargs`。一旦你给某个工具加了 `extra_kwargs`（比如注入 `db_path`），就**必须删掉那个工具 schema 里的 `additionalProperties: false`**——框架会把 extra_kwargs 合进参数再做 jsonschema 校验，且不会剔除它，必报 `Additional properties are not allowed ('db_path' was unexpected)`。详见 `../../references/custom-tools.md`。
9. ⚠️ **`nexau.json` 的 `excluded` 字段平台完全不解析**，只是打包端约定，别指望它排除文件。真正被消费的是 `agents` / `setup` / `backend` / `runtime.command`。
10. ⚠️ **打包硬约束**：≤ 100 MiB（超限 413）；归档只允许普通文件和目录，**含符号链接必 400**；根目录必须有 `nexau.json`。知识库文件多时留意体积。

## 本模板相对 cookbook 原版的改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `agent.yaml` | 删除 `llm_config.api_type` / `base_url` / `api_key` / `stream` 四个字段，只保留 `model` + `max_tokens` + `temperature` | NAC 上 `base_url`/`api_key` 被平台无条件覆盖，`api_type` 被模型卡派生值覆盖，`stream` 在流式路径被强制 `True`——四个字段写了不生效，纯噪声，还会误导复制者以为要自己填密钥 |
| `agent.yaml` | 上述位置补一段注释：NAC 会覆盖这四项；**本地裸跑 NexAU 时需自行提供 `base_url`/`api_key`**（写进 yaml 或设 `LLM_BASE_URL`/`LLM_API_KEY`） | 收敛成 NAC 最小写法后不能让本地裸跑的人无路可走；`LLMConfig.__init__` 确实会从这两个环境变量兜底 |
| `agent.yaml` | 删除文件头部重复的 `max_iterations: 300`（保留下方的 `max_iterations: 50`） | YAML 重复 key 被 `yaml.safe_load` 静默取最后一个，`300` 从来没生效过。留着会让复制者改了上面那处却毫无效果 |
| `systemprompt.md` | 「知识库导航方法」下新增一段：`部署后 skills 根目录位于 /home/user/.skills/，本知识库即 /home/user/.skills/labor-lawyer-cn；以 LoadSkill 返回的 Skill Folder 为准` | 平台静态校验器 `required_systemprompt_patterns` 有正则硬检查，原版缺这句会直接判不通过；同时补上原版缺失的「路径权威来源」说明 |
| `systemprompt.md` | 新增「工具使用规则」表 + 「🚫 禁止操作」清单；「禁止跳步」块补一条「禁止对 `references/` 根目录 `search_file_content`」 | 原版挂了三个工具却对搜索/工具边界零规则：`search_file_content` / `run_shell_command` 全文一次都没出现，Agent 会在 47 文件的根目录上全局 grep（超时），也永远不知道 `scripts/` 下有计算脚本。同一套规则按 §5 要求同步写进了 `skills/labor-lawyer-cn/SKILL.md` |
| `skills/labor-lawyer-cn/SKILL.md` | 同上：补「禁止对 `references/` 根目录搜索」+ 三行工具使用规则表 + 「计算脚本」小节（含"裸跑会进交互模式挂住"的警告） | §5「四个必须防的坏习惯」要求 systemprompt 与 skill 入口两处都写；`scripts/calculate_compensation.py` 原本没有任何索引指向它 |
| `nexau.json` / `tools/*.tool.yaml` / `skills/**` 的其余部分 | **内容逐字未改**；仅 `references/` 下 14 个各层索引**改名** `SKILL.md` → `INDEX.md`（见下 §索引文件命名），33 篇叶子与 `nexau.json` / `tools/*.tool.yaml` 一字未动 | 无过时项：三个 binding 在框架里都存在，`tool_call_mode` 原本就是合法的 `structured`，`additionalProperties: false` 在无 `extra_kwargs` 的场景下安全；改名只动文件名、不动任何一个字节的内容 |

> 复核记录（交叉复核轮）：上一轮曾把 `references/` 裁到「14 个索引 + 3 篇叶子」并附 `_FULL-TREE.txt`。
> 实测该裁剪会让保留下来的 14 个索引指向 41 条不存在的路径 —— A4A 静态校验器
> （`skill_reference_rules.require_referenced_paths_exist`）报 41 条 `skills.references.path_missing`，
> 运行时 Agent 也会按索引去 `read_file` 一堆不存在的文件。**已整树还原为 cookbook 原样**
> （代价仅 +130 KB），`_FULL-TREE.txt` 随之删除。**裁知识库时务必连索引一起裁，别只删叶子。**

### ✅ 索引文件命名：整个 skill 只有一个 `SKILL.md`，内层一律 `INDEX.md`

本模板的形状（**已相对 cookbook 原版改名**，原版内层用的是嵌套 `SKILL.md`）：

```
skills/labor-lawyer-cn/
├── SKILL.md          ← 唯一的 SKILL.md：skill 入口
└── references/
    ├── INDEX.md      ← 根索引
    ├── 法律条文/
    │   ├── INDEX.md  ← 子目录索引
    │   ├── 合同与用工/INDEX.md
    │   └── …
    └── …
```

- **理由是语义**：`SKILL.md` 是 skill 入口（框架 `Skill.from_folder` 只在 skill 根目录找它）；
  `references/` 下面是**知识库层级、不是 skill**，不该占用 skill 专用文件名。
- 框架层不管内层索引叫什么（只要求 skill 根目录有带 `name`/`description` frontmatter 的 `SKILL.md`）。
- `skill-knowledge-organizer` 产出的正是 `INDEX.md`，**不用改名**，直接可用。
- ⚠️ **平台静态校验器当前会报 14 条 error**（1 条 `index_missing` + 13 条 `directory_index_missing`），
  因为它的规则文件把 `index_file` 配成了 `SKILL.md`。
  **这是平台配置缺陷**，修法是把 `builder-static-rules.json:56` 改成 `"INDEX.md"`（实测改完 0 error 通过）。
  ⚠️ 但 `builder-static-rules.json` 是 NAC 仓里受控的**平台**规则文件，需由平台维护者走 PR 修改；
  **制品作者 / 生成 agent 不要为了让自己的制品过检而就地编辑它**——那会静默改变所有使用者的校验口径。
  在平台修掉之前，把这 14 条 error 当已知噪声即可。
  详见 `../../references/artifact-spec-checklist.md` §8。

## 延伸

- 通用契约与字段：`../../references/agent-yaml-fields.md`、`../../references/llm-config.md`
- 内置工具三件套的完整参数：`../../references/builtin-tools.md`；可直接复制的 yaml：`../_builtin-tool-yamls/`
- 中间件（含 `ContextCompactionMiddleware` 全部参数、`LongToolOutputMiddleware`）：`../../references/middlewares.md`
- 打包 / `nexau.json` / `setup` 离线依赖：`../../references/nexau-json-and-packaging.md`
- 密钥与环境变量两条通路：`../../references/env-vars-and-secrets.md`
- 报错速查：`../../references/troubleshooting.md`
- 自动化建层级知识树：skill `skill-knowledge-organizer`
- 相关模板：`06-external-vector-kb`（知识量超大改走向量库）、`10-reference-skeleton`（空骨架）、`09-content-guardrail`（输出合规护栏，可叠加）
