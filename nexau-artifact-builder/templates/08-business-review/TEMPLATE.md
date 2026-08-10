# 模板：业务审核 Agent（08-business-review）

> 政务/企业**合规审核类** Agent 的集大成骨架：法规知识按需检索 + PDF 材料 OCR + 交叉核验 + 强约束结论输出。难度 L3（最高）。来源：nexau-cookbook《住房公积金审核》（`tutorial-house-fund-review.md`，8 大设计原则的出处）。

## 这个模板教你什么

1. **三层分离**：`systemprompt.md`（怎么干活）/ `SKILL.md`（业务规则）/ `references/*.md`（法规原文）各管一层，改法规不改逻辑、不改 prompt。
2. **多 Skill 协同**：一个 agent 挂 2 个 skill——领域大脑（`house-fund-review`）+ 能力扩展（`pdf_to_md`），由 systemprompt 编排调用顺序。
3. **Skill 携带可执行脚本**：skill 目录里放 `scripts/*.py`，Agent 用 `run_shell_command` 跑它（**不是**注册成工具），密钥走沙箱环境变量而非参数。
4. **索引 + 原文分离的 Agentic RAG**：SKILL.md 里写"哪份文件、哪一条、优先级如何"，Agent 自己 `read_file` 拿原文引用，杜绝凭记忆编条款。
5. **边界防御三件套**：风险红线清单（法规里没有、实务提炼的）+ "不知道就说不知道"的退出路径（12329 热线）+ 易漏规则显式提醒。
6. **输出格式即质量控制**：结论先行 / 必须标注条款编号 / ✅❌⚠️ 三级状态标记，把格式约束当审核质量的强制项。

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 替代 |
|---|---|---|
| 依据成文法规/制度做条件判断 + 材料齐全性预审 | ✅ 正解 | — |
| 纯法规问答，不涉及材料/附件 | 🔶 过重 | `01-agentic-rag`（去掉 pdf_to_md 层） |
| 要读用户上传的 PDF/扫描件并交叉核验 | ✅ 正解 | — |
| 知识全在数据库/结构化表里，要算数字 | ❌ | `03-text-to-sql` |
| 知识来自外部 REST API / 内部系统 | ❌ | `02-rest-api-tool` / `04-mcp-server` |
| 知识库有几十上百份文档，要分层检索 | 🔶 骨架可用，知识层要重做 | 配合 `skill-knowledge-organizer` 做层级化 |
| 主要产物是一份生成的文档（报告/公文） | ❌ | `07-doc-generation` |
| 需要对输出做内容安全过滤 | 🔶 叠加使用 | `09-content-guardrail` 的中间件 |
| 材料涉个人信息 / 不允许出网（政务外网，无 OCR 外网 API） | ⚠️ 删掉 `pdf_to_md` 整层或换内网 OCR（默认脚本会把 PDF 原文发到公网第三方，见下方数据去向提示） | `05-native-driver-airgap` |

## 目录结构

```
08-business-review/
├── nexau.json                       # 制品清单：声明 agent 入口（agents.house_fund_review → agent.yaml）
├── agent.yaml                       # 骨架：模型、6 个内置工具注册、2 个 skill 挂载、middlewares: []
├── systemprompt.md                  # 指挥层：角色 + 5 步处理流程 + PDF 处理指引 + 输出规范 + 边界注意
├── tools/                           # 内置工具的 input_schema 副本（8 个 yaml）
│   ├── read_file / write_file / replace .tool.yaml        # 已在 agent.yaml 注册
│   ├── search_file_content / list_directory .tool.yaml    # 已在 agent.yaml 注册
│   ├── run_shell_command.tool.yaml                        # 已注册，跑 pdf_to_md 脚本靠它
│   └── ask_user / complete_task .tool.yaml                # ⚠️ 随包但**未注册**，要用需自己加进 agent.yaml
└── skills/
    ├── house-fund-review/           # 领域大脑：6 步审核工作流 + 法规索引 + 输出模板
    │   ├── SKILL.md
    │   └── references/
    │       ├── INDEX.md             # references 导航索引（文件清单 + 十章速查 + 未随附上位法说明）
    │       └── 上海市住房公积金提取管理办法.md   # 法规原文（本模板只保留这一份，见「相对原版的改动」）
    └── pdf_to_md/                   # 能力扩展：PDF → Markdown（OCR）
        ├── SKILL.md                 # 面向 Agent：何时用、怎么调、返回什么
        └── scripts/pdf_to_md.py     # 面向机器：PyMuPDF 拆页 + DeepSeek-OCR 并发识别
```

