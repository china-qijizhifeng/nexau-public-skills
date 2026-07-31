# 模板：多技能协作文档生成（doc-generation）

> **PDF 进 / Word 出**的端到端制品流水线：三个 Skill 各司其职，靠 systemprompt 串成工序。难度 L3（实战）。来源：nexau-cookbook 《公文写作》样例（`tutorial-govdoc-writer.md`，公文写作 Agent）。

## 这个模板教你什么

1. **Schema 内联 > 让 Agent 去读 schema 文件**：把目标 JSON 的 `section` 结构 + ❌/✅ 字段对照表直接写死在 systemprompt，而不是指望 Agent 去读 `schemas/base.json`（它必然漏读 `$ref` 指向的公共定义）。
2. **需要编译的输出引擎（.NET/Go/Rust）怎么封装**：不让 Agent 碰 `dotnet`，用一个 shell 脚本 `scripts/build` 吃掉首次编译、SDK 预初始化、多 top-level statements 隔离、失败重试。
3. **`set -euo pipefail` 下 `find` 会杀脚本**：`bin/` 不存在时 `find` 返回 1 → 管道整体 1 → `set -e` 直接退出，Agent 只看到 "exit 1 无输出"。修法：**每一处 `find` 都要 `|| true`**（本脚本 7 处）。
4. **不要给命令接 `| tail` / `| head`**：`tail` 永远 exit 0，会把真实退出码吞掉，还截断错误信息。要看输出就 `2>&1`，不接管道。
5. **目录 basename 决定运行时路径，SKILL.md 的 `name` 决定 LoadSkill 调用名**——本模板里 `skills/pdf_to_md/` 的 frontmatter `name: pdf-to-md`，所以是 `LoadSkill("pdf-to-md")` 而路径落在 `/home/user/.skills/pdf_to_md`。这是两者可以不一致的活例子。
6. **双层防错**：内联 schema（前置，让 Agent 少犯错）+ build 脚本里的 Python JSON 预校验（后置，犯错了给可执行的错误提示，而不是吐一个 2KB 的空 Word）。

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 替代 |
|---|---|---|
| 输入是文件（PDF/扫描件），输出是 Word/PDF/OFD 制式文档 | ✅ 正是本模板 | — |
| 要生成任意结构化产物（JSON/YAML/SQL/配置）且格式必须精确 | ✅ 抄「Schema 内联 + 预校验」这套 | — |
| Skill 里含需要编译的代码（C#/Go/Rust） | ✅ 抄 `scripts/build` 的封装范式 | — |
| 只是知识库问答，不产出文件 | ❌ 过重 | `01-agentic-rag` |
| 只需要调外部 HTTP API 拿数据 | ❌ | `02-rest-api-tool` |
| 输出是 Excel / PPT 而非 Word | 🔶 骨架可抄，渲染引擎要换 | 把 `docx-report` 换成 openpyxl / python-pptx 脚本（沙箱已预装） |
| 完全离线 / 信创且沙箱不能出网 | ⚠️ 先解决 NuGet 取包（见「已知的坑」#1） | — |
| 需要审核/合规判定流程 | ❌ | `08-business-review` |

## 目录结构

