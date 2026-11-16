# MCP servers 与 sub_agents

本文覆盖 agent.yaml 顶层两个块的完整契约：`mcp_servers:`（把外部服务/数据库接进 Agent 的一等公民路径）和 `sub_agents:`（拆子代理 + 随之自动注入的 `Agent` / `LoadSkill` / `ToolSearch` 三个工具 + `stop_tools` 陷阱）。**当制品需要访问外部 HTTP 服务 / 数据库 / 已有 MCP server，或需要把长流程拆成多个角色时读它。** 只做纯对话或只用内置工具 + skills 的制品不需要读。

相关但不在本文：自定义 Python 工具的进程边界与 `extra_kwargs` → `references/custom-tools.md`；内置工具清单与 `.tool.yaml` 来源 → `references/builtin-tools.md`；顶层字段全集与校验强度分层 → `references/agent-yaml-fields.md`。

本文描述的行为对应 NAC agent-runtime 镜像内置的那份 NexAU SDK（版本号未核，见 SKILL.md 开头）。

---

## 一、外部服务集成：三条路怎么选

| 路径 | 代码在哪跑 | 工具 schema 从哪来 | 适用 | 主要代价 |
|---|---|---|---|---|
| **MCP server（http/sse）** | 独立进程/独立服务，Agent 只发 RPC | server 初始化时返回，**不用你写 `.tool.yaml`** | 数据库问数、已有 MCP 生态、需要独立于制品运维/升级的服务 | 多一套部署物；网络不通时静默降级（见 §三） |
| **MCP server（stdio）** | **agent-runtime 容器内**的子进程 | 同上 | 现成的 stdio MCP 包，且二进制/依赖能装进 runtime 镜像 | 依赖必须随制品 `setup` 装好；不在沙箱里，读不到沙箱文件 |
| **custom tool** | agent-runtime 进程内（同进程函数调用） | 你自己写 `.tool.yaml` | 薄封装、只需几个函数、想复用制品里打包的静态资源 | schema 和实现两边手工同步；见 `references/custom-tools.md` |
| **CLI 脚本 + Skill** | **沙箱内**（经 `run_shell_command`） | 无 schema，靠 SKILL.md 教模型怎么调 | 需要沙箱文件系统、需要长命令、产物落在沙箱 | 无结构化参数校验；密钥要走 sandbox scope 环境变量 |

选型口诀：**要结构化参数 + 边界收敛 → MCP；要访问沙箱文件 → CLI+Skill；只是包一层 HTTP 调用 → custom tool。**

---

## 二、mcp_servers 配置

### 2.1 位置与注册模型

- 写在 agent.yaml **顶层** `mcp_servers:`，是一个 list。
- 🚫 **MCP 工具不要在 `tools:` 里注册**。Agent 初始化时会自己连 server → 发 `tools/list` → 把返回的 schema 转成内部 Tool。它们作为独立的 registry source `"mcp"` 加入，和 `tools:` 里的条目并列暴露给模型。
- 模型看到的 description 就是 MCP server 返回的 tool description，**你无法在 agent.yaml 里改写它**。要控制模型行为只能改 server 端的 description，或在 systemprompt 里加使用规则。

### 2.2 三种 type 各自的必填字段

条目类型是三选一的联合：`MCPServerConfig = MCPStdIOServer | MCPHttpServer | MCPSseServer`（这三个名字会原样出现在校验报错里，见 §2.4）。

| type | 独有必填 | 独有可选 | 说明 |
|---|---|---|---|
| `stdio` | `command` (str) | `args` (list[str]) | 在 agent-runtime 容器内起子进程；环境 = runtime 进程自身的环境变量与 `env:` 合并 |
| `http` | `url` (str) | `headers` (dict[str,str]) | Streamable HTTP；`url` 要写到具体端点路径（如 `.../mcp`） |
| `sse` | `url` (str) | `headers` (dict[str,str]) | 老式 SSE 传输，新项目优先用 `http` |

