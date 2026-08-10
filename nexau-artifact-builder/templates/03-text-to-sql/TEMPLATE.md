# 模板：企业数据库问数 / Text-to-SQL（03-text-to-sql）

> 把「自然语言 → SQL → 结果解读」做成一个 Agent：**一张表一个 SKILL.md** 承载 schema/枚举/join 知识，**一个 `execute_sql` custom tool** 承载只读安全。
> 难度：🟡 Level 2 进阶 ｜ 来源：`nexau-cookbook/企业数据库问数/enterprise_data_agent`（tutorial-text-to-sql.md）

---

## 这个模板教你什么

1. **「一表一 Skill」的知识切分**：7 张表 = 7 个 `skills/<table>/SKILL.md`。模型按用户问题只加载用得上的那 1–3 张表的知识，而不是把整库 schema 灌进 system prompt。
2. **frontmatter 做路由、body 做知识**：`description` 始终在上下文里（决定"读不读"），Schema/枚举/示例 SQL 在 body（决定"怎么写对"）。含**负面路由**写法（`users` 表主动劝退）。
3. **SQL 安全写在 Python 里，不写在 prompt 里**：`custom_tools/execute_sql.py` 用 `file:...?mode=ro` 只读打开 + 首关键字白名单（只放行 `SELECT` / `WITH`）+ 注释剥离 + `set_progress_handler` 超时 + 行数/字节双重截断。prompt 里的"只允许 SELECT"只是给模型的提示，**真正的门在代码里**。
4. **`extra_kwargs` 注入「模型不可见」的连接参数**：`db_path` 由 agent.yaml 注入，不出现在 `input_schema.properties` 里 → 模型看不见也传不来。**代价是这个 tool.yaml 绝对不能写 `additionalProperties: false`**（本模板中招的 P0，已修，见「已知的坑」）。
5. **类型陷阱三点联动**：TEXT 存数字的列（`register_capital`），必须在 Schema 表 + 示例查询 + 注意事项**三处同时**提示 `CAST(... AS REAL)`。只写一处模型会忽略。
6. **窄数据原则**：默认只回 10 行 + `total_rows` / `truncated` / `warnings` 字段，让模型知道"还有更多"而不是把全表塞进上下文。

---

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 说明 / 替代 |
|---|---|---|
| 结构化库（SQLite/PG/MySQL）自然语言问数，schema 稳定、表数量 ≤ 几十 | ✅ 直接用 | 本模板的主场 |
| 库不能直连，只有一个「SQL 执行 HTTP 接口」 | ✅ 用，改 tool 实现 | 保留 skills/ 与 systemprompt，把 `execute_sql.py` 换成 HTTP 调用；写法见 `templates/02-rest-api-tool` |
| 上百张表 / schema 频繁变动 | ⚠️ 要改造 | 一表一 Skill 会撑爆路由。改成「按业务域分 Skill + references 二级索引」，见 `templates/10-reference-skeleton` 与 `skill-knowledge-organizer` |
| 问的是**非结构化文档**（政策/法规/合同） | ❌ | 用 `templates/01-agentic-rag` |
| 知识在外部向量库里 | ❌ | 用 `templates/06-external-vector-kb` |
| 需要写库（INSERT/UPDATE）或跑事务 | ❌ | 本模板从工具层就把写操作堵死了；写操作应做成**具名业务工具**（一个动作一个 tool），不要开放通用 SQL |
| 要出图表 / Excel 报表 | ⚠️ 组合 | 查询用本模板，产出用 `templates/07-doc-generation`（沙箱里 pandas/matplotlib 已预装） |

---

## 目录结构