```
07-doc-generation/
├── nexau.json                     制品清单：agents 映射（excluded 平台不解析，仅打包端约定）
├── agent.yaml                     主 agent：4 个内置工具 + 3 个 skill + 上下文压缩中间件
├── systemprompt.md                ★工序指令书：铁律 / 内联 schema / 6 种文种 JSON 模板 / 9 步工作流 / 禁令 / 故障排除表
├── tools/                         4 个内置工具的 tool.yaml（与 _builtin-tool-yamls 同源）
│   ├── read_file.tool.yaml
│   ├── write_file.tool.yaml
│   ├── search_file_content.tool.yaml
│   └── run_shell_command.tool.yaml   ← 唯一的"动手"通道：跑 OCR 脚本 + 跑 build render
└── skills/
    ├── pdf_to_md/                 Skill①（name: pdf-to-md）PDF → Markdown
    │   ├── SKILL.md               用法 + 返回 JSON 字段表 + OCR_API_KEY 作用域说明
    │   └── scripts/pdf_to_md.py   PyMuPDF 拆页 → SiliconFlow DeepSeek-OCR 并发 10 → 拼 md
    ├── docx-report/               Skill②（name: docx-report）JSON → .docx
    │   ├── SKILL.md               build 子命令 + section 字段对照表 + 各 type 的 required + references 导航
    │   ├── scripts/build          ★bash 封装：JSON 预校验 → 隔离编译 → dotnet 渲染；还有 batch/diff/pdf/ofd
    │   ├── template-index.json    type ↔ family ↔ schema ↔ required ↔ 别名 的单一事实源
    │   ├── schemas/               base.json（section/table 公共定义）+ govdoc/*.json + general/generic.json
    │   ├── templates/*.cs         C# OpenXML 渲染引擎（GovDocEngine.cs 是入口，其余是参考模板）
    │   ├── templates/GovDoc.csproj  net8.0 + DocumentFormat.OpenXml 3.2.0
    │   └── references/            GB/T 9704 与中办发〔2012〕14号 原文
    │       └── INDEX.md           references 根索引（本模板新增，见「已知的坑」#5）
    └── govdoc-writing/            Skill③（name: govdoc-writing）公文写作知识库，Agentic Search 模式
        ├── SKILL.md               文种速查表 + 标题层级表 + references 导航
        └── references/
            ├── INDEX.md           references 根索引（本模板新增）
            ├── guidelines/        格式标准 / 行文规则 / 常用套语（+ INDEX.md 子目录索引）
            └── templates/         6 种文种模板，每份都自带 JSON sections 示例（+ INDEX.md 子目录索引）
```

## 复制后必须改的地方

按编号逐条改，改完再打包。

> ⚠️ **动手前先确认数据去向**：`skills/pdf_to_md/scripts/pdf_to_md.py:24` 默认把**整页 PDF 原文**（base64）发到公网第三方 `api.siliconflow.cn` 做 OCR，`:56` 又用 `verify=False` 关掉了 TLS 校验。一旦输入含个人信息 / 涉密或政务材料，这就是一次**数据出境 + 委托处理**决策，必须先走合规确认，不是「能出网就能用」。内网 / 信创交付一律换成内网 OCR 或本地方案（沙箱已预装 PyMuPDF，纯文本 PDF 直接 `page.get_text()` 即可，完全不出网），并把 `verify` 改回 `True` 或配企业 CA。