`type` 在 pydantic 层是普通联合（没有 `discriminator`），技术上能靠字段形状推断出来；但配置构建阶段另有一道显式检查：缺 `type` 直接 `ConfigError`。**一律显式写 `type`，不要依赖推断。** 同一处还会二次校验 type 只能是 `stdio`/`http`/`sse`，以及 stdio 必须有 `command`、http/sse 必须有 `url`。

### 2.3 共享字段全集

下表是**三种 type 都能写**的字段。⚠️ `command` / `args` / `url` / `headers` **不在**这张表里——它们是 type 独有字段（§2.2），写到不匹配的 type 上会直接 `Extra inputs are not permitted`（例如给 `stdio` 写 `headers`）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | str | **必填** | server 名，会成为工具名前缀的一部分（见 §3.5） |
| `timeout` | int，约束 `gt=0` | `null` → 运行时按 **30 秒** 兜底 | **单位是秒**，不是毫秒（对比 `sandbox.execute_bash(timeout=…)` 是毫秒） |
| `env` | dict[str,str] | `null` | 三种 type 都能写，但只对 `stdio` 有实际作用：与 runtime 进程环境**合并**（不是替换），同名覆盖 |
| `disable_parallel` | bool | `false` | 该 server 的工具进入「串行工具名单」，执行时阻塞后续工具提交 |
| `source_id` | str \| null | `null`→自动填 `local:mcp_server:{name}` | 血缘标记，一般不用手写 |
| `permissions` | dict[str, list[str]] \| null | `null` | server 级权限。**见 §3.7 警告** |
| `tool_permissions` | dict[str, dict[str, list[str]] \| null] \| null | `null` | per-tool 权限覆盖（key 是**未加前缀的原始工具名**） |

### 2.4 ⚠️ mcp_servers 是 schema 层**真严格**的 `extra='forbid'`

`mcp_servers` 在 schema 里被实打实地声明成 `list[MCPServerConfig]`，泛型真的生效，所以每个条目都会按 `extra="forbid"` 逐字段校验。

- 多写一个字段 / 拼错 key → 直接 `ConfigError`，agent **加载失败、部署后每次请求都起不来**。
- 因为是联合类型，报错会**逐分支列出**，非常吵。下面是给一个合法 `http` 条目多加一个 `bogus_field` 后的**真实完整输出**（实跑采集）：
  ```
  Invalid agent configuration: mcp_servers->0->MCPStdIOServer->type: Input should be 'stdio';
  mcp_servers->0->MCPStdIOServer->command: Field required;
  mcp_servers->0->MCPStdIOServer->url: Extra inputs are not permitted;
  mcp_servers->0->MCPStdIOServer->bogus_field: Extra inputs are not permitted;
  mcp_servers->0->MCPHttpServer->bogus_field: Extra inputs are not permitted;
  mcp_servers->0->MCPSseServer->type: Input should be 'sse';
  mcp_servers->0->MCPSseServer->bogus_field: Extra inputs are not permitted
  ```
  读法：**只看与你实际 `type` 同名的那个分支**（这里是 `MCPHttpServer`），它报的才是真问题；`MCPStdIOServer->command: Field required` / `MCPSseServer->type` 全是噪声。
- 🔁 **对比**：`tools:` / `skills:` 的条目是 `list[Any]`，多余字段被**静默忽略**。同一个 agent.yaml 里两种块的校验强度完全不同——见 `references/agent-yaml-fields.md`「校验强度分层」。

### 2.5 可直接抄的片段（http 型）

```yaml
mcp_servers:
  - name: enterprise_ops_db          # 会成为工具名前缀：mcp__enterprise_ops_db__query_sql
    type: http                       # 显式写，别依赖推断
    url: http://mcp-db.default.svc.cluster.local:8000/mcp
    headers:
      # Accept / Content-Type 不写也行：框架在连接时自动补
      # Accept: application/json, text/event-stream
      Authorization: Bearer ${env.MCP_TOKEN}   # 变量名只能 [A-Za-z_][A-Za-z0-9_]*；未设置 = 加载期 ConfigError
    timeout: 30                      # 秒
```

stdio 型：

```yaml
mcp_servers:
  - name: local_fs
    type: stdio
    command: /opt/venv/bin/python    # 必须是 agent-runtime 容器里真实存在的可执行文件
    args: ["-m", "my_mcp_server"]
    env:
      MY_SERVER_MODE: readonly       # 与 runtime 进程环境合并，同名覆盖
    timeout: 30
```

