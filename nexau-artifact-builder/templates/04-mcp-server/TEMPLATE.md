# 模板：外部 MCP Server 接入（04-mcp-server）

> 把「数据库 / 外部系统」的能力做成一个**独立部署的 HTTP MCP server**，Agent 制品里一行工具都不注册，只写 `mcp_servers` 连过去，工具 schema 在启动时自动发现。
> 难度 Level 2（进阶）· 来源：nexau-cookbook《数据库 MCP 接入》(`tutorial-database-mcp.md`)

---

## 这个模板教你什么

1. **`mcp_servers` 的完整可跑配置**：`type: http` + `url` + `headers` + `timeout`，以及三个 type（`stdio` / `http` / `sse`）的校验规则。
2. **MCP 工具名会被强制加前缀** `mcp__<server_name>__<tool>`（无条件，没有开关）——systemprompt 必须按前缀名写，否则模型会以为工具不存在。
3. **MCP client 跑在 agent-runtime 进程里，不是沙箱里**——网络可达性、DNS、出网白名单全部要按 **runtime pod** 排查，`host.docker.internal` 的局限也源于此。
4. **只读边界必须在 server 侧强制**（三层：SQL 前缀白名单 + 危险关键字黑名单 + 驱动层 `mode=ro` / 数据库只读账号），prompt 只是提示不是安全边界。
5. **同一份 Agent 制品换后端零改动**：`sqlite_mcp_server` 与 `dm8_mcp_server` 工具契约完全一致，方言差异靠 `server_info()` 运行时自述（`limit_syntax`），不靠改 agent.yaml。
6. **DNS rebinding 防护 → 必须显式给 `Host` header**：FastMCP 的 `TransportSecuritySettings(allowed_hosts=...)` 会按 `Host` 头拒绝请求，用 `host.docker.internal` 之类的地址连过去时 Host 必须伪装成白名单里的值。

---

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 替代 |
|---|---|---|
| 数据库能力要被**多个 Agent / 多个客户端**复用 | ✅ 用 | — |
| 数据库凭证不能进制品包，必须收在服务端 | ✅ 用 | — |
| 已经有现成的第三方 MCP server（内部平台 / 厂商提供） | ✅ 用（只改 `url` + `headers`） | — |
| 只有一个 Agent 查一个库，且愿意让 runtime 直连 DB | ❌ 太重 | `03-text-to-sql`（custom_tools 直连） |
| 要调的是普通 REST / HTTP API，没有 MCP 协议 | ❌ | `02-rest-api-tool` |
| 目标环境完全离线、装不了额外服务进程 | ❌ | `05-native-driver-airgap` |
| 只是想检索文档 / 知识库 | ❌ | `01-agentic-rag` / `06-external-vector-kb` |

---

## 目录结构

```text
04-mcp-server/
├── TEMPLATE.md                     ← 本文
├── db_mcp_agent/                   ← 唯一要打包上传 NAC 的目录
│   ├── nexau.json                  ← 只声明 agents 映射（无 setup / 无沙箱依赖）
│   ├── agent.yaml                  ← 核心：mcp_servers 一段就是全部工具来源
│   └── systemprompt.md             ← 表结构 + join key + SQL 模板 + 输出格式，全部内联
├── sqlite_mcp_server/              ← 可跑的 MCP server 参考实现（零外部依赖，教学/本机调试首选）
│   ├── server.py                   ← FastMCP + sqlite3；三层只读防护 + DNS rebinding 防护
│   ├── init_db.py                  ← 读 ../_shared_schema/schema_seed.sql 建库灌数据
│   ├── start.sh                    ← 一键：uv sync → init_db → 起 server（`-d` 后台）
│   └── pyproject.toml
├── dm8_mcp_server/                 ← 生产形态参考实现（达梦，Linux only）
│   ├── server.py                   ← dmPython TCP 连接串 + dmssl 软链 workaround
│   ├── start.sh                    ← 校验 DM8_CONN_STR / macOS 提前 exit 3
│   ├── pyproject.toml
│   └── .gitignore
└── _shared_schema/
    └── schema_seed.sql             ← 3 张演示表（企业 / 年度指标 / 政策扶持），DM8 与 SQLite 共用
```

⚠️ **只打包 `db_mcp_agent/`**。MCP server 代码、`_shared_schema/`、`*.sqlite` 一律不进制品包——它们是独立部署的服务与数据，不是 Agent 的一部分。

---

## 复制后必须改的地方

编号即执行顺序。**1 和 2 不改，部署上去 100% 不可用。**