1. **`nexau.json:agents`** → 把 `"govdoc_writer"` 换成你的 agent 名（小写 + 下划线）。这个 key 就是平台上的 agent 标识。
2. **`agent.yaml:name`** → 与上一步的 key **保持一致**。
3. **`agent.yaml:description`** → 换成你的业务描述（会展示给用户）。
4. **`agent.yaml:llm_config.model`** → 保持 `${env.LLM_MODEL}` 跟随项目默认模型。⚠️ 项目里一张可见模型卡都没有时，该 env 不会被注入，agent 加载期直接 `ConfigError`。
5. **`agent.yaml:llm_config.temperature`** → 公文/合同类保持 `0.2`；营销/创意文案调到 0.7+。
6. **`agent.yaml:middlewares[0].params.threshold`** → 输入文件很长就保持 `0.6`；输入短可放宽到 0.8。import 路径**必须**带 `execution` 层，且该中间件 `extra=forbid`，多写一个参数名直接报错。
7. **`agent.yaml:skills`** → 删掉你不需要的 skill 条目；条目值是**相对制品根的目录路径**，目录 basename 会成为 `/home/user/.skills/<basename>`。
8. **`skills/*/SKILL.md` frontmatter 的 `name`** → 这是 `LoadSkill("...")` 的调用名，改了它就必须同步改 systemprompt 里所有 `LoadSkill(...)` 调用。**改目录名不影响调用名，改 name 才影响。**
9. **`systemprompt.md` 的「正文结构 Schema」段** → 换成你自己产物的结构定义；❌/✅ 对照表要列出**你实际见过 Agent 犯的**字段名错误，不要照抄公文的。
10. **`systemprompt.md` 的「各公文类型 JSON 模板」段** → 换成你的输出类型模板，每个类型都要给 **完整示例 + `required` 字段清单**两样。
11. **`systemprompt.md` 的 `/home/user/.skills/` 那句话** → **不要删**。平台静态校验器有一条 `required_systemprompt_patterns`，正则 `(?i)skills\s*根目录位于\s*`?/home/user/\.skills/?`?`，删掉就校验失败。
12. **`systemprompt.md` 的「🚫 禁止操作」与「故障排除」两张表** → 这是模板的核心资产，**只增不删**。每跑一轮真机测试，把 Agent 新犯的错各补一行。
13. **换渲染引擎时**：`skills/docx-report/templates/*.cs`、`GovDoc.csproj`、`template-index.json`、`schemas/` 四处要同步改；`scripts/build check-index` 会校验 index 的 `required` 与 schema 的 `required` 是否一致、以及 `template-index.json` 里的 type 在引擎 `Render` switch 里是否都有实现——改完必跑一次。
14. **`skills/pdf_to_md/scripts/pdf_to_md.py:API_URL / MODEL`** → 换 OCR 供应商就改这两行；同时改 `OCR_API_KEY` 这个变量名的话，SKILL.md 和 systemprompt 故障排除表都要跟着改。
15. **环境变量按作用域配**（关键，配错就是读不到）：
    | 变量 | 谁读它 | 配在哪 |
    |---|---|---|
    | `LLM_MODEL` | agent.yaml 的 `${env.*}`，加载期在 **runtime pod** 取值 | runtime scope（平台按项目默认模型注入） |
    | `OCR_API_KEY` | `pdf_to_md.py`，经 `run_shell_command` 跑在**沙箱**里 | **sandbox scope**（运行配置 → 沙箱环境），或按次请求 `variables.sandbox_env` |
16. **打包前自查**：压缩包 ≤ 100 MiB；归档里**不能有符号链接**（有就 400 失败）；必须含 `nexau.json`。本模板本体约 368 KB，余量充足。

## 关键设计要点

### 要点 1：三个 Skill 而不是一个大脚本

tutorial 的原话对比：

```
❌ 一个大脚本包办一切（PDF解析 + 公文写作 + Word生成）：
   → 任何一环出问题，整体失败且难以定位
   → 无法复用——别的 Agent 也需要 PDF 解析或 Word 生成
   → 公文规范更新时，要改脚本而非知识库
✅ 三个 Skill 各司其职：
   → 每个 Skill 可以独立测试、独立更新
   → 公文规范更新只需修改 govdoc-writing 的 references，不动代码
```

**判据**：一个能力会被**多个 Agent** 复用 → 拆成独立 Skill；只有这一个 Agent 用的一次性逻辑 → 写进 systemprompt 或 custom_tools。

### 要点 2：Schema 内联——本模板最重要的决策

早期测试中 Agent 反复写错字段名（`title` 而非 `heading`、`content` 而非 `paragraphs`、漏 `level`），产出 < 3KB 的空 Word。

**根因**：`section` 定义在 `schemas/base.json`，各文种 schema 用 `$ref` 引它。Agent 读了 `notice.json` 就以为读完了，**永远漏掉 base.json**。

```
❌ "去读 schema 文件再构造 JSON"：漏读 $ref / 多一次读取 / 即使读了也可能理解偏差
✅ schema + ❌/✅ 对照表直接写在提示词里：零检索开销、零遗漏
```

tutorial 的结论原文：**「Schema 内联比"让 Agent 去读"可靠 10 倍」**——5 轮测试中内联后 JSON 构造零错误。