---

## 三、MCP 部署坑（按踩到的先后顺序）

| 症状 | 真因 | 定位方式 |
|---|---|---|
| 部署成功、模型却完全不提这些工具 | server 连不上，MCP 工具数 = 0，**静默降级不报错** | 看 runtime 日志 `MCP initialization completed: … , 0 tools discovered` 与 `Registered N tools`（**不要**只 grep `Failed to initialize`，见 §3.1） |
| 模型答「查询未返回结果 / 暂时无法获取数据」 | 工具在，但每次调用返回 `{"error": "..."}`，被当正常结果喂回模型 | 看 runtime 日志 `Error executing MCP tool` |
| systemprompt 里写的工具名模型「找不到」 | 工具真名带 `mcp__<server>__` 前缀 | 看日志 registered tools 列表 |
| 每次调用都卡住/被拒 | 配了 `permissions` 但没命中规则 → `AskPermission` | 见 §3.7 |

### 3.1 ⚠️ 初始化失败是静默降级，不是硬失败；而且**多数情况连 "failed" 都不打**

两层吞异常：多个 server 并发初始化，单个 server 抛异常只记一行 `Failed to initialize MCP server '<name>': …` 就跳过；外面整个 MCP 工具初始化又包了一层兜底，异常同样只记日志、返回空工具列表。

🚫 **但 `Failed to initialize MCP server` 不是你该 grep 的字符串。** 它只在异常**逃逸**时才打。最常见的「连不上」场景走的是另一条路：连接阶段自己就把异常吞掉、只判定成「连接未建立」，该 server 于是带着**空工具列表**正常返回，在汇总里被算成**成功**、只是工具数 0。

按可信度排序的真实日志信号：

| 日志串 | 含义 |
|---|---|
| `MCP initialization completed: X/N servers succeeded, M tools discovered` | **最可靠的一行**。看 `M`：`M=0` 就是没接上，哪怕 `X=N`（「succeeded」会骗人） |
| `Failed to connect to HTTP MCP server '<name>': <err>` | HTTP 连接失败（DNS / 拒连 / 403 / Host 头被拒） |
| `Connection to HTTP MCP server '<name>' timed out after <T>s` | 超时，`T` = 你配的 `timeout` 或兜底 30。⚠️ 这条是 **warning 级**，别只看 error |
| `Failed to connect to MCP server '<name>': <err>` | 外层兜底（含 stdio 起不来） |
| `Successfully initialized N MCP tools (async)` | 正向确认，`N` 应等于所有 server 工具数之和 |
| `Registered %d tools (%d eager, %d deferred), %d sub_agents` | 最终注册总数（含 config/builtin 工具，不只 MCP） |
| `Failed to initialize MCP server '<name>'` | 仅异常逃逸时出现，**别当主判据** |

**后果**：agent 照常启动、chat 照常返回 200，只是模型手里没那个工具，于是开始编。所以：
- 部署后**第一件事是看 `MCP initialization completed: … tools discovered` 的工具数**，再核 `Registered %d tools`。
- 不要把「chat 能返回」当作 MCP 接通的验收标准。

### 3.2 ⚠️ 调用期错误被当成 tool 结果回灌给 LLM

MCP 工具执行时的兜底是：捕获所有异常，记一行 `Error executing MCP tool '<name>': <err>` 日志，然后把 `{"error": "<err>"}` 当作**一次正常的工具返回值**交回给模型。DNS 解析失败、连接被拒、server 500，统统变成一个字符串塞回对话。模型看到 `{"error": "[Errno -2] Name or service not known"}` 之后，绝大多数情况会自行「兜底作答」，用户看到的是「未查询到相关数据」这类软话术，**而不是一条显式报错**。

对策：
1. systemprompt 里显式写死：**工具返回中包含 `error` 字段时，必须原样告知用户查询失败及原因，禁止基于常识作答**。
2. 让 MCP server 自己把业务错误返回成人类可读的 `[SQL ERROR] ...` 之类前缀（cookbook 的 sqlite MCP 样例就是这么做的），比裸 traceback 对模型友好得多。