| # | 文件:字段 | 改成什么 |
|---|---|---|
| 1 | `db_mcp_agent/agent.yaml:url` | 改成 **agent-runtime pod 能解析并连通**的地址。默认值 `http://host.docker.internal:8000/mcp` 只适用于本机调试，任何真实集群都解析不到。<br>同集群：`http://<svc>.<ns>.svc.cluster.local:8000/mcp`<br>内网：`http://10.x.x.x:8000/mcp`<br>公网：`https://mcp.your-domain.com/mcp` |
| 2 | `db_mcp_agent/agent.yaml:headers.Host` | 换成正规域名 / svc 地址后**直接删掉这一行**。它只是为了骗过本机 server 的 DNS rebinding 白名单；留着会让请求带上错误的 Host 头，反而被真实网关/server 拒。 |
| 3 | `db_mcp_agent/agent.yaml:mcp_servers[0].name` | 改成你的业务名（如 `crm_db`）。⚠️ 改完必须同步改 `systemprompt.md`「可用工具」段里的 `mcp__enterprise_ops_db__*` 前缀，前缀就是这个 name。 |
| 4 | `db_mcp_agent/agent.yaml:headers` 加鉴权（公网必做） | 在 `headers:` 下加一行真实配置（不是注释）：`Authorization: Bearer ${env.MCP_TOKEN}`。**顺序不能反**——必须先把 `MCP_TOKEN` 建成 runtime scope 环境变量并重新部署，否则加载期 `ConfigError`。见「已知的坑 · 坑 1」。 |
| 5 | `db_mcp_agent/systemprompt.md` §数据库表结构 | 全量替换成你的真实表 / 字段 / 单位 / join key。模型不会去猜，写错这段等于问数全错。 |
| 6 | `db_mcp_agent/systemprompt.md` §常见 SQL 模板 | 换成你库的方言与真实表名；保留「先调 `server_info` 看 `limit_syntax` 再决定 `LIMIT` 还是 `FETCH FIRST`」这条规则。 |
| 7 | `db_mcp_agent/agent.yaml:name` / `description`、`nexau.json:agents` 的 key | 三处同步改成你的 agent 名（`nexau.json` 的 key 必须与 `agent.yaml:name` 一致）。 |
| 8 | `sqlite_mcp_server/server.py:MAX_ROWS`（默认 200）/ `dm8_mcp_server/server.py:DEFAULT_MAX_ROWS`(200)/`HARD_MAX_ROWS`(1000) | 按你的结果集体量调；**别调到几千**，MCP 返回值整段进上下文。 |
| 9 | `_shared_schema/schema_seed.sql` | 用自己的库就整份删掉，别灌演示数据到生产库。 |
| 10 | `db_mcp_agent/agent.yaml:llm_config.model` | 默认 `${env.LLM_MODEL}`（跟随项目默认模型）。要钉死某张模型卡就写全键 `provider/model_name`。⚠️ 项目里一张可见模型卡都没有时 `LLM_MODEL` 不会被注入，agent 加载期直接 ConfigError。 |

部署前自检（两条命令，别跳）：

```bash
# 本地/可达网络：确认 server 活着
curl -sI -m 5 <your-mcp-url>     # 期望 405（HEAD 不允许但活着）或 200

```

⚠️ **本机 curl 通 ≠ Agent 那边通**。Agent 跑在平台的运行环境里，出口和 DNS 都和你本机不同——
内网地址、`localhost`、只对你办公网开放的域名，在那边多半解析不到。

**没有集群权限时怎么验**（推荐，这也是绝大多数使用者的情况）：部署后在 Playground 里
提一句必然触发该 MCP 工具的话，让 Agent 真调一次，然后看返回：

| 你看到 | 说明 |
|---|---|
| 工具正常返回结果 | 连通性没问题 |
| 报 DNS 解析失败 / 名称无法解析 | 平台侧解析不到这个域名，换公网可达地址，或联系平台方确认网络策略 |
| 报连接超时 / 拒绝 | 域名解析到了但连不上，多半是防火墙或出网策略 |

⇒ 后两种**不是你改制品能解决的**，带上 MCP 地址、报错原文、发生时间联系平台方。

（如果你恰好是私有化部署、手上有集群权限，也可以直接进运行环境验 DNS 与连通性，比上面快。）

---

## 关键设计要点

### 1. MCP server 是「数据库边界」，不是「一层转发」

```text
Agent → NexAU MCP client（agent-runtime 进程内）→ 外部 HTTP MCP server → 数据库
```