推广规则：任何要 Agent 产出结构化数据（JSON/YAML/SQL/配置）的制品，都把目标 schema 的**关键结构**内联到 systemprompt，并附 ❌/✅ 对照表。

### 要点 3：需要编译的引擎必须封成脚本

Agent 直接 `dotnet build` 会踩 **CS8802**（`templates/` 下多个 `.cs` 都有 top-level statements，只允许一个编译单元有）。`scripts/build render` 的解法是：mktemp 建临时目录 → 只把 `GovDocEngine.cs` 拷进去并**重命名成 `Program.cs`** → 隔离编译 → 产物拷回 `templates/bin/`。

配套三层防护（都在 `scripts/build` 里）：

| 层 | 做法 | 防的是 |
|---|---|---|
| 1 | 每处 `find ... \| head -1` 后接 `\|\| true` | `bin/` 不存在时 find 返 1 被 `set -e` 杀掉 |
| 2 | `dotnet --info > /dev/null 2>&1 \|\| true` 预初始化 SDK | 首次运行 `~/.dotnet` 未初始化导致 build 静默失败 |
| 3 | build 失败 `sleep 1` 后无静默重试一次 | SDK 初始化竞态 |

外加 `DOTNET_NOLOGO=1 / DOTNET_CLI_TELEMETRY_OPTOUT=1 / DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1`——离线沙箱里这三个不设会让首次 build 卡住。

**规则**：Skill 含编译型代码时，shell 脚本吃掉「首次编译 / 环境初始化 / 冲突隔离 / 输入校验」，Agent 只负责调一条命令。

### 要点 4：知识层用 Agentic Search，格式层用内联

同一个制品里两种策略并用，判据是**「Agent 每次是否都需要全部内容」**：

| 层 | 内容 | 策略 | 理由 |
|---|---|---|---|
| 格式层 | JSON schema / 字段名 | **内联到 systemprompt** | 每次都要用，且错一个字就废 |
| 知识层 | 6 种文种模板 + 3 份规范指南 | **Agentic Search**（SKILL.md 导航 + references 按需读） | 数万字，每次只用其中一两份 |

`govdoc-writing` 的每份 template 里都**自带 JSON sections 示例**——这是它区别于普通知识库的关键：Agent 查到"通知正文怎么写"的同时，直接看到能被 docx-report 渲染的 JSON 长什么样。于是有三层参照：systemprompt 的通用 schema（结构）→ template 的文种示例（内容）→ common-phrases（语言）。

### 要点 5：systemprompt 是工序指令书，不是人设

结构固定为：铁律 → 内联 schema → 各类型 JSON 模板 → 编号工作流 → 工具使用表 → **禁止操作** → **故障排除表**。

两个反直觉技巧（tutorial 明确的结论）：

- **禁令 > 正面引导**：「大模型对"不能做什么"比"应该做什么"的遵从度更高——定义失败条件比定义成功条件更能约束行为。」每条禁令都来自一次真实失败。
- **故障排除表 = Agent 的自愈手册**：把「错误现象 → 原因 → 解决方法」列成表，Agent 遇错能自主诊断修复，不用人介入。tutorial 的运营建议：部署后每发现一个 Agent 犯的错，就补一条禁令或一行故障表；**攒到 5–10 条后自主成功率显著提高**。

## 已知的坑

⚠️ **1. `dotnet restore` 需要沙箱能访问 NuGet**。沙箱镜像预装了 .NET SDK 8.0（`docker/Dockerfile.sandbox-aio` 里明确写着 "compile & run C# OpenXML code for 红头文件 docx generation"）和 LibreOffice，但 **`DocumentFormat.OpenXml 3.2.0` 没有预置 NuGet 缓存**，首次 `render` 会实时 restore。出网被 NFW 拦或纯离线环境 → 编译失败。修法：放通 NuGet 出网 / 预置离线包 / 或把编译好的 `templates/bin/` 一起打进制品（注意 100 MiB 上限）。