```
03-text-to-sql/
├── nexau.json                        # 项目清单：agents 映射 → agent.yaml
├── agent.yaml                        # agent 定义：llm_config / tools / skills
├── systemprompt.md                   # 系统提示词：数据库概览 + 6 步工作流 + 约束
├── custom_tools/
│   └── execute_sql.py                # 【安全核心】只读 SQLite 执行器：白名单/超时/截断/诊断
├── tools/
│   ├── execute_sql.tool.yaml         # 给模型看的 execute_sql 签名（注意：无 additionalProperties）
│   ├── read_file.tool.yaml           # 内置 read_file 的 schema（cookbook 的精简版：只留文本读取，砍掉了图片/音视频/PDF 参数；要完整能力换 ../_builtin-tool-yamls/read_file.tool.yaml）
│   └── run_shell_command.tool.yaml   # 内置 run_shell_command 的 schema
└── skills/                           # 一表一 Skill —— 本模板的知识层
    ├── enterprise_basic/SKILL.md     # 主表（37 列）：schema + 枚举 + 示例 + 注意事项（最完整，抄它）
    ├── enterprise_contact/SKILL.md   # 联系人（简单表：只有 何时使用/Schema/示例）
    ├── enterprise_financing/SKILL.md # 融资上市（枚举值最丰富，抄"常见取值 → WHERE"映射写法）
    ├── enterprise_product/SKILL.md   # 产品与知识产权（含另一处 TEXT 存数字陷阱）
    ├── industry/SKILL.md             # 产业链树（parent_id + 物化路径 path，抄树结构说明写法）
    ├── industry_enterprise/SKILL.md  # 桥接表（三表 join 的关键，抄 join 引导写法）
    └── users/SKILL.md                # 平台账号（**负面路由范例**：主动劝退"用户"一词的误路由）
```

⚠️ **`enterprise.sqlite`（156 KB 示例库）已从模板裁剪**。模板开箱即跑不了，必须换成你自己的库，见下一节。

---

## 复制后必须改的地方

按编号顺序做，每一步都是必改（1–6 不做就跑不起来）。

| # | 文件:字段 | 改成什么 |
|---|---|---|
| 1 | **放入你的数据库文件** | 把 `xxx.sqlite` 放到制品根目录（与 `agent.yaml` 同级）。⚠️ 压缩包 ≤ 100 MiB，超了直接 413；库大就别塞制品，改走方案 B（下方「接自己的库」） |
| 2 | `agent.yaml:tools[execute_sql].extra_kwargs.db_path` | `/agent/<你的库文件名>.sqlite`。制品在 runtime 里解包到 `/agent`（`AGENT_PROJECT_DIR` 默认值），所以「制品根目录下的 X」= `/agent/X` |
| 3 | `skills/` 下 7 个目录 | **全删重写**：一张表一个目录，目录名 = 表名。目录 basename 决定运行时路径 `/home/user/.skills/<basename>`；`SKILL.md` frontmatter 的 `name` 决定 `LoadSkill` 用什么名字调用，两者可以不一致但建议保持一致 |
| 4 | `agent.yaml:skills[]` | 与第 3 步的目录一一对应，路径相对 agent.yaml 所在目录 |
| 5 | `systemprompt.md` 第 5–11 行「数据库」段 | 换成你的引擎、表清单、主关联键。**保留** `/home/user/.skills/` 那一行（平台静态校验器要求）和「先读 Skill 再写 SQL」那一段 |
| 6 | `systemprompt.md` 最后一条「测试数据」 | 描述的是 cookbook 的脱敏 mock 数据（`测试企业_N` / `MOCKCREDIT...`）。换成你的真实数据说明，或直接删掉 |
| 7 | `agent.yaml:name` / `description`、`nexau.json:agents` 的 key | 换成你的 agent 名（三处要一致） |
| 8 | `tools/execute_sql.tool.yaml:description` 最后两行 | 「该数据库为 SQLite 方言」「用 credit_code 做 JOIN」是本案例的业务事实，换成你的方言与主关联键 |
| 9 | `custom_tools/execute_sql.py:MAX_ROWS / MAX_OUTPUT_LENGTH / DEFAULT_TIMEOUT` | 默认 10 行 / 50 KB / 30 s。宽表建议降 `MAX_ROWS`，聚合为主可以调高 |
| 10 | `agent.yaml:tools[read_file, run_shell_command]` | 本案例其实用不上这两个内置工具（模型只需要 `execute_sql`）。**除非你要让模型在沙箱里做后处理（画图/导表），否则建议删掉这两条 + 对应 tool.yaml**，减少工具噪声 |

### 接自己的库：三种接法

| 接法 | 怎么改 | 什么时候选 |
|---|---|---|
| **A. SQLite 随制品打包**（模板现状） | 库文件放制品根，`db_path: /agent/<file>.sqlite` | 只读参考数据、体积小（≤ 几十 MB）、无需实时更新 |
| **B. 直连 PG / MySQL** | 重写 `execute_sql.py`：把 `sqlite3.connect(...mode=ro)` 换成 `psycopg2.connect(dsn)`；`extra_kwargs` 从 `db_path` 改成 `dsn: ${env.DB_DSN}`；**账号必须在 DB 侧就是只读**（`GRANT SELECT`），别只靠 Python 里的关键字白名单 | Agent 与 DB 同一可信网络 |
| **C. 走业务方的 SQL 执行 API** | `execute_sql.py` 改成 httpx POST；`extra_kwargs` 注入 `api_base` + `api_token: ${env.SQL_API_TOKEN}` | DB 不能直连 / 要走网关鉴权 / 多租户按用户切数据权限 |

