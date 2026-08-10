# 模板：内容安全护栏（content-guardrail）

> 给任意已有 Agent 套一层确定性的敏感词闸门：输入 / 输出 / 工具结果三路拦截。难度 **入门**（改 `agent.yaml` 一段 + 换词库即可）。来源：nexau-cookbook 「敏感词过滤 / sensitive_word_agent」。

---

## 这个模板教你什么

1. **`middlewares:` 是横切能力的挂载点** —— 内容安全不写进 system prompt，而是挂 `SensitiveWordMiddleware`，与业务逻辑（prompt / tools / skills）完全解耦，拷进任何制品都能用。
2. **一个中间件同时管三条链路**：`before_model` 拦用户输入 **和** 工具结果（`Role.TOOL`），`after_model` 拦模型输出——不需要三份配置。
3. **命中动作必须显式声明**：`input_action` / `output_action` 默认是 `mask`（脱敏后继续），只有显式写 `terminate` 才是「终止 run + 返回拒绝文案」。这是本模板最容易被静默改变语义的一处。
4. **词库 = 目录，文件名 = 类别**：`lexicon/*.txt` 随制品分发，安全团队独立维护；类别名会出现在拒绝文案与审计事件里。
5. **「读随制品打包的材料」必须用自定义工具，不能用内置 `read_file`**：内置文件工具走沙箱（cwd `/home/user`），沙箱里没有制品目录 `/agent`。本模板的 `custom_tools/read_material.py` 就是这条边界的最小示范。

---

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 说明 / 替代 |
|---|---|---|
| 政务、金融、对公上线前的内容安全评审要求 | ✅ 直接用 | 把 `middlewares:` 段 + `lexicon/` 拷进你的制品即可 |
| 要「模型不许说 XX」且要可审计、可追责 | ✅ 用 | prompt 约束是概率性的，中间件是确定性的；两者并存不冲突 |
| 要拦的是**语义**违规（阴阳怪气、诱导、越狱），不是固定词 | ❌ 不用 | 敏感词是精确子串匹配，管不了语义；需要审核模型 / 分类器 |
| 只想让模型「尽量别提某话题」，误伤不可接受 | ⚠️ 谨慎 | 改用 `input_action: mask` / `soft_reject`，或缩小 `scan_roles` |
| 需要白名单（词库说拦、白名单说放） | ❌ 不支持 | 中间件刻意不做 allowlist；误杀就从词库里删词，保持词库是唯一事实源 |
| 只是想做一个普通的政务问答 Agent | ❌ 别用本模板 | 本模板的 Agent 本体只是载体，去看 `01-agentic-rag` / `10-reference-skeleton` |

---

## 目录结构

```text
09-content-guardrail/
├── nexau.json                      # 项目清单：agents 映射到根目录的 agent.yaml
├── agent.yaml                      # 核心：middlewares 段声明敏感词中间件 + tools 注册
├── systemprompt.md                 # 普通政务咨询助手 prompt（与安全护栏完全解耦）
├── custom_tools/
│   └── read_material.py            # 读制品内 materials/ 的自定义工具（跑在 runtime 进程）
├── tools/
│   └── read_material.tool.yaml     # 上面那个工具给模型看的 schema
├── lexicon/                        # 词库目录：每个 .txt 文件名 = 类别，一行一个词
│   ├── 涉枪涉爆词库.txt             # 完整类别词库（434 词，来自 konsheng/Sensitive-lexicon）
│   ├── 民生词库.txt                 # 演示词：打人
│   ├── 贪腐词库.txt                 # 演示词：腐败
│   ├── 本单位自定义词库.txt          # 演示词：内部测试代号
│   └── README.md                   # 词库来源与裁剪说明（.md 不会被加载，不影响词数）
├── materials/
│   └── 网民留言-20260601.txt        # 含「腐败」的虚构材料，用于触发工具结果拦截
└── TEMPLATE.md                     # 本文件，打包前删掉
```

实测：这份 `lexicon/` 加载后 `lexicon_size = 437`（434 + 3 个演示词）。

---

## 复制后必须改的地方