收益全部落在中间那一层：**凭证 / 连接池 / 只读账号 / SQL 白名单 / 审计** 都在 server 侧；换 DM8 → PostgreSQL → 数仓时 Agent 侧只改 `url`。反例：把 `execute_sql` 写成 custom_tool 直连 DB —— 凭证进 runtime pod、每个 Agent 各写一份、换库要改所有制品。

### 2. 工具要**少而稳定**，四个就够

| 工具 | 作用 | 为什么不能省 |
|---|---|---|
| `server_info` | 返回 `backend` / `read_only` / `limit_syntax` / `default_max_rows` | 让**同一份 systemprompt 同时适配 DM8 与 SQLite**：方言在运行时自述，不写死在 prompt 里 |
| `list_tables` | 只返回表名列表 | 表名与字段分两步取，避免一次性灌爆上下文 |
| `describe_table` | 单表字段/类型/可空 | 阻止模型猜字段名 |
| `query_sql` | 执行单条只读 SQL | 唯一的数据出口，所有校验都挂在这里 |

tutorial 的原话值得抄进你自己的 server：数据库 Agent 最容易出问题的不是「工具不够」，而是**工具边界过宽、输出太散、模型不知道用哪个**。

### 3. 只读**必须**写在 server 里 —— 看 `sqlite_mcp_server/server.py` 的三层

| 层 | 代码位置 | 拦什么 |
|---|---|---|
| ① 前缀白名单 | `_READONLY_PREFIX = ^\s*(SELECT|WITH)` | 非查询语句 |
| ② 关键字黑名单 | `_BANNED`（含 `ATTACH` / `DETACH` / `PRAGMA` / `REINDEX`） | 绕过前缀的写操作 |
| ③ 驱动层 | `sqlite3.connect("file:...?mode=ro", uri=True)` | ①②被绕过后的最终防线 |
| ④ 单语句 | `if ";" in statement` | SQL 注入式串联 |
| ⑤ 行数上限 | `fetchmany(row_limit + 1)` + `(truncated to N rows)` | 结果集撑爆上下文 |

DM8 版额外做了**注释剥离 + 引号内容置空后再校验**（`_validation_view()`）——防的是 `SELECT 1 /* DROP TABLE x */` 这类把危险词藏进注释/字符串里骗过朴素正则的写法。生产环境这四层之上**仍然要叠数据库只读账号**，它才是最后一道。

### 4. 方言差异不进 prompt，进 `server_info`

systemprompt 里写的是规则而不是结论：

> 限制行数：先看 `server_info` 返回的 `limit_syntax`。DM8 用 `FETCH FIRST N ROWS ONLY`，SQLite / MySQL / PostgreSQL 用 `LIMIT N`。

这样换后端时 systemprompt 一个字不用改。

---

## 已知的坑

### ⚠️ 坑 1（P0，会让 agent **加载期直接失败**）：注释里的 `${env.X}` 也会被解析

cookbook 原版 `agent.yaml` 在 headers 下留了一行注释样例 `# 公网部署加: Authorization: Bearer ${env.MCP_TOKEN}`。

`${env.X}` 的替换发生在 **`yaml.safe_load` 之前，对整份文件原文做正则替换**，**注释不豁免**；变量没设置直接 `ConfigError: Environment variable 'MCP_TOKEN' is not set`。也就是说那行「无害的注释」会让整个 agent 起不来。

- 修法：本模板已删掉该注释样例，改成纯文字说明。
- 你要启用鉴权时：**先建 runtime scope 的 `MCP_TOKEN` 并重新部署**，再往 `headers` 里加真正的 `Authorization: Bearer ${env.MCP_TOKEN}`（真实一行，不是注释）。
- 同理：任何被你「注释掉」的配置，只要里面还有 `${env.…}`，都必须**真删**。
- 详见 `../../references/env-vars-and-secrets.md` §2。

### ⚠️ 坑 2：`host.docker.internal` 在真实集群解析不到，而且失败会被**静默吞掉**

DNS 解析失败（`Name or service not known`）会被当成 **tool 调用结果回灌给 LLM**，模型于是编一句「数据库查询未返回结果」交差 —— 你在 Playground 看到的是**业务话术，不是报错**。排查时不要信最终回答，去看 trace 里 `mcp__*` 工具的原始返回。

⚠️ 另一半事实：`host.docker.internal` 是 **Docker 容器**的特殊 DNS，**K8s Pod 里默认不一定有**。本机 Docker Desktop K8s 上能不能通取决于集群配置，**部署前务必在 agent-runtime pod 里 `getent hosts host.docker.internal` 实测一次**，不要默认它可用。

### ⚠️ 坑 3：MCP 工具名带 `mcp__<server>__` 前缀