⚠️ B 和 C 都要注入密钥：custom tool 跑在 **agent-runtime 进程**里，密钥必须配成 **runtime scope** 环境变量，`${env.X}` 才读得到。sandbox scope 的变量它读不到（那是给 `run_shell_command` 用的）。详见 `../../references/env-vars-and-secrets.md`。

---

## 关键设计要点

### 1. 为什么不把全库 schema 塞进 systemprompt

7 张表全塞进去 → 每轮对话都付这份 token，且无关表的枚举值会干扰模型。一表一 Skill 后：问"注册资本最高的企业"只加载 `enterprise_basic`，问"谁估值最高"只加载 `enterprise_financing`。**systemprompt 只留表清单和主关联键，细节全在 Skill body 里。**

### 2. `description` 是路由，不是知识

| 反模式 | 问题 | 改成 |
|---|---|---|
| `description: 企业基本信息` | 太笼统，模型不知道什么问题该来 | `当用户询问企业注册信息、地址、规模、行业分类或专精特新等级时使用` |
| `description: 融资表` | 纯标签，零路由信息 | 把用户可能的**各种说法**都列上：银行贷款/股权融资/估值/上市状态/融资需求 |
| 把 Schema 塞进 description | 浪费常驻 token | description 只放路由词，Schema 放 body |
| 没写 join 关系 | 模型不知道这张表和谁关联 | 末尾加一句 `通过 credit_code 关联 enterprise_basic` |
| 容易混淆的表没写"什么时候不该用" | `users` 被"用户"一词误路由 | **负面路由**：`此表与企业表无关。大多数关于"用户"的问题实际上指的是企业` |

### 3. 三点联动治类型陷阱

`register_capital` 是 TEXT 存数字，直接 `ORDER BY` 会得到 `"8000" > "50000"`（字符串序）。模板在**三处**同时提示：

- Schema 行内：`| register_capital | TEXT | 注册资本（万元）— **注意是 TEXT 类型**，需 CAST(... AS REAL) |`
- 示例查询里就用 `CAST(register_capital AS REAL) AS capital_wan` 排序
- 注意事项解释**为什么**：`直接 ORDER BY 得到错误结果（字符串序："8000" > "50000"）`

只写一处，模型会忽略。这个模式对**所有隐式类型/单位陷阱**都适用（金额单位、日期存字符串、布尔存 0/1）。

### 4. 枚举值必须给精确串，并映射用户说法

模型不知道数据库里"小巨人"的精确值，会猜 `= '小巨人'`（查不到）或 `LIKE '%小巨人%'`（多匹配）。Skill 里要写：

```
- zhuanjingtexin_level：专精特新中小企业 < 专精特新潜在"小巨人"企业 < 专精特新"小巨人"企业
  - NULL = 无认定
  - "小巨人企业"：WHERE zhuanjingtexin_level = '专精特新"小巨人"企业'
- listing_status：未上市 / 新三板 / 已上市 / 拟上市
  - "有上市计划的" = WHERE listing_status IN ('拟上市','已上市')
```

**格式统一是「用户可能的说法 → 对应的 WHERE 条件」。** 预判越全，写对概率越高。

### 5. 多表 join 必须手把手给完整 SQL

模型不会自己发现 `industry_enterprise` 是桥接表，会试图直接 join `industry` 和 `enterprise_basic`。所以三表 join 要在 Skill 里给出**完整可执行的 SQL**：

```sql
SELECT b.enterprise_name, i.name AS industry_node
FROM industry i
JOIN industry_enterprise ie ON ie.industry_id = i.id
JOIN enterprise_basic b ON b.credit_code = ie.credit_code
WHERE i.chain_id = 45 AND i.chain_position = 'up';
```

同时在每张表的「何时使用」末尾写跨表指引（`如需融资信息请查 enterprise_financing`），让模型加载完一个 Skill 后知道还要读哪个。

### 6. 安全在工具层，不在 prompt 层

把 Agent 当成**不受信任的外部调用者**授权。prompt 里写"只允许 SELECT"只是省一次往返，真正的门是：