⚠️ **2. `set -euo pipefail` × `find`——本案例第 5 轮才挖到的真根因**。`bin/` 不存在时 `find` 返回 exit 1 → `pipefail` 让整条管道 1 → `set -e` 杀脚本 → 编译逻辑根本没跑到 → Agent 只看到「exit 1 无输出」。**7 处 `find` 全部要 `|| true`**。你新增任何 `find` / `grep` 之类"空结果是合法的"命令时，同样要加。

⚠️ **3. 别给命令接 `| tail` / `| head`**。`tail` 永远 exit 0，会把 `build render` 的真实退出码吞成 0，让 Agent 以为成功；还会截断错误信息。cookbook 原版自己在故障排除表里写了「加 `2>&1 | tail -50` 看详细错误」，**和它自己的禁令直接打架**——本模板已改掉（见下节改动表）。

⚠️ **4. Word 文件 < 3KB = JSON 有问题**，不是渲染失败。systemprompt 第九步的 `ls -la` 校验就是为这个。生成后必须验大小。

⚠️ **5. `references/` 每一层都必须有 `INDEX.md` 索引**。平台静态校验器的 `skill_reference_rules`（`require_root_index_when_nonempty` / `require_directory_indexes`）要求：非空的 `references/` 根目录、以及其下每个非空子目录，都要有一份导航索引（本 skill 统一命名 `INDEX.md`）。cookbook 原版缺 4 个（`docx-report/references/`、`govdoc-writing/references/` 及其 `guidelines/`、`templates/` 两个子目录），会报 `skills.references.index_missing` / `directory_index_missing`——**本模板已补齐**（⚠️ 校验器规则文件把 `index_file` 配成 `SKILL.md`，属平台缺陷，用 `INDEX.md` 仍会被报这几条，见 ../../references/artifact-spec-checklist.md §8）。

  两点容易踩：
  - 索引文件名一律 `INDEX.md` —— `SKILL.md` 是 skill 入口专用名，`references/` 下是知识库层级不是 skill，不该占用它。这些索引**不需要 frontmatter**（它们是目录导航，不是 skill 入口）。
    ⚠️ 校验器的规则文件当前把 `index_file` 配成了 `SKILL.md`（平台缺陷；散文规范 `artifact-hard-rules.md:156` 同样禁止 references 内用 `SKILL.md`，只是它推荐小写 `index.md`），所以用 `INDEX.md` 会被它误报 `index_missing` / `directory_index_missing` —— 见 `../../references/artifact-spec-checklist.md` §8。
  - 索引里出现的**行内代码和链接会被校验器当路径检查**：必须真实存在、且解析后仍落在本 skill 的 `references/` 目录内。所以别在索引里写绝对路径（如 `/home/user/.skills/...`，会判 `path_escapes_skill_root`）、也别用反引号提上级目录的文件（会判 `path_missing` / `path_outside_references_dir`）。

⚠️ **6. `pdf_to_md.py` 里 `httpx.HTTPTransport(verify=False)`**——关掉了 TLS 校验。是为了穿沙箱 MITM 代理，但等于放弃证书验证；对安全敏感的部署要评估。

⚠️ **7. OCR_API_KEY 属沙箱作用域**。`custom_tools` 的 Python 函数跑在 agent-runtime 进程（读 runtime scope，`${env.X}` 也从这里取），而 `run_shell_command` 跑的脚本在**沙箱**里（只能读 sandbox scope / `variables.sandbox_env`）。本模板的 OCR 脚本属后者。两条通路互不可见，配错 scope 表现就是"明明配了却读不到"。详见 `../../references/env-vars-and-secrets.md`。

⚠️ **8. `${env.LLM_MODEL}` 是硬失败**。`${env.X}` 是加载期对整个 agent.yaml **文本**做正则替换（在 `yaml.safe_load` 之前），连注释里的 `${env.X}` 也会被解析；未设置 = `ConfigError`，不支持默认值语法。项目里没有任何可见模型卡时该变量不注入 → agent 起不来。