1. **`lexicon/` 换成你的词库** —— 这是最重要的一步。演示词（打人 / 腐败 / 内部测试代号）在生产里要么删掉、要么换成真实词表。文件名即类别名，按业务含义拆文件，别塞一个大文件。
2. **`agent.yaml: middlewares[0].params.lexicon_dir`** → 必须是**绝对路径**，NAC 上就是 `/agent/<你的词库目录名>`。改了目录名一定要同步改这里。
3. **`agent.yaml: middlewares[0].params.input_action / output_action`** → 想要「命中即终止 + 拒绝文案」就保持 `terminate`；想要「脱敏后继续对话」改 `mask`；想要「温和拒绝但 run 算成功」改 `soft_reject`。**别删掉这两行**，删了会退回默认的 `mask`。
4. **`agent.yaml: llm_config.model`** → 保持 `${env.LLM_MODEL}` 跟随项目默认模型；本地裸跑 NexAU（不经 NAC）时需自行补 `base_url` / `api_key`。⚠️ 项目**一张可见模型卡都没有**时该 env 不会被注入，agent 加载期直接 `ConfigError: Environment variable 'LLM_MODEL' is not set`（`${env.X}` 不支持默认值语法）。要钉死模型就写平台模型卡全键 `provider/model_name`。
5. **`agent.yaml: name` / `description` / `nexau.json: agents` 的 key** → 换成你的 agent 名（三处要一致）。
6. **`systemprompt.md`** → 换成你自己的业务 prompt。安全护栏不依赖 prompt，唯一相关的是最后那句「输入输出会经过内容安全检查」（可留可删）。
7. **`materials/` + `custom_tools/read_material.py` + `tools/read_material.tool.yaml`** → 这三件套只为演示「工具结果拦截」。把护栏装到已有 Agent 上时，**整套删掉**，只保留 `middlewares:` 段和 `lexicon/`。
8. **删掉 `TEMPLATE.md` 和 `lexicon/README.md`** 再打包（`.md` 不会被中间件加载，但没必要进制品）。

把护栏装到**别的**模板上时，只需要两步：拷 `lexicon/` 目录 + 抄 `agent.yaml` 的 `middlewares:` 段。

---

## 关键设计要点

### 1. 为什么是 middleware 而不是 prompt

| | prompt 里写「不要谈 XX」 | `SensitiveWordMiddleware` |
|---|---|---|
| 确定性 | 概率性遵循，换个问法就绕过 | 精确子串匹配（Aho-Corasick），命中就是命中 |
| 可审计 | 无结构化记录 | `ContentBlockedEvent`（`source` / `categories` / `words` / `message`）+ 日志 |
| 输入侧 | 管不到，违规输入照样进模型照样计费 | `before_model` 短路，请求根本不发给 LLM |

两者不互斥：prompt 负责「引导模型得体」，中间件负责「兜底一定拦住」。

### 2. 三路拦截的时机

| 来源 | 钩子 | 时机 | 效果 |
|---|---|---|---|
| 用户 / 系统 / 框架输入 | `before_model` | 调模型**前**短路 | 违规请求不发给 LLM |
| 工具结果（`Role.TOOL`） | `before_model` | 工具执行完的**下一轮**模型调用前 | 工具读到的敏感内容不进模型上下文 |
| 模型输出 | `after_model` | 整段响应聚合后、执行工具前 | 违规输出不作为最终回复 |

- 工具结果是在「下一轮」被拦的：工具**已经执行完**（材料确实被读了），事件序列是 `TOOL_CALL_RESULT → ContentBlockedEvent(source=input) → RUN_ERROR`。
- 流式输出下，输出侧是「整段流完才拦」，违规 chunk 可能已经流到前端；前端需在收到 `RUN_ERROR` / `ContentBlockedEvent` 时清掉已渲染内容。输入侧不受影响。

### 3. 三种命中动作（`OnHitAction`）