| 层 | 本模板的实现 | 上生产要补 |
|---|---|---|
| 只读 | `sqlite3.connect("file:...?mode=ro", uri=True)` | PG/MySQL 用只读 role（`GRANT SELECT`），不是靠 Python |
| 语句白名单 | 剥注释后首关键字必须是 `SELECT`/`WITH`，且不得以 15 个危险关键字开头 | API 侧再校验一遍；限制可访问 schema/表 |
| 资源保护 | `set_progress_handler` 超时 + `fetchmany(max_rows+1)` + 代码里 clamp 到 `HARD_MAX_ROWS`/`HARD_TIMEOUT` + `MAX_OUTPUT_LENGTH` | DB 侧 `statement_timeout` |
| 敏感字段 | 无（示例数据已脱敏） | 用视图只暴露脱敏列，或直接不给 SELECT 权限 |
| 审计 | `logger.info("SQL executed: ...")` | DB 查询日志 / API 访问日志 |

⚠️ 注意关键字白名单只查**首个**关键字，`SELECT ... ; DROP TABLE x` 这种多语句在 `sqlite3.execute()` 下会被拒（它只执行单条），但换成别的驱动就未必——**换驱动时必须重新验证多语句行为**。

### 7. 迭代闭环：答错 → 改 Skill

| Agent 的错误 | 根因 | 改哪 |
|---|---|---|
| 没读该 Skill | description 没覆盖用户关键词 | description 加关键词 |
| 类型处理错 | 只在一处提了 CAST | Schema + 示例 + 注意事项三处补齐 |
| 枚举值写错 | 模型在猜值 | 「常见取值」补精确串 |
| join 写错 | 不知道表间关系 | Schema 标 FK + 示例给完整 join SQL |
| 用错表 | 表名/语义相近 | description 加负面路由 |
| SQL 跑通但结果不对 | 缺业务过滤条件 | 「注意事项」补过滤规则 |

---

## 已知的坑

### ⚠️ P0：`extra_kwargs` × `additionalProperties: false` 互斥（cookbook 原版中招，本模板已修）

框架在调用工具前会把 `extra_kwargs` 并进参数（等价于 `{**extra_kwargs, **params}`），然后拿这份合并结果去做 jsonschema 校验；校验前**只剔除**四个注入参数（`agent_state` / `global_storage` / `sandbox` / `ctx`），**不剔除 `extra_kwargs`** → `db_path` 原样进了校验。schema 又写了 `additionalProperties: false` 且 properties 里没有 `db_path` →

```
ValueError: Invalid parameters for tool 'execute_sql': Additional properties are not allowed ('db_path' was unexpected)
```

**每次调用必炸。** 修法：删掉这个 tool.yaml 里的 `additionalProperties: false`。
❌ 不要把 `db_path` 补进 `properties` —— 那样模型就能看见并覆盖它（`{**extra_kwargs, **params}` 里 params 优先）。
✅ 判据只有一条：**这个工具有没有 `extra_kwargs`**。`read_file` / `run_shell_command` 没有 extra_kwargs，它们的 `additionalProperties: false` 保留是安全的。

### ⚠️ 行数 / 超时闸门以代码里的 `HARD_*` 为准，schema 的 `maximum` 只是给模型看的提示

`max_rows` / `timeout` 是模型可传的参数，`tool.yaml` 里的 `maximum: 1000` / `maximum: 300` 只是提示——jsonschema 校验确实会拦住越界值，但**别把它当唯一防线**（换 formatter、放宽 schema、或直接被别的调用方复用时就没了）。真正的闸门在 `execute_sql.py` 顶部：`HARD_MAX_ROWS = 1000` / `HARD_TIMEOUT = 300`，函数入口 `max(1, min(int(...), HARD_*))` 无条件 clamp。改上限时**两处一起改**，别只改 schema。

同理，取数用 `cursor.fetchmany(max_rows + 1)` 而不是 `fetchall()`：Text-to-SQL 场景模型最容易写出 `SELECT * FROM 大表`，`fetchall()` 会先把全表读进内存，之后再截断已经晚了（`MAX_OUTPUT_LENGTH` 那道兜底救不了内存）。代价是**截断时拿不到全表行数**，所以 `total_rows` 会返回 `">=N"`，需要精确总数请让模型另跑一次 `COUNT(*)`。

### ⚠️ 库文件不在制品里 → 每次查询都返回 "Database file not found"