⚠️ **9. 中文输出文件名会乱码**。systemprompt 已有禁令，改造时别放宽。

## 本模板相对 cookbook 原版的改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `agent.yaml` | 删掉 `llm_config.base_url` / `api_key` / `api_type` / `stream` 四行 | NAC 上 `base_url`/`api_key` 被平台无条件覆盖，`api_type` 被模型卡派生值覆盖，`stream` 在流式路径被强制 True——写了不生效，纯噪声，还会让人误以为可以在制品里改连接参数 |
| `agent.yaml` | 新增 3 行注释：说明上述覆盖 + **本地裸跑 NexAU（不经 NAC）时需自行补 base_url / api_key** | 删字段后必须留下逃生说明，否则拿去本地跑不通 |
| `systemprompt.md` 规则 1 | 新增「部署后 skills 根目录位于 `/home/user/.skills/`……但取值仍以 LoadSkill 返回的 `<SkillFolder>` 为准」；同时把 `.skills/...` 从"禁止猜测路径"的示例里移除（**规则 1 和「🚫 禁止操作」两处都要改**） | 平台静态校验器 `required_systemprompt_patterns` 强制要求 systemprompt 显式写出这个根目录；原文把 `.skills/` 列为反例会与该要求自相矛盾 |
| `systemprompt.md` 故障排除表 | `加 2>&1 \| tail -50 看详细错误` → `看 2>&1 的完整输出（不要接 \| tail）` | 与同一份文件里的禁令「禁止在 build render 后加管道」直接冲突，也违反 tutorial 自己总结的教训 #2；照原样 Agent 会被引导去吞掉退出码 |
| `systemprompt.md` 第三步 | 改成两档：消息里已给出 `full_text.md` / `page_{N}.md` 路径就直接 `read_file`，只有拿到未转换的 `.pdf` 才回退跑 `pdf_to_md.py` | Playground / SimpleChat 上传 PDF 后平台会自动 OCR 并把转好的 Markdown 路径拼进 user message（`frontend/src/pages/Playground/messageHelpers.ts:242-270`，产物目录 `/home/user/uploads/converted/{file_id}/`）。原文让 Agent 无条件再转一遍是重复劳动，还平白把 `OCR_API_KEY` 变成主路径的硬依赖 |
| `systemprompt.md` 故障排除表 | 新增一行：首次 render 卡在 `dotnet restore` / NuGet 失败 → 出网问题 | 沙箱不预置 NuGet 包，这是真机上最可能出现且原表没覆盖的失败模式 |
| `systemprompt.md` 故障排除表 | `PDF 解析返回 API Key required / 联系管理员注入环境变量` → 改成脚本真实报错串 + 明确「必须配在**沙箱环境**（sandbox scope）」 | 原文的错误串与脚本实际抛的 `OCR_API_KEY environment variable is required for PDF OCR` 对不上；且"注入环境变量"没说作用域，配到 runtime scope 是最常见的踩坑 |
| `skills/docx-report/SKILL.md` | 同上两处：去掉 `\| tail -50` 建议；新增 NuGet 出网失败一行 | 同上 |
| `skills/govdoc-writing/SKILL.md` | 「使用方法」第 2/3/4 步的路径补上 `references/` 前缀（原文写成 `guidelines/format-standard.md`） | 磁盘上没有顶层 `guidelines/` 目录，真实路径是 `references/guidelines/…`；同文件 :44-46 的导航表本来就是对的，属「改了表没改正文」。⚠️ 校验器抓不到这类错：`artifact_static_validator.py:763` 扫 skill 根 SKILL.md 时只校验含 `references/` 的路径，**不带该前缀的相对路径是校验盲区** |
| `skills/pdf_to_md/SKILL.md` | `OCR_API_KEY（由平台注入）` → 写明 sandbox scope + 配置位置；依赖段补一句「PyMuPDF / httpx 已预装在沙箱 `/opt/sandbox-python` venv」 | "由平台注入"是错的（平台不会自动给你注 OCR key）；依赖可用性写清楚可以避免 Agent 去 pip install |
| `skills/docx-report/references/INDEX.md` | **新增**：references 根索引，列出两份法规原文各自的内容与查阅时机，并给出「查排版 vs 查文种」的分工判据 | 校验器 `require_root_index_when_nonempty` 强制非空 references/ 必须有根索引，缺则报 `skills.references.index_missing` |
| `skills/docx-report/SKILL.md` | **新增**「references/ 目录导航」一节（两份法规原文的内容 / 查阅时机 + 指向 `references/INDEX.md`） | 只放 INDEX.md 不够：框架的 `Skill.from_folder` 只自动加载 skill 根 `SKILL.md`，references/ 全靠 SKILL.md 明确导航才会被 Agent 读到。原版 docx-report/SKILL.md 全文不提 references，那两份法规是**没有任何入口的孤儿**（对照组 `govdoc-writing/SKILL.md` 有完整导航段）。补上后才真正接进 Agentic Search 路径 |
| `skills/govdoc-writing/references/INDEX.md` | **新增**：references 根索引，列出 `guidelines/` 与 `templates/` 两个子目录的分工、各自文件速览、以及「定文种 → 写正文 → 核排版 → 顺措辞」的查阅顺序 | 同上（`index_missing`） |
| `skills/govdoc-writing/references/guidelines/INDEX.md` | **新增**：子目录索引，3 份规范指南（格式标准 / 行文规则 / 常用套语）的内容与查阅时机 | 校验器 `require_directory_indexes` 强制每个非空 references/ 子目录都要有索引，缺则报 `skills.references.directory_index_missing` |
| `skills/govdoc-writing/references/templates/INDEX.md` | **新增**：子目录索引，6 份文种模板 ↔ 覆盖文种 ↔ `docx-report` type ↔ 行文方向 的对照表 + 使用步骤 | 同上（`directory_index_missing`） |
| 上述 4 个新增索引 | 一律**不写 frontmatter**；行内代码里只出现相对本目录真实存在的路径，不写绝对路径、不写 `../` 越级引用 | 校验器会把索引里的行内代码 / 链接当引用路径逐一校验存在性与边界，写错即 `path_missing` / `path_escapes_skill_root` / `path_outside_references_dir` |