框架在装载 MCP 工具时**无条件**把工具名重写成 `mcp__{server_name}__{tool_name}`，没有任何开关或分支。tutorial 说「不同运行时版本可能直接显示原始工具名」——实测不存在这种情形，前缀是确定的。改了 `mcp_servers[*].name` 就要同步改 systemprompt 里的前缀。

### ⚠️ 坑 4：`Host` header 是「本机调试专用的欺骗」，不是通用配置

`sqlite_mcp_server` 开了 `enable_dns_rebinding_protection=True`，白名单默认 `localhost:*,127.0.0.1:*`；你用 `host.docker.internal:8000` 连过去，Host 头默认就是 `host.docker.internal:8000`，**会被 server 拒**——所以模板里硬写了 `Host: localhost:8000`。
换到正规地址后必须删掉这行；或者改 server 的 `MCP_ALLOWED_HOSTS` 环境变量把真实域名加白。
注意 `dm8_mcp_server` **没有**配 `transport_security`，那条路径不需要这个 header。

### ⚠️ 坑 5：改了 `MCP_PORT` 就要改三处

`start.sh` 的 `MCP_PORT` 只影响 server 监听端口。agent 侧 `url` **和** `headers.Host`（`localhost:8000` 里的端口）都要跟着改，漏一个就 403 / 连不上。

### ⚠️ 坑 6：dmPython 的 `[CODE:-70089] Encryption module failed to load`

dmPython 2.5.x 的 wheel 把 `libssl/libcrypto` 装在 `site-packages/dmssl/`，但 dlopen 只搜 `dmpython.libs/`。`dm8_mcp_server/server.py:_preload_dmssl_libs()` 在 `dmpython.libs/` 下补软链（含 `-3.so` 别名）解决。**这段必须在 `import dmPython` 之前跑**，顺序不能调（文件里有 `# noqa: E402` 标注）。

### ⚠️ 坑 7：dmPython 只有 Linux wheel

macOS 上 `uv sync` 必失败，`dm8_mcp_server/start.sh` 会提前 `exit 3`。Mac 本地教学一律走 `sqlite_mcp_server`；要验真实 DM8 链路请 SSH 到 Linux 主机。

### ⚠️ 坑 8：cookbook 原版这四条过不了平台静态校验器（**本模板已全部修掉**）

「零工具注册、全靠 MCP」是这个场景的卖点，但它恰好踩中官方制品规范的四条硬要求。
拿平台的制品静态校验器实测 cookbook 原版的 `db_mcp_agent/`，四条 error：

| error code | cookbook 原版现状 | 本模板已如何修 |
|---|---|---|
| `agent.system_prompt.required_pattern_missing` | systemprompt 没写「skills 根目录位于 `/home/user/.skills/`」 | `db_mcp_agent/systemprompt.md:10`（「## 运行环境」段）补了这句。校验器**无条件**要它，哪怕一个 skill 都没挂 |
| `tools.invalid_type` | 没有 `tools` 键（工具全部来自 `mcp_servers` 自动发现） | `db_mcp_agent/agent.yaml:24` 显式写 `tools: []` |
| `skills.invalid_type` | 没有 `skills` 键 | `db_mcp_agent/agent.yaml:25` 显式写 `skills: []` |
| `middlewares.invalid_type` | 没有 `middlewares` 键 | `db_mcp_agent/agent.yaml:26` 显式写 `middlewares: []` |

这四条**不影响运行**（这些字段在框架里都可缺省），但它们是官方制品规范的一部分，
**从 cookbook 自己搬制品时要照上表补齐**，不要以为「能跑就行」。

### ⚠️ 坑 9：可达性要在 **agent-runtime pod** 里验，不是沙箱

cookbook 自查清单写的是「NAC 沙箱是否能访问 `mcp_servers.url`」——**错的**。MCP client 是 `agent-runtime` 进程内的 httpx 客户端，跟沙箱没有任何关系。网络策略、出网白名单、DNS 都要针对 runtime pod 配。

---