### 3.3 ⚠️ `host.docker.internal` 只在本机可用

（这是通用的 Docker/K8s 网络语义，不是 NexAU 框架的行为。）本机 Docker Desktop / Kind 调试时 `http://host.docker.internal:8000/mcp` 能打通宿主机；**部署到任何真实集群（包括 NAC 测试/生产）都解析不到**（该名字由 Docker Desktop 注入，K8s 集群 DNS 里没有），直接落进 §3.1 的静默降级。cookbook 的 `templates/04-mcp-server/db_mcp_agent/agent.yaml` 与 `templates/10-reference-skeleton/agent.yaml` 里写的就是 `host.docker.internal`（本机调试用），**上集群前必须改**成集群内可达地址：K8s Service DNS（`http://<svc>.<ns>.svc.cluster.local:<port>/<path>`）或有 DNS 记录的外部地址。

### 3.4 ⚠️ `Host` header 与 DNS rebinding 防护

（下述是**工程实践，不是 NexAU 框架行为**：FastMCP 是第三方库，其上游默认值本文未核实。）cookbook 的 sqlite MCP 样例显式设了 `TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["localhost:*", "127.0.0.1:*"])`（见 `templates/04-mcp-server/sqlite_mcp_server/server.py`），照它改出来的 server 都会带这套防护。当你用 `host.docker.internal:8000` 或 Service DNS 去连时，请求的 `Host` 头不在白名单里 → server 直接拒（表现为 §3.1 的 `Failed to connect to HTTP MCP server`）。两种解法（二选一，别都不做）：

- 客户端侧：在 `headers:` 里显式覆盖 `Host: localhost:8000`（本机调试常用）；
- 服务端侧（上集群时的正解）：把 server 的 `allowed_hosts` 放开到实际访问用的 host:port。

### 3.5 ⚠️ 工具名带 `mcp__<server>__<tool>` 前缀

当前 pin 版本对 MCP 工具统一改名，规则是 `mcp__<server 的 name>__<server 里的原工具名>`。server 里叫 `query_sql`、`name: enterprise_ops_db`，模型看到的就是 `mcp__enterprise_ops_db__query_sql`。

- 写 systemprompt 时**优先按能力描述引导**（「用数据库查询工具执行 SQL」），少写死工具名；确实要写就写全前缀名。
- 前缀是 `0.5.0`（tag 日期 2026-06-10）之前引入的（2026-05-08），**更早的版本不加前缀**；跨版本迁移时写死的工具名会失效——这是把工具名硬编码进 systemprompt 的主要风险点。
- `tool_permissions` 的 key 是**原始名**（`query_sql`），权限规则串却是**前缀名**（`mcp__enterprise_ops_db__query_sql`）。两处不一样，别抄串了。

### 3.6 stdio server 跑在 agent-runtime 容器里，不在沙箱里

`command` 指向的可执行文件必须存在于 **agent-runtime 容器**（制品挂在只读 `/agent`，进程 cwd 是 `/home/user`）。要装依赖走 `nexau.json` 的 `setup`（离线 whl），见 `references/nexau-json-and-packaging.md`。stdio server 看到的文件系统**不是**沙箱的 `/home/user`，别指望它能读到 Agent 用 `write_file` 写出来的东西。

### 3.7 ⚠️ 除非确有需要，别配 `permissions` / `tool_permissions`

不写这两个字段（保持 `null`）→ 该工具的权限为空 → 不进权限缓存，查找时回落成通配规则 → 权限检查第一步就无条件放行。**一旦你写了**，未命中 allow 的调用会抛 `AskPermission`——那是给有人类确认通道的宿主用的，NAC 无人值守链路上表现为调用失败/挂起。

要用的话：规则串用前缀形态，server 级通配 `mcp__<server>` 匹配该 server 下全部工具，`**` 无条件放行；deny 优先于 allow。

### 3.8 部署前 sanity check（必做）