**未改动、逐字保留的**：`nexau.json`（含平台并不解析的 `excluded` 字段和 `start.py` 残留）、4 个 tool.yaml（无 `extra_kwargs`，`additionalProperties: false` 可安全保留）、`tool_call_mode: structured`（已是合法值）、中间件 import 路径（已带 `execution` 层）、`scripts/build`、所有 `.cs` / `schemas/` / `template-index.json`，以及 `references/` 下原有的法规原文与指南 / 模板正文（新增的 4 个 `INDEX.md` 索引是纯增量，未改动任何一份原有资料）。

**裁剪情况**：本模板是 cookbook `公文写作/公文写作 Agent/` 的**完整拷贝，未删任何文件**；相对原版**新增的文件**只有 4 个 `references/INDEX.md` 导航索引，其余改动都是上表列出的就地编辑。tutorial 原文在 `nexau-cookbook/公文写作/tutorial-govdoc-writer.md`。

## 延伸

- 平台事实与字段契约：`../../references/agent-yaml-fields.md`、`../../references/llm-config.md`、`../../references/middlewares.md`
- 环境变量 / 密钥双通路（本模板踩点最多）：`../../references/env-vars-and-secrets.md`
- 内置工具清单与 tool.yaml 规范：`../../references/builtin-tools.md`
- 打包硬约束（100 MiB / 无符号链接 / setup 离线 whl）：`../../references/nexau-json-and-packaging.md`
- 错误速查：`../../references/troubleshooting.md`
- 相关模板：`01-agentic-rag`（纯知识库问答，无产物）、`08-business-review`（把本模板的产物再接一道审核流程）、`10-reference-skeleton`（只要 Agentic Search 骨架时）