## 复制后必须改的地方

> ⚠️ **动手前先确认数据去向**：`skills/pdf_to_md/scripts/pdf_to_md.py:16` 默认把**整页 PDF 原文**（base64）发到公网第三方 `api.siliconflow.cn` 做 OCR，`:54` 又用 `verify=False` 关掉了 TLS 校验。本模板收的是市民的身份证 / 房产证 / 购房合同，一旦照默认配置上线，这就是一次**数据出境 + 委托处理**决策，必须先走合规确认，不是「能出网就能用」。内网 / 政务交付一律用 `OCR_BASE_URL` 指到内网 OCR，或整层删掉 `pdf_to_md`（沙箱已预装 PyMuPDF，纯文本 PDF 直接 `page.get_text()` 即可，完全不出网），并把 `verify` 改回 `True` 或配企业 CA。

| # | 文件:字段 | 改成什么 |
|---|---|---|
| 1 | `nexau.json` : `agents` 的 key | 你的 agent 名（英文 snake_case），value 保持 `agent.yaml` |
| 2 | `agent.yaml` : `name` | 与上面 key **逐字一致**的 agent 名（不一致平台静态校验器直接判 `nexau_json.agent_name.mismatch`） |
| 3 | `agent.yaml` : `skills` 列表 | 改成你自己的 skill 目录；**目录 basename 就是运行时路径的最后一段**，改名要连带改 systemprompt 里所有 `/home/user/.skills/<basename>/…` |
| 4 | `agent.yaml` : `llm_config.model` | 保持 `${env.LLM_MODEL}`（跟随项目默认模型）；⚠️ 项目一张可见模型卡都没有时该 env 不会注入，agent 加载直接 ConfigError。要钉死模型就写平台模型卡**全键** `provider/model_name`；⚠️ 别写裸名（如 `gpt-4o`）——sidecar 见无 `provider/` 前缀直接 Reject 且不走回落，平台静态校验器也判 error |
| 5 | `agent.yaml` : `max_tokens` / `temperature` | `max_tokens` 按业务调。**`temperature` 本模板已定为 `0.2`**（合规审核属 `../../references/llm-config.md` §5.5 的「法律 / 金融」档：需精确引用、禁止发挥；cookbook 原版是 `1`，见「相对原版的改动」），创意类才往上调。⚠️ **模型卡默认开了 anthropic `thinking` 时上游要求 `temperature: 1`**，平台不做运行期纠正——那种情况改回 `1` 或把该行整行删掉 |
| 6 | `systemprompt.md` 第 1 行 | 一句话角色定义，换成你的业务身份 |
| 7 | `systemprompt.md` : `# Skill 加载` / `# 处理流程` 里的 skill 名与路径 | 全量替换 `house-fund-review` → 你的 skill 名；路径根 `/home/user/.skills/` **必须保留原样**（平台静态校验器要求显式出现该根目录） |
| 8 | `systemprompt.md` : `# 关键注意事项` 的退出路径 | 把 `12329` 换成你业务的求助渠道；没有渠道也要写"转人工复核" |
| 9 | `skills/house-fund-review/` 整个目录 | 换成你的领域：frontmatter `name`/`description`（description 要**低触发门槛**，见下）、6 步工作流、法规索引、材料表、频次额度表、风险清单、输出模板 |
| 10 | `skills/house-fund-review/references/*.md` | 换成你的原文（法规/制度/标准）。SKILL.md 的「核心法规依据」清单、以及 `references/INDEX.md` 这份导航索引，都必须与 `references/` 下**实际存在的文件**逐一对齐，否则 Agent 会去读不存在的文件（索引缺失或指向不存在/越界路径，静态校验器也会判 error） |
| 11 | `skills/pdf_to_md/` | 不需要 OCR 就整个删掉，同时删 `agent.yaml` 的 `skills` 那一行 + systemprompt 的 `# PDF 处理` 整节 |
| 12 | **环境变量：`OCR_API_KEY`（+ 可选 `OCR_BASE_URL`）** | 必须配置在 **sandbox scope**（脚本跑在沙箱里，runtime scope 的变量它读不到）。见 `../../references/env-vars-and-secrets.md` |
| 13 | `tools/*.tool.yaml` | 通常原样复用。`ask_user` / `complete_task` 两份**随包但未注册**（本模板不挂它们）。要用就得在 `agent.yaml` 里补 `tools` 条目，且**两个都必须登记进 `stop_tools`**（`stop_tools: [ask_user, complete_task]`）——`ask_user` 自己不停机（它只是返回一段文本），停机的唯一来源是框架在工具执行后拿工具名去比对 `stop_tools`；漏写会一路兜到 `max_iterations: 300` |
| 14 | 打包前 | 目录内**不得有符号链接**（含符号链接的归档必 400 失败）、压缩包 ≤ 100 MiB、必须含 `nexau.json`。见 `../../references/nexau-json-and-packaging.md` |