```bash
# 1. 端点可达性（关键是「有 HTTP 响应」——405/406/400 都说明端口通了；
#    Connection refused / Could not resolve host = 不通。具体状态码取决于 server 实现，别硬卡 200）
curl -m 5 -sI http://<mcp-host>:<port>/mcp

# 2. 真正列一次工具，确认 server 返回的工具名与你 systemprompt 里的一致
curl -m 10 -s http://<mcp-host>:<port>/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

第 1 步必须**从和 agent-runtime 相同的网络位置**发（本机 curl 通不代表 pod 里通）。部署后再核一次 runtime 日志的 `Registered %d tools`。

---

## 四、⚠️ 只读 / 单语句 / 行数限制必须写在 server 侧

> 本节是**工程纪律**，不是 NexAU 框架能校验的东西——框架对 MCP server 内部实现零约束。下表做法取自 cookbook 样例 `templates/04-mcp-server/sqlite_mcp_server/server.py`。

Text-to-SQL 类 MCP 尤其容易犯：把「只允许 SELECT」「一次只跑一条语句」「最多返回 200 行」写进 systemprompt。**prompt 不是安全边界**——模型会被绕、会被 prompt injection 拐、也会自己写错。这些约束一律落在 server 代码里，至少三层：

| 层 | 做什么 | 样例写法 |
|---|---|---|
| 语法白名单 | 只允许 `^\s*(SELECT|WITH)\b` 开头 | 拒绝时返回可读错误串给模型，而不是抛异常 |
| 关键字黑名单 + 单语句 | 拒 `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/REPLACE/TRUNCATE/ATTACH/DETACH/PRAGMA/REINDEX`；剥掉尾分号后若仍含 `;` 直接拒 | 防 `SELECT 1; DROP TABLE t` |
| 驱动层兜底 | 连接本身就是只读：SQLite `file:...?mode=ro`、PG 用只读角色 `GRANT SELECT` + `default_transaction_read_only` | 即使前两层被绕过也写不进去 |

外加两个必配的量化闸门：**结果行数上限**（`fetchmany(limit+1)` 判断是否截断并显式告诉模型「已截断」）和**语句超时**（PG `statement_timeout`）。前者防上下文被一次全表扫爆，后者防慢查询把 `timeout` 耗光变成 §3.2 的静默 error。

同理，凡是「不允许做 X」的硬约束（删文件、发外部请求、越权读表），都要在 server 侧实现，prompt 里只做**重复声明**用于提高模型配合度。

---

## 五、sub_agents

### 5.1 条目 schema

这里的 `extra='forbid'` 是**真实生效**的（`sub_agents` 是泛型直接标注的，不像 `tools:` 那样退化成 `list[Any]`）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | str | ✅ | 主 agent 调用时用的标识 |
| `config_path` | str | ✅ | 子 agent 的 agent.yaml 路径 |
| `source_id` | str \| null | — | 血缘标记，一般不写；缺省自动填 `local:sub_agent:<name>` |

关键规则：

1. **`config_path` 的基准是「当前 agent.yaml 所在目录」**（而不是制品根目录）。和 `tools[].yaml_path` 同基准，但和 `tools[].binding` 的 import 根（制品根目录）**不同**——制品把 agent.yaml 放在 `agents/` 子目录时最容易踩。
2. **条目的 `name` 覆盖子 agent yaml 里自己的 `name`**。调用时用的是条目名。
3. 两个条目重名 → `ConfigError: Sub-agent name conflict for '<name>' between ...`。注意冲突判定用的是**覆盖之后**的名字，而条目 `name` 是必填且总会覆盖，所以这条只可能由「两个条目写了同一个 `name`」触发。
4. 多写一个字段 → 直接 `Invalid agent configuration: sub_agents->0->bogus: Extra inputs are not permitted`（实跑采集），agent 加载失败。
5. 子 agent 文件找不到 / 自身配置有错 → NAC 上走的是严格模式（平台加载子 agent 的两条分支都没关掉它，框架默认就是严格），直接抛 `ConfigError: Skipped sub-agent '<name>': ...`——**尽管文案写着 Skipped，它是硬失败，不是跳过**。
6. 运行期调用了未配置的名字：不是硬崩，子代理管理器抛 `ValueError("Sub-agent 'x' not found")`，被委派工具捕获转成 `{"status": "error", "error": "..."}` 返给模型。（某些旧资料提到的 `SubAgentNotFoundError` 实际**不存在**，别按这个类名找日志。）

### 5.2 ⚠️ 三个自动注入的工具——禁止手写进 `tools:`

| 工具名 | 注入条件 | 参数 |
|---|---|---|
| `Agent` | `sub_agents` 非空 | `sub_agent_name`(必填) / `message`(必填) / `sub_agent_id`(可选，续跑已结束的子代理) |
| `LoadSkill` | `skills:` 非空 **或** 任一工具 `as_skill: true` | 见 `references/builtin-tools.md` |
| `ToolSearch` | 存在 `defer_loading: true` 的工具（`deferred_count > 0`） | 同上 |

规则与细节：

- 注入的 `Agent` 工具描述里会自动拼上「Available sub-agents: - **name**: description」列表，取的是**子 agent yaml 的 `description`**。所以**每个子 agent 的 `description` 必须写清职责**——那是主 agent 唯一的路由依据。子 agent 没写 description 时会 fallback 成 `Delegate work to sub-agent 'x'.`（毫无信息量，模型会乱派活）。
- 委派工具**固定叫 `Agent`**，不叫 `call_sub_agent` / `Task`。systemprompt 里要用这个名字引导。
- `LoadSkill` 有一道去重守卫：`tools` 里已存在名为 `LoadSkill` 的工具时**跳过注入**。`Agent` 和 `ToolSearch` **没有**这道守卫，手写会得到重名工具。一律不要手写这三个。

### 5.3 子代理的能力范围

子代理走的是和主 agent **完全相同**的配置构建链（core → llm_config → mcp_servers → hooks → tracers → tools → sub_agents → skills → system_prompt → sandbox），所以：

- ✅ 可以有自己的 `tools` / `skills` / `mcp_servers` / `middlewares` / `llm_config`；
- ✅ 可以再嵌套 `sub_agents`，无深度限制；
- 🚫 唯一被忽略的是 `plugins`：子 agent 加载时不展开 plugins，整段被直接丢弃，只打一条 `sub_agent_load plugins_ignored=N` 日志，不报错。

### 5.4 ⚠️ 子代理与主 agent 共享同一个沙箱实例 + 同一份 global_storage/session

委派子代理时，父 agent 的沙箱管理器被原样下传给子代理（构造子代理的每一条分支都如此），同时一律共用 `global_storage` / `session_manager` / `user_id` / `session_id`；NAC 侧给请求注入 `sandbox_config` 时也会递归下发到 sub_agents，注入的是同一份。

🚫 **别想着「给子代理写一个自己的 `sandbox_config` 来隔离」**。NAC 侧确实会保留子 agent 显式声明的 `sandbox_config`（只在它缺席时才注入父的那份），但框架侧不认：子代理初始化沙箱时，一旦发现已经有父传下来的沙箱管理器就直接用它，子 agent 自己的 `sandbox_config` 不会用来新建沙箱。而 NAC 链路上父的沙箱管理器恒非空 → **子代理永远和主 agent 同一个沙箱实例**。

后果，逐条记牢：

- **没有文件隔离**。子代理 `write_file` 写的就是主 agent 看到的那份 `/home/user`；子代理 `rm` 掉的文件主 agent 也没了。
- **「只读子代理」必须靠不给它写工具来实现**（子 agent 的 `tools:` 里只放 `read_file` / `search_file_content` / `list_directory`，不放 `write_file` / `replace` / `run_shell_command`），不是靠沙箱隔离。
- **可以用文件传大产物**：子代理把结果写到约定路径、只在返回值里回一个路径 + 摘要，比把几万字塞进 `result` 省上下文得多。这是共享沙箱唯一的好处，用起来。
- `global_storage` 也是共享的，子代理写的键主 agent 能读到（反之亦然）。

### 5.5 ⚠️ `stop_tools` 必须显式声明，否则挂了 `complete_task` 也白搭

`stop_tools` 默认是**空集**。把 `complete_task` 放进 `tools:` **不会**让它自动变成停止工具。

只有工具名确实出现在 `stop_tools` 里，这次调用才会被打上「停止工具」标记、触发提前终止；也只有在这条路径上，`complete_task` 的 `result` 参数才会被取作 final_response。

**漏写的表现**：子代理调完 `complete_task` 后不停，继续兜圈子直到模型自己不再发工具调用、或撞满 `max_iterations`（默认 100），返回给主 agent 的还是模型最后一段自由发挥的文本，而不是它精心写的 `result`。表现为「子代理很慢 + 返回内容和它声明的结果对不上」。

正确写法（子代理自己的 agent.yaml）：

```yaml
tools:
  - name: complete_task
    yaml_path: ./tools/complete_task.tool.yaml     # 基准 = 本（子）agent.yaml 所在目录
    binding: nexau.archs.tool.builtin.session_tools:complete_task