| action | 行为 | `force_stop_reason` | 何时选 |
|---|---|---|---|
| `terminate` | 拒绝文案替换/追加 assistant 消息，run 当错误终止 | `ERROR_OCCURRED` | 严苛合规（政务 / 审计），本模板默认 |
| `mask`（框架默认） | 命中位置替换成 `mask_template`（默认 `***`），run 正常继续 | — | 普通对话，不想被一个词打断整轮 |
| `soft_reject` | 温和拒绝文案，run 算**正常完成**；并把历史里的命中词 mask 掉 | `SUCCESS` | 不想报错、也不想让 LLM 看到原文；且不希望后续轮被同一个词反复拦 |

文案模板：`refusal_template`（terminate）/ `soft_refusal_template`（soft_reject / mask 的事件文案），占位符 `{source}` / `{category}` / `{hits}`（`{source}` 渲染为「用户输入」或「模型输出」；工具结果归入输入侧，也显示「用户输入」）。

### 4. 词库的四种来源（可叠加）

```yaml
params:
  lexicon_dir: /agent/lexicon             # 目录：每个 .txt 文件名 = 类别（推荐）
  lexicon_file: /agent/words.txt          # 单文件：文件名 = 类别
  lexicon_words: ["打人", "腐败"]          # 显式词表：统一归入 "explicit" 类
  extra_words: ["内部代号A", "项目X"]      # 在已有词库上追加：归入 "extra" 类
```

`lexicon_dir` / `lexicon_file` / `lexicon_words` **必须至少配一个**，否则构造时 `ValueError`（框架已不再内置默认演示词库）。

### 5. 生产词库从哪来