`db_path` 写错（比如写成相对路径 `./enterprise.sqlite`）不会在部署期报错，只在**每次调用**返回 error dict。`execute_sql.py` 会把 cwd、cwd 下的文件、以及在 `/agent` `/app` `/workspace` `/artifacts` 下搜到的 `*.sqlite*` 候选放进 **`returnDisplay`**——**先看这段排障信息再改 db_path**，别猜。

注意这段信息**只给人看**：`returnDisplay` 会被默认 markdown formatter 剥掉、不进模型上下文（见 `../../references/custom-tools.md` §6）。路径清单和目录列表对模型没有用，塞进顶层键只会烧 token 并把宿主机目录结构喂给模型——这正是「窄数据原则」要拦的。扫描本身也有闸门：只扫上面 5 个根、最多 20 条候选、超过 2 秒即停（截断时 `returnDisplay` 会注明）。

### ⚠️ 打包硬约束

- 压缩包 ≤ 100 MiB，超限上传返回 **413**。SQLite 库大就别随包走，改直连（接法 B/C）。
- 归档里**只允许普通文件和目录**：含任何符号链接 → **400 失败**。别用 `ln -s` 指向外部的库文件。
- 必须含 `nexau.json`。

### ⚠️ `${env.LLM_MODEL}` 在没有可见模型卡的项目里会硬失败

`${env.X}` 在**加载期**对整个 agent.yaml 文本做正则替换（`yaml.safe_load` 之前，连注释里的 `${env.X}` 也会被解析），未设置 = `ConfigError` 硬失败，不支持默认值语法。项目一张可见模型卡都没有时 `LLM_MODEL` 不会被注入 → agent 加载即挂。要么先给项目授权模型卡，要么把 `model` 写成钉死的全键（`provider/model_name`）。

### ⚠️ 模型把 SQL 也念给用户

systemprompt 已写「不要在回答中输出 SQL 语句」。删这条约束会让回答变成 SQL 教学。如果你的用户是数据分析师、**想看 SQL**，把这条改成「在结论之后附上使用的 SQL」。

### ✅ 本模板已通过平台静态校验器（`pass: true`，0 error）

拿平台的制品静态校验器跑本目录：`pass: true`。历史上曾剩的两条 error 已修：

| 曾经的 error code | 原状（cookbook 原版） | 已改成 |
|---|---|---|
| `agent.field.invalid` | `agent.yaml:system_prompt_type: file` | `jinja`（改前已确认 `systemprompt.md` 里没有会被 Jinja 吃掉的 `{{ }}` / `{% %}`） |
| `middlewares.invalid_type` | `agent.yaml` 根本没有 `middlewares` 键 | 显式写 `middlewares: []`；要挂中间件按 `01-agentic-rag` 的 `ContextCompactionMiddleware` 写法加 |

两条**本来都不影响运行**（框架接受 `system_prompt_type: file`，`middlewares` 也可缺省），改动纯粹是为了让制品自检零 error；`system_prompt_type: jinja` 对本模板是行为等价的（无模板语法可渲染）。
`systemprompt.md` 里那句 `/home/user/.skills/` 也是为过同一个校验器加的。

复制本模板改造后**若引入自己的中间件**，注意平台白名单（`allowed-middlewares.json`）目前只放行 `ContextCompactionMiddleware` 与 `LongToolOutputMiddleware`，且后者不接受任何 `params`；挂别的会报 `middleware.not_allowed` / `middleware.params.unexpected`。⚠️ **这不是「规范滞后于框架能力、可以无视」**——`artifact-hard-rules.md` §5.1 明写「middleware 不允许自由创新，只能从模板允许项中复制」，白名单窄是平台**有意收窄**。框架能跑 ≠ 平台允许交付：偏离规范需自负后果，上线前与平台确认或走白名单收录流程。详见 `../../references/artifact-spec-checklist.md` §9.3。本模板不挂任何中间件，因此不触发这两条。

### ⚠️ 一表一 Skill 的规模上限

表数量上到几十张后，常驻的 description 本身就开始占可观 token，且路由准确率下降。此时改成「按业务域聚一个 Skill + Skill 内 references 二级索引」，参见 `skill-knowledge-organizer` skill。

---