## 关键设计要点

来自 tutorial 的**8 大设计原则**（整个 cookbook 的方法论顶点，原样保留）：

| # | 原则 | 一句话 |
|---|------|-------|
| 1 | 三层分离 | System Prompt 管流程，Skill 管知识，References 管原文 |
| 2 | Prompt 只做指挥官 | 告诉 Agent "怎么干活"，不告诉它"你知道什么" |
| 3 | Skill 可插拔 | 用元数据 description + 低触发门槛设计，让 Agent 知道何时启用 |
| 4 | 知识按需加载 | 原文存文件 + 索引指引，不塞进 prompt |
| 5 | 表格优于散文 | 分类、材料、条件、额度等信息用表格呈现 |
| 6 | 显式处理边界 | 风险清单、"不知道就说不知道"、容易遗漏的提醒 |
| 7 | 工具结果要引导 | 不只是"用工具"，还要告诉 Agent 拿到结果后做什么 |
| 8 | 输出格式 = 质量控制 | 定义输出模板，强制结论先行、引用条款、状态标记 |

配套的对比/反例（生成新制品时照抄这些模式）：

- **原则 1 反例**：所有内容塞进 System Prompt → 改一个条款要翻 3000 行、法规更新要重测整个 Agent、每次对话都加载全部法规。本模板：systemprompt ~60 行 + SKILL ~200 行 + 原文按需 `read_file`。
- **原则 3 低触发门槛**：description 末尾必须有一句"即使用户只是随口问一下……也应触发此 skill"，避免模糊场景下 Agent 不敢用 skill。
- **原则 4 索引三要素**：文件在哪（文件名）+ 优先级（"以《提取管理办法》为主，未覆盖再向上查"）+ 入口（"提取范围见第 24 条"）。三样缺一，Agent 就会退化成凭训练数据回答。
- **原则 5 关键词列**：分类表要额外加一列"关键词"，专门给 LLM 做映射（用户说"房租" → 第（四）项租赁住房），比让 LLM"自己理解意图"可靠得多。
- **原则 6 退出路径**：`不编造法规条款。遇到法规未覆盖的边界情况，明确告知"建议咨询…（12329）"` —— 给 LLM 一条**合法的**认输通道，是防幻觉最有效的一句话。
- **原则 7 工具结果引导**：光让 Agent 转 PDF 只会得到"内容摘要"；systemprompt 里那 5 条「解析后的核验要点」（姓名一致性 / 地址地域 / 日期有效期 / 金额匹配 / 多份材料相互印证）才把"看 PDF"变成"审 PDF"。
- **原则 8 输出契约**：咨询类固定 5 段（结论/依据/材料/频次额度/注意事项），预审类固定 ✅❌⚠️ 三级标记。

写完 SKILL.md 用这 5 个问题自查：触发条件够宽吗 / 步骤够细吗（每步只做一件事）/ 表格够多吗 / 退出路径有吗 / 容易遗漏的规则标出来了吗。

## 已知的坑