推荐 [konsheng/Sensitive-lexicon](https://github.com/konsheng/Sensitive-lexicon)（MIT，`Vocabulary/` 目录格式与 `lexicon_dir` 天然兼容，17 个分类文件）。三条纪律：

- **逐词人工审核后再用**：开源词库追求覆盖面，部分类别名实不符（「民生」「贪腐」完整版混有大量涉政词条与真实人名）。本模板只完整收录相对中性的「涉枪涉爆」一类，就是这个原因。
- **按业务评估误伤面**：启用「贪腐」类会把市民正常的举报留言一并拦下——本模板的演示材料（设计如此）就是这种情况。
- **词库本身是敏感资产**：高敏感类别的完整词表不要提交进代码仓库，走安全团队发布渠道，部署时注入。

误杀了正常词：**直接从词库里删掉**。中间件刻意不提供 allowlist，避免「词库说拦、白名单说放」的二义性。

---

## 已知的坑

| ⚠️ 坑 | 现象 | 修法 |
|---|---|---|
| **不写 `input_action` / `output_action`** | 护栏「装了但不拦」——命中只是把词换成 `***`，Agent 照常回答，验收用例全不符合预期 | 显式写 `input_action: terminate` / `output_action: terminate`（本模板已写死） |
| **`lexicon_dir` 写相对路径** | 按进程 CWD（`/home/user`）解析 → 目录不存在 → 构造时抛 `FileNotFoundError: lexicon_dir is not a directory` → **agent 加载失败**（当前版本已改为硬失败，早期版本是静默加载 0 词） | 一律写绝对路径 `/agent/lexicon` |
| **目录在但词一个没加载** | 目录存在却没有 `*.txt`（改了扩展名 / 全放进子目录 / 只有 `.md`）→ 不报错，`lexicon_size = 0`，护栏完全失效 | 部署后核对启动日志 `[SensitiveWordMiddleware] loaded N words`，N 必须与词库规模一致；`glob("*.txt")` **不递归子目录** |
| **命中的那条消息留在会话历史** | 同一会话后续每一轮都会被同一个词反复拦截（`terminate` 下尤其明显），用户「怎么问都被拦」 | 验收时**每个用例开新会话**；业务上引导用户开新会话或前端做会话重置；或改用 `soft_reject`（它会 mask 历史命中词） |
| **默认 `scan_roles` 覆盖 SYSTEM 和 TOOL** | 你的 system prompt / 知识库原文里本身含词库词（政策场景的「打人」、信访场景的「腐败」很常见）→ 装上即被**持续**拦截，每轮都拦 | 要么从词库删词，要么显式传 `scan_roles` 缩小范围（默认 `{USER, FRAMEWORK, SYSTEM, TOOL}`） |
| **用内置 `read_file` 读制品内的材料** | 内置文件工具走沙箱（cwd `/home/user`），沙箱里**没有** `/agent`，工具直接返回「文件不存在」，工具结果拦截这条链路根本触发不了 | 用 `custom_tools/read_material.py` 这种跑在 runtime 进程内、用 `Path(__file__)` 定位的自定义工具 |
| **词库改了不重启** | Aho-Corasick 自动机构建后不可追加，词库只在中间件初始化时加载一次 | 改词 = 重新打包上传部署（或至少重启 runtime），不支持热更新 |
| **`${env.LLM_MODEL}` 未注入** | agent 加载期 `ConfigError: Environment variable 'LLM_MODEL' is not set`，看起来像 yaml 写错 | `${env.X}` 在 `yaml.safe_load` **之前**对整份文本做正则替换，未设置就硬失败、不支持默认值。项目至少要挂一张可见模型卡 |
| **给工具加了 `extra_kwargs` 却留着 `additionalProperties: false`** | 每次调用报 `Additional properties are not allowed ('xxx' was unexpected)` | 该工具的 `input_schema` 删掉 `additionalProperties: false`（别把密钥 key 写进 `properties`） |
| **平台制品静态校验会报 1 条 `middleware.not_allowed`（规范滞后，不要按它改）** | 跑官方静态校验器时，`agent.yaml.middlewares[0].import` 报「Middleware must be copied from the allowed template middleware list」 | **保持原样，不要删这个中间件**。`allowed-middlewares.json` 当前只放行 `ContextCompaction` 和 `LongToolOutput` 两个，`SensitiveWordMiddleware` 尚未进白名单——而它正是本模板存在的全部意义。这是白名单滞后于框架能力，不是模板写错。上线前若被硬门禁拦下，走白名单收录流程，别为了消这条 error 把护栏摘掉 |

---

## 本模板相对 cookbook 原版的改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `agent.yaml` | `middlewares.params` 新增 `input_action: terminate` / `output_action: terminate` | **该中间件当前的默认值是 `mask`，不是 `terminate`**。不写就退化成脱敏继续，教程描述的三条验收用例全部不符 |
| `agent.yaml` | `llm_config` 删掉 `base_url` / `api_key` / `api_type` / `stream`，只留 `model` + `temperature`，并加注释说明本地裸跑需自补 | 这四个字段在 NAC 上被平台无条件覆盖（`base_url` / `api_key` 换成平台注入值，`api_type` 按模型卡派生，流式路径强制 `stream=True`），写了是噪声 |
| `agent.yaml` | `tools` 条目由内置 `read_file` 改为自定义 `read_material`（binding `custom_tools.read_material:read_material`） | 内置 `read_file` 读的是**沙箱**文件系统，而 NAC 的沙箱 pod 只挂 emptyDir `/home/user`、**不含制品目录 `/agent`**（runtime 侧只往沙箱上传 skills，制品其余部分不上传）。原写法在 NAC 上读不到 `materials/`，「工具结果拦截」这条主线演示不出来 |
| `agent.yaml` | 中间件注释里的「见教程设计要点 3」改为「见 TEMPLATE.md」 | 教程不随模板分发 |
| `custom_tools/read_material.py` | **新增** | 上一条的实现：跑在 runtime 进程，用 `Path(__file__).resolve().parent.parent / "materials"` 定位制品静态资源，带 `../` 逃逸防护和「文件不存在时返回可读清单」的自纠正返回 |
| `tools/read_material.tool.yaml` | **新增**（替换 `tools/read_file.tool.yaml`，已删除） | 配套 schema。保留 `additionalProperties: false`（本工具无 `extra_kwargs`，安全），并写了一行注释提醒「一旦加 extra_kwargs 就必须删掉这行」 |
| `systemprompt.md` | 材料清单由 `/agent/materials/xxx.txt` 改为文件名 `xxx.txt`，`read_file` 改为 `read_material` | 与新工具契约一致（新工具只吃文件名，不吃路径） |
| `materials/网民留言-20260601.txt` | 末尾说明里的 `read_file` → `read_material` | 同上 |
| `lexicon/README.md` | 末尾指向的「仓库内教程」改为指向 `TEMPLATE.md` | 教程不随模板分发 |
| `nexau.json` | **未改** | `agents` 映射到根目录 `agent.yaml` 是合法格式；`excluded` 平台不解析、留着无害（只是打包端约定，别当成「平台会按它排除文件」） |
| `lexicon/*.txt`、`tool_call_mode: structured` | **未改** | 词库逐字保留；`tool_call_mode` 原版已是合法值 `structured`（合法值只有 `xml` / `structured`） |
| `agent.yaml` | `system_prompt_type` 由 `file` 改为 `jinja` | 平台制品静态校验把 `system_prompt_type` 钉死为 `jinja`（`builder-static-rules.json.required_agent_fields`），`file` 直接报 `agent.field.invalid`。本模板的 `systemprompt.md` 不含任何 `{{ }}` / `{% %}`，按 jinja 渲染结果与 `file` 逐字相同 |
| `agent.yaml` | 新增 `skills: []`（带一行注释） | `skills` 是必需的列表字段（`required_list_fields`），缺键报 `skills.invalid_type`。本模板不挂 skill，显式写空列表 |
| `systemprompt.md` | 新增「# 运行环境」小节：声明 skills 根目录位于 `/home/user/.skills/`、以 `LoadSkill` 返回的 `SkillFolder` 为权威路径，并重申 `materials/` 只能经 `read_material` 读取 | 静态校验要求 systemprompt 里显式出现 skills 根目录（`agent.system_prompt.required_pattern_missing`）。顺带把原本只写在注释里的「制品目录不在沙箱里」这条边界摆到模型面前，与「已知的坑」里 `read_file` 那条呼应 |
| `custom_tools/__pycache__/` | **已删除** | 本地跑出来的 `.pyc` 产物，`excluded` 平台不解析，整目录打包会被带进制品 |

**裁剪掉的文件**：cookbook 原目录的 `tutorial-sensitive-word-guardrail.md`（教程正文，本文已提炼）。完整版在 `nexau-cookbook/敏感词过滤/`。
另删除了 `custom_tools/__pycache__/`（本地跑出来的 `.pyc` 产物）—— `nexau.json` 的 `excluded` 里虽写了 `__pycache__/`，但**平台完全不解析 `excluded`**（那只是打包端约定），整目录打包会把它一起带进制品。

**教程里已过时、本文已纠正的说法**：
- 「SensitiveWordMiddleware 尚未合入主线」——**已过时**。该中间件已随 SDK 分发，import 路径 `nexau.archs.main_sub.execution.middleware.sensitive_word:SensitiveWordMiddleware` 可直接用。
- 「什么都不传时使用包内自带的 3 词演示词库」——**已过时**，现在不传任何词库来源直接 `ValueError`。
- 「路径写错不会报错、静默加载 0 词」——**已过时**，`lexicon_dir` 不是目录时抛 `FileNotFoundError`。静默 0 词只发生在「目录存在但没有 `*.txt`」。
- 日志文案：命中日志实际是 `[SensitiveWordMiddleware] HIT source=... action=... categories=... hits=[...]`（不是 `BLOCKED`）；加载日志是 `loaded N words; block_input=.../... block_output=.../... case_sensitive=...`。

---

## 延伸

- `../../references/middlewares.md` —— 中间件通用契约（import 路径必须带 `execution` 层、参数名写错的报错形态）
- `../../references/custom-tools.md` —— 自定义工具三件套、进程边界、`extra_kwargs` × `additionalProperties` 的必崩组合
- `../../references/builtin-tools.md` —— 内置工具清单与 binding 串（含「内置文件工具都在沙箱里跑」这条边界）
- `../../references/llm-config.md` —— NAC 覆盖了 `llm_config` 的哪些字段
- `../../references/nexau-json-and-packaging.md` —— 打包硬约束（≤100 MiB、不许含符号链接、必须有 nexau.json）
- 相关模板：把本模板的 `middlewares:` 段装到 `01-agentic-rag`（知识库原文含敏感词的风险最高）或 `08-business-review` 上