## 本模板相对 cookbook 原版的改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `tools/execute_sql.tool.yaml` | **删除 `additionalProperties: false`**，替换成解释性注释 | P0：该工具配了 `extra_kwargs.db_path`，框架会把它一并送进 jsonschema 校验，原版**每次调用必抛 ValueError**，按原样部署全线失败 |
| `agent.yaml` | `llm_config` 删掉 `base_url` / `api_key` / `api_type` / `stream`，只留 `model` + `temperature`；加注释说明**本地裸跑 NexAU 时需自行补 base_url / api_key** | 这四项在 NAC 上写了没用：`base_url`/`api_key` 被平台运行期无条件覆盖，`api_type` 被模型卡派生值覆盖，`stream` 在流式路径被强制 True。留着是噪声，且 `api_key` 写字面量会被平台静态校验判 error |
| `agent.yaml` | `extra_kwargs.db_path` 上方加注释：`/agent` = 制品解包根目录（运行时的默认制品目录），并提示模板未附带示例库 | 裁掉示例库后，`/agent/enterprise.sqlite` 这个值必须解释清楚来源，否则复制者不知道该改成什么 |
| `systemprompt.md` | 新增一行：skills 根目录位于 `/home/user/.skills/`，并说明以 `LoadSkill` 返回的 `<SkillFolder>` 为准 | 平台静态校验器（`builder-static-rules.json:required_systemprompt_patterns`）要求 systemprompt 显式写出这个根目录；原版没写 |
| `custom_tools/execute_sql.py` | `search_roots` 里补上 `Path("/agent")` | 诊断分支原本搜 `/app` `/workspace` `/artifacts` `/tmp`，**唯独漏了 NAC 上真正的制品根目录 `/agent`** → 库找不到时给不出有用候选，误导排查 |
| `enterprise.sqlite`（156 KB） | **已裁剪，未随模板附带** | 模板不携带示例数据。要跑通 cookbook 原样例请到 `nexau-cookbook/企业数据库问数/enterprise_data_agent/enterprise.sqlite` 取；正常用法是换成你自己的库（见「接自己的库」） |
| `custom_tools/__pycache__/` | **已删除**（交叉复核轮补的） | 上一轮跑过 `execute_sql.py` 留下的 `.pyc`，是构建垃圾不是模板内容；`nexau.json:excluded` 里虽写了 `__pycache__/` 但**平台不解析该字段**，照抄打包就会把它塞进制品 |
| `agent.yaml` | `system_prompt_type: file` → **`jinja`**，并加一行注释说明本 systemprompt 无 `{{ }}` / `{% %}` | 平台静态校验器把该字段钉死为 `jinja`（`builder-static-rules.json`），原版的 `file` 报 `agent.field.invalid`。本模板 systemprompt 无模板语法，改后行为等价 |
| `agent.yaml` | 新增 **`middlewares: []`**（含注释指向 `01-agentic-rag` 的中间件写法） | 原版根本没有 `middlewares` 键 → 校验器报 `middlewares.invalid_type`（要求该键存在且为 list）。空 list 与"缺省"运行时等价，只是把契约写显式 |
| `custom_tools/__pycache__/` | **再次删除**（本轮） | 上一轮删除后又被重新生成的 `execute_sql.cpython-312.pyc`；同上，属构建垃圾 |

**逐字保留未改**的部分：7 个 `SKILL.md`（知识层是本模板的精华，一字未动）、`nexau.json`（含平台并不解析的 `excluded` 字段——它只是打包端约定，保留无害）、`read_file` / `run_shell_command` 两个内置工具 yaml（无 extra_kwargs，`additionalProperties: false` 保留是安全的）、`execute_sql.py` 的安全逻辑与截断逻辑、`systemprompt.md` 的六步工作流。

---

## 延伸

| 想深入 | 去哪 |
|---|---|
| `extra_kwargs` 机制、保留注入参数名、返回值/异常语义、路径基准、可用依赖 | `../../references/custom-tools.md`（§4 就是本模板的 P0） |
| `llm_config` 每个字段在 NAC 上的真实命运、`model` 三种写法 | `../../references/llm-config.md` |
| `${env.X}` 语义、runtime scope vs sandbox scope 两条互不可见的密钥通路 | `../../references/env-vars-and-secrets.md` |
| 内置工具清单与它们的 tool.yaml 原件 | `../../references/builtin-tools.md`、`../_builtin-tool-yamls/` |
| agent.yaml 全字段契约与校验强度分层 | `../../references/agent-yaml-fields.md` |
| 把 Skill 当**文档知识库**用（而不是数据库说明书） | `../01-agentic-rag`（劳动法问答） |
| 把 SQL 换成 HTTP API | `../02-rest-api-tool` |
| 查询结果出报表 / 图表 | `../07-doc-generation` |
| 大规模知识库的分层与索引 | skill `skill-knowledge-organizer` |