stop_tools:
  - complete_task      # ← 少这一行，上面那个工具形同虚设
```

> ⚠️ 这是 cookbook 原版《档案助手》踩过的坑：`sub_agents/file_classifier/agent.yaml` 挂了 `complete_task` 却没写 `stop_tools`。**本 skill 的 `templates/10-reference-skeleton/` 已修好**（那份 yaml 现在有 `stop_tools: [complete_task]`），可以直接照抄；去 cookbook 原仓拿的话要自己补。

### 5.6 ⚠️ `max_running_subagents` 目前是空旋钮

`max_running_subagents`（默认 5）会从配置一路传到执行器并被存下来，**然后就没有任何地方读它**——框架里既没有对应的信号量，也没有线程池上限，子代理管理器里根本没有这个字段。某些资料把它描述成「用 ThreadPoolExecutor 做并发上限」，与实际行为不符。

**不要承诺它能限流，也不要拿它做容量保护。** 真要限制并发子代理，只能靠：子代理数量本身控制少、systemprompt 里约束「一次只委派一个」、或给主 agent 设更小的 `max_iterations`。

### 5.7 什么时候该拆子代理 / 什么时候不该

> 「✅ 拆」那几行是经验性判断；「🚫 别拆」里涉及隔离与并发的两行是平台的确定行为，见 §5.4 / §5.6。

| 场景 | 拆不拆 | 理由 |
|---|---|---|
| 一个阶段会产生大量中间输出（逐文件扫描、批量分类、粗筛几十个候选），主流程只需要结论 | ✅ 拆 | 中间上下文关在子代理里，主 agent 只收摘要，最有效的省上下文手段 |
| 两个阶段需要**不同工具集**，且合并后工具总数明显变多（比如「检索」只要读、「产出」只要写+跑脚本） | ✅ 拆 | 工具越少模型选错概率越低；顺带天然限制了各阶段爆炸半径 |
| 两个阶段需要**不同模型 / 不同 temperature**（抽取要稳、写作要活） | ✅ 拆 | 子代理可以有自己的 `llm_config` |
| 需要「审阅者」角色对前一阶段产物挑错 | ✅ 拆 | 独立上下文的审阅质量显著高于同一条对话里自查 |
| 只是流程有先后顺序（先读再写），工具集基本重合 | 🚫 别拆 | systemprompt 里写编号步骤即可；拆了只多一层委派开销和一个失败点 |
| 想靠子代理做**权限/数据隔离** | 🚫 别拆 | 共享同一沙箱和 global_storage，隔不开（§5.4） |
| 想靠子代理做**并发提速** | 🚫 别拆 | `max_running_subagents` 是空旋钮（§5.6），并发不由你控制 |
| 单次任务总轮数本来就很少（< 10 轮） | 🚫 别拆 | 委派本身要花掉主 agent 一轮，收益为负 |

拆之后必配的三件事：① 子 agent 的 `description` 写清职责边界（决定路由）；② 子代理挂 `complete_task` **并**写 `stop_tools`；③ 主 agent 的 systemprompt 里写明「什么情况下派给谁、派过去要说清什么」。

### 5.8 可直接抄的片段

主 agent 的 agent.yaml：

```yaml
sub_agents:
  - name: doc_reviewer                                  # 调用标识，覆盖子 agent yaml 的 name
    config_path: ./sub_agents/doc_reviewer/agent.yaml   # 相对【本 agent.yaml 所在目录】