| ⚠️ 坑 | 表现 | 修法 |
|---|---|---|
| **skill 相对路径在 NAC 上不存在** | systemprompt 写 `skills/xxx/SKILL.md`，部署后 Agent `read_file` 报 file not found（真实路径是 `/home/user/.skills/xxx/SKILL.md`，工作目录 `/home/user`） | 用 `LoadSkill` 拿 `<SkillFolder>`（权威取值），或写绝对路径 `/home/user/.skills/<目录 basename>/…`。本模板已修 |
| **skill 目录名 ≠ frontmatter name** | `skills/pdf_to_md/` 目录 basename 决定**路径**，SKILL.md 里 `name: pdf-to-md` 决定 `LoadSkill` 用什么**名字**调用 —— 两者不一致但都合法，混用会各种"找不到" | 路径一律用 basename（`pdf_to_md`），`LoadSkill` 一律用 frontmatter name（`pdf-to-md`）。新写 skill 建议两者取一致 |
| **skill 里的脚本不是工具** | SKILL.md 写成 `pdf_to_md(file_path=…)`，Agent 会去调一个根本没注册的工具 | 明确写"用 `run_shell_command` 跑 `<绝对路径>/scripts/xxx.py`"。本模板已修 |
| **脚本密钥拿不到** | 脚本抛 `API Key required for PDF OCR` | 脚本跑在**沙箱**，只能读 sandbox scope 环境变量 / per-request `variables.sandbox_env`；custom_tools 的 Python 才读 runtime scope。两条通路互不可见 |
| **`${env.LLM_MODEL}` 未注入** | agent 加载期 ConfigError 硬失败 | `${env.X}` 是加载期对整份 yaml 文本做正则替换（连注释里的也会被解析），未设置就直接失败，**不支持默认值语法**。项目至少要有一张可见模型卡 |
| **法规原文被裁剪后索引对不上** | SKILL.md 说有 3 份文件，`references/` 只有 1 份 → Agent 反复读不存在的文件、或退化成凭记忆答 | 索引清单必须与实际文件逐一对齐；建议 Agent 先 `list_directory` 再读。本模板已修 |
| **多页 PDF 跨页表格** | OCR 逐页独立识别，跨页表格断裂 | SKILL.md 的「注意事项」已声明，需人工核对；把不确定字段标 ⚠️ |
| **OCR 结果被截断** | 脚本只返回前 10000 字符 | 返回值 `truncated == "True"` 时用 `read_file` 读 `output_file`。systemprompt 已写明 |
| **脚本 `verify=False`** | `pdf_to_md.py` 的 httpx transport 关闭了 TLS 校验 | 原样保留自 cookbook。生产/政务环境上线前建议改回 `verify=True` 或配置企业 CA |
| **`references/` 里写绝对路径会被判「越界」** | SKILL.md / references 索引里用反引号包一条 `/home/user/.skills/<skill>/references/`，静态校验器报 `skills.references.path_escapes_skill_root`（它把代码块里的路径按**相对当前 skill 目录**解析，绝对路径一律算逃逸） | 代码块里只写相对路径（`references/`、`xxx.md`）；要说明部署后的绝对位置就写成普通正文，不加反引号。本模板已修 |
| **`references/` 缺导航索引** | 非空的 `references/`（及其每个非空子目录）没有导航索引，静态校验器报 `skills.references.index_missing` / `directory_index_missing` | 每层放一份 `INDEX.md` 导航（文件清单 + 一句话作用 + 定位速查），内容要写真实存在的文件。⚠️ 校验器规则文件把 `index_file` 配成了 `SKILL.md`（平台缺陷），用 `INDEX.md` 会被它报这一条——见 ../../references/artifact-spec-checklist.md §8。本模板已补 |
| **`additionalProperties: false` × extra_kwargs** | 本模板 6 个注册工具都**没有** extra_kwargs，所以保留 `additionalProperties: false` 安全；但你若给自定义工具配了 `extra_kwargs`，必须删掉该行，否则必报 `Additional properties are not allowed` | 见 `../../references/custom-tools.md` |