## 本模板相对 cookbook 原版的改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `db_mcp_agent/agent.yaml` | 删除 headers 注释里的 `${env.MCP_TOKEN}` 字面量，改为纯文字说明 + 指向 TEMPLATE.md | **P0**：`${env.X}` 在 `yaml.safe_load` 前对整份原文替换，注释不豁免；变量没配 → 加载期 `ConfigError`，agent 直接起不来 |
| `db_mcp_agent/agent.yaml` | `llm_config` 删 `stream: false` 与 `api_type: openai_chat_completion`，补 `model: ${env.LLM_MODEL}` | NAC 上 `base_url`/`api_key` 与 `api_type` 都被平台运行期无条件覆盖，`stream` 在流式路径被强制 True——写了是噪声；收敛成「model + 业务采样参数」的推荐最小写法 |
| `db_mcp_agent/agent.yaml` | `llm_config` 上方加注释：本地裸跑 NexAU 需自行补 `base_url` / `api_key` | 收敛后脱离 NAC 就没有连接信息了，必须提示 |
| `db_mcp_agent/agent.yaml` | `url` 上方注释「NAC 沙箱可达」→「NAC runtime 可达」 | MCP client 跑在 agent-runtime 进程内，与沙箱无关；写成沙箱会把排查方向带偏 |
| `db_mcp_agent/agent.yaml` | `Host` 注释补上「sqlite_mcp_server 开了 DNS rebinding 防护」 | 原注释说「MCP server 的防护」，但 `dm8_mcp_server` 并没配 `transport_security`，笼统说法会误导 |
| `db_mcp_agent/agent.yaml` | 注释里的 `../tutorial-database-mcp.md` 指向改为 TEMPLATE.md | tutorial 已不在模板目录内 |
| `db_mcp_agent/systemprompt.md` | 新增「## 可用工具」段，写明实际工具名是 `mcp__enterprise_ops_db__*` | 框架无条件给 MCP 工具名加前缀；prompt 里只写短名会让模型误判工具不存在 |
| `sqlite_mcp_server/uv.lock`、`dm8_mcp_server/uv.lock` | **已裁剪** | 体积大且随依赖版本漂移；`start.sh` 走的是 `uv sync`（非 `--frozen`），缺 lock 会重新解析，不影响可跑性。需要精确复现原始依赖版本时去 cookbook 原始目录取 |
| `tutorial-database-mcp.md` | **已裁剪**（内容已提炼进本文「关键设计要点」/「已知的坑」） | 模板目录只留可直接复制的制品与参考实现 |
| `db_mcp_agent/agent.yaml` | 显式补上 `tools: []` / `skills: []` / `middlewares: []` 三个空键 | 平台官方制品规范 `required_list_fields` 要求这三个键必须存在（缺键报 `tools.invalid_type` 等）。本 Agent 能力全来自 MCP，确实一个都不挂，但键要写出来 |
| `db_mcp_agent/systemprompt.md` | 新增「## 运行环境」段，写明 skills 根目录位于 `/home/user/.skills/` + 以 LoadSkill 返回值为准 | 规范 `required_systemprompt_patterns` 正则硬检查这句话，缺了报 `agent.system_prompt.required_pattern_missing` |
| 其余全部文件 | **逐字未改** | 两份 server.py、init_db.py、start.sh、pyproject.toml、schema_seed.sql、nexau.json、systemprompt.md 其余段落均与 cookbook 原版一致 |

> ✅ **本模板已通过平台官方静态校验器**（制品根 = `db_mcp_agent/`，`pass: true`，0 errors）。
> 复验命令见 `../../references/artifact-spec-checklist.md` 顶部。

### 待确认（未改动，留给使用者判断）

- `nexau.json` 里的 `"excluded"` 字段**平台完全不解析**，只是打包端约定。留着无害（不影响加载），但别指望平台按它排除文件——打包时该 `zip -x` 还得自己写。
- `db_mcp_agent/agent.yaml` 的 `max_iterations: 80` / `max_context_tokens: 128000` 沿用 cookbook 取值，未按现网模型窗口重估。
- `dm8_mcp_server/server.py` 的 `describe_table` 用字符串拼 SQL（只做了 `'` 转义 + `upper()`），非参数化。cookbook 教学量级可接受，接生产库前建议改成绑定参数。
- `EXEC_TIMEOUT_SEC = 30` 在 `dm8_mcp_server/server.py` 里定义了但**未被引用**（无查询超时保护），保留原样未动。

---

## 延伸

- 环境变量 / 密钥三条通路、`${env.X}` 的完整语义与注释陷阱 → `../../references/env-vars-and-secrets.md`
- `llm_config` 各字段在 NAC 上的真实命运 → `../../references/llm-config.md`
- `agent.yaml` 全字段与校验强度 → `../../references/agent-yaml-fields.md`
- 打包硬约束（≤100 MiB、禁符号链接、必须含 `nexau.json`）→ `../../references/nexau-json-and-packaging.md`
- 同一个问数场景但**不走 MCP**（custom_tools 直连 DB）→ 模板 `03-text-to-sql`
- 调普通 REST API 而非 MCP → 模板 `02-rest-api-tool`
- 完整字段骨架参考 → 模板 `10-reference-skeleton`