# 🚫 不要写 tools: - name: Agent —— sub_agents 非空时框架自动注入
```

子 agent 的 `sub_agents/doc_reviewer/agent.yaml`（只读角色）：

```yaml
type: agent
name: doc_reviewer
description: 审阅已生成的文档草稿，逐条指出事实性错误与格式问题，只读不改。   # ← 主 agent 的路由依据
system_prompt: ./systemprompt.md
system_prompt_type: jinja
max_iterations: 30

llm_config:
  temperature: 0.1

# yaml_path 基准 = 本文件所在目录（sub_agents/doc_reviewer/），
# 所以 cookbook 的做法是给每个子代理放一份自己的 tools/ —— 照做最不容易错
tools:                                     # 只给读工具 = 唯一可靠的「只读」约束（沙箱是共享的）
  - name: read_file
    yaml_path: ./tools/read_file.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:read_file
  - name: search_file_content
    yaml_path: ./tools/search_file_content.tool.yaml
    binding: nexau.archs.tool.builtin.file_tools:search_file_content
  - name: complete_task
    yaml_path: ./tools/complete_task.tool.yaml
    binding: nexau.archs.tool.builtin.session_tools:complete_task

stop_tools:
  - complete_task                          # ← 必须显式写
```

主 agent systemprompt 里的引导（照这个语气写）：

```markdown
## 委派规则
- 草稿写完后，**必须**用 `Agent` 工具委派 `doc_reviewer` 审阅一遍，再根据反馈修订。
- 调用 `Agent` 时：`sub_agent_name` 填 `doc_reviewer`，`message` 里写清「待审文件的绝对路径 + 本次要重点检查什么」。
- 子代理与你共用同一个工作目录，**不要**把文件内容整段贴进 `message`，只给路径。
```

---

## 六、错误速查

| 报错 / 症状 | 位置 | 处理 |
|---|---|---|
| `Invalid agent configuration: mcp_servers->0->MCPStdIOServer->xxx: Extra inputs are not permitted`（三分支一起报） | 加载期 | 找你自己多写/拼错的 key；别被 `url: Field required` 带偏（§2.4） |
| `MCP server configuration N missing 'type' field` / `has invalid type 'x'` | 加载期 | `type` 只能 `stdio`/`http`/`sse`（§2.2） |
| `MCP server configuration N of type 'stdio' missing 'command' field` | 加载期 | 补 `command`；http/sse 同理补 `url` |
| 日志 `MCP initialization completed: …, 0 tools discovered` / `Failed to connect to HTTP MCP server '<name>'`，但 chat 正常返回 | 启动期 | 静默降级；查网络可达性与 `Host` 头（§3.1/3.3/3.4）。**别只 grep `Failed to initialize`，那条多数时候根本不打** |
| 日志 `Error executing MCP tool '<name>'`，用户看到「未查询到数据」 | 运行期 | 错误被当结果回灌；systemprompt 加「见 error 字段必须如实报错」（§3.2） |
| 模型说找不到你在 prompt 里写的工具名 | 运行期 | 真名带 `mcp__<server>__` 前缀（§3.5） |
| `Invalid agent configuration: sub_agents->0->xxx: Extra inputs are not permitted` | 加载期 | 条目只允许 `name` / `config_path` / `source_id`（§5.1） |
| `ConfigError: Skipped sub-agent '<name>': ...` | 加载期 | NAC 默认 strict，是硬失败；先查 `config_path` 基准是否搞错（相对 agent.yaml 目录） |
| `Sub-agent name conflict for '<name>' between ...` | 加载期 | 两个 `sub_agents` 条目写了同一个 `name` |
| 工具返回 `{"status":"error","error":"Sub-agent 'x' not found"}` | 运行期 | 模型传的 `sub_agent_name` 与条目名不一致；在 systemprompt 里写死可用名字 |
| 子代理很慢、返回内容与它声明的结果对不上 | 运行期 | 漏写 `stop_tools: [complete_task]`（§5.5） |
| 想限制并发子代理，设了 `max_running_subagents` 没效果 | — | 空旋钮，无代码消费（§5.6） |