## 本模板相对 cookbook 原版的改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `agent.yaml` | 删 `llm_config.base_url` / `api_key` / `api_type` / `stream` 四个字段，只留 `model` + `max_tokens` + `temperature` | NAC 上 `base_url`/`api_key` 被平台无条件覆盖、`api_type` 被模型卡派生值覆盖、`stream` 在流式路径强制 True —— 写了不生效，纯噪声 |
| `agent.yaml` | 新增 4 行注释说明"连接四件套由平台注入；本地裸跑 NexAU 需自行补 base_url / api_key" | 避免使用者以为模板缺字段；注释里刻意不写 `${env.…}` 语法，因为 `${env.X}` 连注释一起被正则解析 |
| `systemprompt.md` | `skills/house-fund-review/…` → `/home/user/.skills/house-fund-review/…`，并新增一句"`LoadSkill` 返回的 `<SkillFolder>` 是权威路径" | 原相对路径在部署后不存在，Agent 必然读不到 SKILL.md |
| `systemprompt.md` 第 5 行 | 删掉「**或直接读取** `/home/user/.skills/house-fund-review/SKILL.md`」这个备选 | 把「不加载 skill 直接拼路径读文件」写成官方备选，正是本 skill `../../SKILL.md`「四个必须防的 Agent 坏习惯」表里点名的第 2 条，也和同文件下一段「一律以 `LoadSkill` 返回的 `<SkillFolder>` 为权威路径」自相矛盾。后文正文里的绝对路径保留（那里已声明只是 `<SkillFolder>` 的默认形态） |
| `systemprompt.md` | 第 3 步 "使用 `pdf_to_md` 工具" → "用 `pdf_to_md` 技能提供的脚本" | 制品里根本没有名为 `pdf_to_md` 的工具，原文会诱导 Agent 调用不存在的工具 |
| `systemprompt.md` | `# PDF 处理 / 转换方式` 改成两档：消息里已给出 `full_text.md` / `page_{N}.md` 路径就直接 `read_file`，只有拿到未转换的 `.pdf` 才回退跑脚本 | Playground / SimpleChat 上传 PDF 后平台会自动 OCR 并把转好的 Markdown 路径拼进 user message（产物目录 `/home/user/uploads/converted/{file_id}/`）。原文让 Agent 无条件再转一遍，是重复劳动，还平白把 `OCR_API_KEY` 变成主路径的硬依赖 |
| `systemprompt.md` | `# PDF 处理` 新增一段：脚本依赖 `OCR_API_KEY`/`OCR_BASE_URL`，缺失时直接告知用户而非伪造结果 | 密钥缺失是最常见的部署失败点，且必须防"OCR 失败后编造材料内容" |
| `skills/house-fund-review/SKILL.md` | 「核心法规依据」三份文件的清单，改为标注 1 份随附 + 2 份未随附；新增"先 `list_directory` 确认实际文件"与绝对路径提示 | 本模板已裁剪掉 2 份原文（见下），索引与实际文件不一致会导致读不存在的文件 |
| `skills/pdf_to_md/SKILL.md` | 「使用方式」由 `pdf_to_md(file_path=…)` 工具调用改为 `run_shell_command` + 绝对脚本路径 | 同上，纠正不存在的工具调用 |
| `skills/pdf_to_md/SKILL.md` | 「注意事项」`SILICONFLOW_API_KEY`（已有默认值）→ `OCR_API_KEY`（必填无默认）+ `OCR_BASE_URL`（可选）+ 必须配 sandbox scope；依赖那条补"沙箱已预装、无需 setup" | 对着 `scripts/pdf_to_md.py:106-107` 核实，原文的变量名与"已有默认值"两处都是错的；cookbook 金融篇「沙箱只有标准库」的说法也已过时（沙箱预装 PyMuPDF/httpx） |
| **裁剪** `skills/house-fund-review/references/住房公积金管理条例.md`、`上海市住房公积金管理若干规定.md` | 已删除，仅保留最常用的《上海市住房公积金提取管理办法》 | 控制模板体积；完整 3 份原文见 cookbook 原目录 `nexau-cookbook/住房公积金审核/住房公积金提取审核/skills/house-fund-review/references/` |
| `agent.yaml` | `name: house_fund_review_agent` → `name: house_fund_review` | 必须与 `nexau.json` 的 agent key 逐字一致，原版两处不一致（校验器 `nexau_json.agent_name.mismatch`）。改 `agent.yaml` 而非 `nexau.json`，是为了让 `nexau.json` 继续逐字保留原版 |
| `agent.yaml` | `llm_config.temperature: 1` → `0.2`（并在 yaml 里加注说明原值与 thinking 例外） | 原版的 `1` 与本 skill `../../references/llm-config.md` §5.5 直接打架：本模板做的是住房公积金提取的**政务合规核查**，正是该表里「法律 / 金融问答 → 0.0–0.2，需要精确引用、禁止发挥」那一档。平台对 temperature **不做任何运行期纠正**，填 `1` 就真按 `1` 发上去。唯一该保留 `1` 的情形是模型卡默认开了 anthropic `thinking`（上游强制 `temperature: 1`），已写进注释 |
| `agent.yaml` | 末尾新增 `middlewares: []` + 一行说明注释 | `middlewares` 是必填列表键，缺键判 `middlewares.invalid_type`；本模板不挂中间件，故给空列表 |
| `systemprompt.md` | 「技能目录部署后统一位于 …」改写为「部署后 skills 根目录位于 `/home/user/.skills/`，每个技能都是它下面的一个子目录……一律以 `LoadSkill` 返回的 `<SkillFolder>` 为权威路径」 | 校验器要求 systemprompt 里**原样出现**「skills 根目录位于 `/home/user/.skills/`」这个措辞（`agent.system_prompt.required_pattern_missing`），原文语义对但措辞不匹配；顺带把「绝对路径只是 `<SkillFolder>` 的默认形态」讲清楚 |
| `skills/house-fund-review/SKILL.md` | 「核心法规依据」开头那句里的代码块绝对路径 `` `/home/user/.skills/house-fund-review/references/` `` 改为正文叙述（不加反引号），代码块只留 `references/`，并加一句指向本目录的导航索引 | 校验器把 SKILL.md 代码块里的路径按**相对 skill 根**解析，绝对路径一律判 `skills.references.path_escapes_skill_root` |
| **新增** `skills/house-fund-review/references/INDEX.md` | 新写一份 references 导航索引：实际文件清单（只有《上海市住房公积金提取管理办法》一份）+ 该办法十章的条款范围与用途速查 + 明确列出两份**未随附**的上位法并给退出路径 | 非空 `references/` 必须有 `INDEX.md` 索引（校验器因 `index_file` 配置缺陷会报 `skills.references.index_missing`）。内容按目录里**真实存在**的文件写，裁剪掉的两份只作为"不在本目录、读了必失败"的告警出现 |
| `TEMPLATE.md` | 目录树补 `references/INDEX.md` 与 `middlewares: []`；「必须改的地方」第 2/10 条补校验器硬约束；「已知的坑」新增 2 行（references 绝对路径越界、references 缺索引） | 与上述改动保持一致 |
| `TEMPLATE.md` | 「必须改的地方」开头新增**数据去向**提示；选型表「完全离线」那格改成「材料涉个人信息 / 不允许出网」；第 13 条把 `stop_tools` 的要求从只系在 `complete_task` 上改成 `ask_user` / `complete_task` **两个都要登记** | ① 原文只把公网 OCR 当连通性问题（「能出网就没问题」），本模板处理的是市民材料，数据出境是**合规决策**不是可用性选项；② `ask_user` 同样不自带停机（它只返回文本），照原第 13 条加挂就会漏配 `stop_tools` 兜到 `max_iterations` |
| 未改动 | `nexau.json`（含 `excluded`）、`tools/*.tool.yaml`（8 份，`additionalProperties: false` 全保留）、`scripts/pdf_to_md.py`、SKILL.md 的业务表格与工作流 | 逐字保留原版。⚠️ 注意 `excluded` 平台**完全不解析**，只是打包端约定 |
| 未改动 | `tool_call_mode: structured` | 原版已是合法值（合法值只有 `xml` / `structured`），无需改 |
| `TEMPLATE.md` 第 4 条 | 「要钉死模型就写死模型名」→ 明确要求写 `provider/model_name` 全键并警告裸名 | 裸名比写错全键更糟：sidecar 直接 Reject 不回落，平台静态校验器判 error（见 `../../references/troubleshooting.md`） |

## 延伸

- 通用知识：`../../references/agent-yaml-fields.md`（字段契约）、`../../references/llm-config.md`（平台覆盖规则）、`../../references/builtin-tools.md`（6 个内置工具的 binding）、`../../references/env-vars-and-secrets.md`（runtime vs sandbox 两条密钥通路）、`../../references/nexau-json-and-packaging.md`（打包硬约束）、`../../references/custom-tools.md`（extra_kwargs 与 schema 冲突）
- 相关模板：`../01-agentic-rag`（本模板知识层的简化版）、`../07-doc-generation`（产物是文档时）、`../09-content-guardrail`（叠加输出安全护栏）、`../10-reference-skeleton`（从零起骨架）
- 知识库超过几十份文档时，先用 skill `skill-knowledge-organizer` 做层级化，再套本模板的三层结构
