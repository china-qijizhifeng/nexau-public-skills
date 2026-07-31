# 模板：原生驱动 + 离线装依赖（05-native-driver-airgap）

> 用 `custom_tools` 直连一个 NAC 默认不带驱动的数据库（本例 达梦 DM8 / dmPython），依赖靠 `nexau.json` 的 `setup` 从制品内的离线 whl 装上，**一个 zip 自包含、无外挂服务**。
> 难度：Level 2 进阶 ｜ 来源：nexau-cookbook《达梦数据库》(`tutorial-dameng-sql-agent.md`)

## 这个模板教你什么

1. **`nexau.json` 的 `setup` 离线装依赖**（本 skill 唯一范例）：把 whl 打进制品，runtime 容器启动时 `uv pip install --no-index --find-links /agent/<dir>` 装到 `/opt/venv`。适用于任何 NAC 镜像不带的库（dmPython / clickhouse-driver / mysqlclient / 内网 SDK）。
2. **native 驱动只能落在 agent-runtime 进程**：`custom_tools` 的 Python 函数跑在 runtime 容器里，`setup` 装的包也只在这个容器里；**沙箱（`run_shell_command`）看不到它们**，两套镜像两套依赖。
3. **凭证经 `extra_kwargs` 注入、永不进上下文**：连接串通过 `${env.X}` → `extra_kwargs` 进 Python 函数形参，模型侧 schema 只有 `sql` / `max_rows` / `timeout`。
4. **⚠️ 用了 `extra_kwargs` 的工具，input_schema 必须去掉 `additionalProperties: false`**（P0，见「已知的坑」1）。
5. **只读 SQL 校验必须写在代码里**：剥注释 → 剥字符串字面值 → 大写化 → 前缀白名单 + 单语句 + 关键字黑名单三层硬卡，prompt 里写「只允许 SELECT」不算数。
6. **native 库 dlopen 失败的运行时自愈**：进程启动后改 `LD_LIBRARY_PATH` 无效，正确修法是在驱动自己的 `*.libs/` 下建软链（幂等、首调触发）。

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 替代 |
|---|---|---|
| 要连 NAC 镜像不带驱动的库（达梦 / 人大金仓 / ClickHouse / 内网 SDK） | ✅ 就是它 | — |
| 要连 PostgreSQL / MySQL 且脚本跑在沙箱里 | ⚠️ 沙箱已预装 `psycopg2-binary`，不需要 `setup` | 直接 `run_shell_command` |
| 只是要写 Text-to-SQL 的表语义 / 业务口径 | ❌ | `03-text-to-sql` |
| 数据库归另一个团队 / 要跨边界审计 / 多 agent 共用同一套 SQL 白名单 | ❌ | `04-mcp-server` |
| 只调 HTTP API，无 native 依赖 | ❌ | `02-rest-api-tool` |
| 依赖体积 > ~90 MiB（whl 塞不进制品） | ❌ 制品硬上限 100 MiB | 改用 MCP server / 自定义 runtime 镜像 |
| 要在**沙箱**里用这个额外依赖 | ❌ `setup` 装不到沙箱 | 沙箱内自行 `pip install`（需出网）或换预装库 |

## 目录结构

```
05-native-driver-airgap/
├── agent.yaml                       Agent 主配置：llm_config + tools 绑定 + extra_kwargs 注入连接串
├── nexau.json                       项目清单：agents 映射 + setup 离线安装命令
├── systemprompt.md                  系统提示词（顶层必需文件，agent.yaml 以路径引用）
├── README.md                        制品自带的一页说明（会跟着一起打包）
├── TEMPLATE.md                      本文（给生成方看的，打包时可删）
├── custom_tools/
│   ├── __init__.py                  包标记，必须有，否则 binding 的 import 路径解析不到
│   └── dameng_sql.py                dmPython 调用 + 只读 SQL 校验 + dmssl 软链 workaround
├── tools/
│   └── run_dameng_sql.tool.yaml     模型可见的工具 schema（不含连接串）
└── dmpython-airgap/                 离线依赖目录，运行时对应 /agent/dmpython-airgap
    ├── download-whls.sh             从 PyPI 拉 x86_64 + aarch64 两份 whl
    ├── README.md                    离线包说明
    └── .gitignore                   忽略 *.whl（⚠️ whl 不入库，打包前必须现拉）
```

## 复制后必须改的地方

| # | 文件:字段 | 改成什么 |
|---|---|---|
| 1 | `nexau.json:agents` 的 key + `agent.yaml:name` | 你的 agent 名，**两处必须一致**（key 就是 NAC 上被调用的名字） |
| 2 | `agent.yaml:description` / `systemprompt.md` | 你的真实表结构、字段口径、禁止行为。表多就抽成 SKILL（见 `03-text-to-sql`）。`systemprompt.md` 里「skills 根目录位于 `/home/user/.skills/`」那段是静态校验必需的，改写可以，**不能整段删掉** |
| 3 | `agent.yaml:llm_config.model` | 保留 `${env.LLM_MODEL}` 跟随项目默认模型；要钉死某个模型就写模型 id 字面量 |
| 4 | `agent.yaml:tools[0].extra_kwargs.db_conn_str` | 改成你的 env 名（如 `${env.PG_DSN}`），并在 NAC 项目 → Runtime Vars 建同名变量（**runtime scope**，勾 Secret） |
| 5 | `agent.yaml:tools[0].name` / `yaml_path` / `binding` | 三处跟着工具改名；`binding` 格式 `<包路径>:<函数名>`，包路径以制品根为起点（`custom_tools.dameng_sql:run_dameng_sql`） |
| 6 | `tools/*.tool.yaml:name` | 必须等于 `agent.yaml:tools[].name` |
| 7 | `tools/*.tool.yaml:input_schema` | 只放模型该填的参数；**不要**把 `db_conn_str` 加进 `properties`（加了模型就能覆盖它），也**不要**加 `additionalProperties: false` |
| 8 | `custom_tools/dameng_sql.py` | 换驱动：`import dmPython` → `psycopg2` / `pymysql` / `clickhouse_driver`；`_build_connect_args()` 按新驱动改；**换驱动后 `_preload_dmssl_libs()` 整个删掉**（那是 dmPython 专属 workaround） |
| 9 | `nexau.json:setup` | **两条都要改**。`setup[0]`（安装）：改包名 + 版本 + 目录名；`/usr/local/bin/uv` 和 `/opt/venv/bin/python` 是 runtime 镜像的固定路径，**别动**；`/agent/<dir>` 里的 `/agent` 是制品根，也别写成本地绝对路径。`setup[1]`（`import` 自检）：改成新驱动的**模块名**——⚠️ 模块名常与包名不一致（`dmpython` 装出来是 `dmPython`、`psycopg2-binary` 是 `psycopg2`、`clickhouse-driver` 是 `clickhouse_driver`），这是最容易漏改的一处。**自检这条不能删**：setup 失败只打 WARNING、部署照样绿，没有它就看不出装没装上（见「已知的坑 · setup 失败是假绿」） |
| 10 | `dmpython-airgap/` 目录名 | 跟 #9 的 `--find-links` 路径同步改 |
| 11 | `dmpython-airgap/download-whls.sh` 的 `VERSION` / `PY` / 包名 | `PY=cp312` 对应 runtime 镜像的 uv-managed Python 3.12；纯 Python 包（`py3-none-any`）把 `--platform` 参数去掉 |
| 12 | **打包前**在离线目录跑一次 `bash download-whls.sh` | whl 被 `.gitignore` 排除，clone / 复制模板后目录是空的，漏拉 = 部署后 `ImportError` |

打包：`zip -rq ../artifact.zip . -x '*__pycache__*' -x '*.DS_Store'`，制品必须含 `nexau.json`、≤ 100 MiB、**不能含符号链接**（含符号链接直接 400）。

## 关键设计要点

### 1. `setup` 到底在哪跑、怎么失败

| 事实 | 后果 |
|---|---|
| 命令由 scheduler 从 `nexau.json.setup` 取出，以 `NEXAU_SETUP_COMMANDS` 注入 **runtime 容器**（不是 init 容器） | 只有 runtime 容器有 `uv` / `/opt/venv`，装的包也只有 `custom_tools` 用得到 |
| wrapper 脚本先 `cd /agent`，再逐条 `eval` | 相对路径以制品根为基准；`/agent/<dir>` 就是本地那层目录 |
| 失败只 `log "WARNING: setup command failed"`，**不中断启动** | ⚠️ 装不上照样 Running、照样绿。判断成不成功只能看 pod 日志或第一次调用工具时的 `ImportError` |
| 每次 runtime pod 起来都重跑（扩缩容 / 滚动 / 冷启动都算） | setup 必须**幂等**且快；装大包会拖长冷启动 |
| `echo "$NEXAU_SETUP_COMMANDS" \| while read` → 跑在子 shell 里 | ⚠️ setup 里 `export` 的环境变量**不会**传给后面的 runtime 进程，别指望用 setup 设 env |

### 2. 为什么必须离线 whl，而不是直接 `pip install`

runtime pod 在 airgap / 受控出网环境下摸不到 PyPI，所以只能 `--no-index --find-links <制品内目录>`。dmPython 又是 Cython 编译的 native binding，PyPI 只有 Linux `manylinux_x86_64` / `aarch64` 两个 wheel（**没有 macOS 版**）——于是两份 whl 同放一个目录，`uv pip install --find-links` 按 pod 架构自动挑，x86 生产和鲲鹏 ARM 共用同一份 zip，零分叉。

### 3. 凭证不进上下文

```yaml
tools:
  - name: run_dameng_sql
    binding: custom_tools.dameng_sql:run_dameng_sql
    extra_kwargs:
      db_conn_str: ${env.DAMENG_DB_CONN_STR}   # 加载期就地替换成真值，只在 Python 进程内可见
```

模型看到的 schema 里根本没有 `db_conn_str`，prompt / 对话历史 / trace 里也不会出现。这比「把连接串写进 system_prompt 让模型自己拼」稳一个量级。密钥注入的两条通路（runtime scope vs sandbox scope）见 `../../references/agent-yaml-fields.md`。

### 4. 只读校验：为什么要剥注释和字符串

反例（只做关键字黑名单会被绕过 / 会误杀）：

| 输入 | 朴素做法 | 本模板 |
|---|---|---|
| `/* x */ DROP TABLE t` | 前缀是 `/*` 不是 `SELECT`，某些实现直接放过 | `_strip_sql_comments()` 后前缀判定 → 拒 |
| `SELECT 'DROP' AS x` | 命中黑名单被误杀 | 字符串字面值先替换成 `''` → 放行 |
| `SELECT 1; DELETE FROM t` | 只看第一条语句 → 放过 | 单语句检查 → 拒 |

> 即使 prompt 写死「只允许 SELECT」，模型仍可能在 tool call 里塞 DDL。**安全必须写代码。**

### 5. `[CODE:-70089]` 的正确修法

社区给的 `LD_LIBRARY_PATH=site-packages/dmssl` 在**进程启动后设置无效**（glibc 启动时已缓存搜索路径）。`LD_DEBUG=files,libs` 抓出的真因：dmPython dlopen 只搜 `site-packages/dmpython.libs/`，不搜 `dmssl/`。修法是在 `dmpython.libs/` 下建软链（含 `-3.so` 后缀别名），文件系统层面解决。代码在 `_preload_dmssl_libs()`：首次调用工具时跑（不在 import 阶段，避免拖慢启动）、模块级标志位 + `os.path.exists` 双重幂等、`OSError` 静默（只读 fs 就跳过）。

这套「native 库 dlopen 失败 → 在 `*.libs/` 下补软链」的套路对其他信创驱动同样适用。

## 已知的坑

| ⚠️ 坑 | 症状 | 修法 |
|---|---|---|
| **`extra_kwargs` × `additionalProperties: false`（P0）** | 工具每次调用都抛 `ValueError: Invalid parameters for tool 'x': Additional properties are not allowed ('db_conn_str' was unexpected)` | 该工具的 `input_schema` 删掉 `additionalProperties: false`。框架先 `{**extra_kwargs, **params}` 再校验，只剔除 `agent_state` / `global_storage` / `sandbox` / `ctx`，不剔除 extra_kwargs。没有 extra_kwargs 的工具可以保留该行 |
| **setup 失败是假绿** | pod Running、部署成功，第一次调工具才 `dmPython is not installed` | 本模板 `setup[1]` 已带一条 `import` 自检——部署后看 runtime pod 日志：有 `[setup-check] dmPython OK <path>` 才算真装上；只看到 `WARNING: setup command failed` 或没有 `[setup-check]` 行就是没装上。换驱动时**自检那条要跟着改模块名，别删** |
| **whl 忘了拉** | 同上，且 setup 日志里 uv 报 `no matching distribution` | 打包前必跑 `download-whls.sh`；`.gitignore` 里有 `*.whl`，`git archive` / clone 都不会带上 |
| **制品超 100 MiB** | 上传 413 | 每份 dmPython whl ~11 MB×2；再塞几个大 whl 就爆了 |
| **归档里有符号链接** | 上传 400 | 离线目录只能放 whl 实体文件，不能软链到别处 |
| **Python 版本对不上** | uv 报找不到匹配 wheel | whl 的 `cp312` 绑死 runtime 镜像的 Python 3.12；镜像升版本要重拉 |
| **mac 上跑不起来** | 本地 import dmPython 失败 | dmPython 没有 macOS wheel，本模板只能在 NAC / Linux 上验 |
| **沙箱里也想用这个驱动** | `run_shell_command` 里 `import dmPython` 失败 | `setup` 只装到 runtime 容器；沙箱是另一套镜像（预装 `/opt/sandbox-python`，含 psycopg2-binary 等，见 `../../references/builtin-tools.md`） |
| **`${env.X}` 未设置** | agent 加载期 `ConfigError: Environment variable 'X' is not set`，整个 agent 起不来 | `${env.X}` 是加载期对整份 YAML 文本正则替换（**注释里的也会被替换**），不支持默认值 / 转义。所有引用的 var 必须在 runtime scope 存在；项目一张可见模型卡都没有时 `LLM_MODEL` 不会被注入 |
| **数据库地址填了本地地址** | 连接超时 | 必须填 runtime pod 可达的地址（同集群 Service FQDN / 内网 DNS / 公网 IP） |
| **用 SYSDBA 连生产** | 校验层被绕过就是灾难 | DM 端建只读账号 `GRANT SELECT ON ... TO readonly_user`，代码校验只是第二道锁 |

## 本模板相对 cookbook 原版的改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `tools/run_dameng_sql.tool.yaml` | 删 `additionalProperties: false`，原地加注释说明原因 | **P0**：与 `extra_kwargs.db_conn_str` 互斥，原版每次调用必抛 `Additional properties are not allowed` |
| `agent.yaml` | `tool_call_mode: openai` → `structured` | `openai` 是会打一次 deprecation warning 的 legacy alias，框架内部归一化成 `structured`；合法值只有 `xml` / `structured` |
| `agent.yaml` | `llm_config` 删掉 `base_url` / `api_key` / `api_type` / `stream`，只留 `model` / `max_tokens` / `temperature`，并加一行「本地裸跑需自行补 base_url / api_key」注释 | 这四个字段在 NAC 上被平台无条件覆盖（`base_url`/`api_key` 直接覆盖、`api_type` 由模型卡派生、流式路径 `stream` 强制 True），写了是噪声；`api_type` 默认值本来就是 `openai_chat_completion`，删掉不改行为 |
| `systemprompt.md`（新增） | 把 `agent.yaml` 里的内联 `system_prompt` 字符串逐字提取成顶层 `systemprompt.md`，并追加「参考资料的取用」一段（说明 skills 根目录位于 `/home/user/.skills/`、以 LoadSkill 返回的 SkillFolder 为权威路径） | 平台静态校验要求制品顶层必须有 `systemprompt.md`（`artifact.required_file.missing`），且其内容必须显式声明 skills 根目录（`agent.system_prompt.required_pattern_missing`）；内联字符串会被当成路径解析失败（`agent.system_prompt.missing`） |
| `agent.yaml` | `system_prompt` 由内联折叠字符串改为 `./systemprompt.md` | 同上，`system_prompt` 必须是存在的文件路径 |
| `agent.yaml` | 新增 `system_prompt_type: jinja` | 必填且只接受 `jinja`（`agent.field.invalid`）；提示词里无 `{{ }}`，行为不变 |
| `agent.yaml` | 末尾新增 `skills: []` / `middlewares: []`（附一行注释） | 两个字段必须是 list，缺省会报 `skills.invalid_type` / `middlewares.invalid_type`；本模板不挂 skill、不加中间件，故为空列表 |
| `nexau.json:setup` | 在安装命令后补一条 `import` 自检：`/opt/venv/bin/python -c 'import dmPython; print("[setup-check] dmPython OK", dmPython.__file__)'` | setup 失败只 `log WARNING`、**不中断启动**，装不上照样 Running 照样绿，直到第一次调工具才 `ImportError`。有了自检，pod 日志里能一眼看出装没装上。这是 `../../references/nexau-json-and-packaging.md` §3.2 列的第 1 号坑，§3.3 给的正是这条命令 |
| `custom_tools/__pycache__/` | 删除（含 `*.pyc`） | 编译产物不该进制品，`nexau.json:excluded` 也把 `__pycache__/` 列为排除项 |
| `README.md` | 「详细教程见上一级 `tutorial-dameng-sql-agent.md`」→ 指向 `TEMPLATE.md` | 裁剪后 tutorial 不在制品目录里，原指向是死链 |
| `README.md` | 本地路径示例 `达梦数据库/达梦数据库/dmpython-airgap/` → `<制品根目录>/dmpython-airgap/` | 模板目录名已不同，照抄会误导 |
| `README.md` | Runtime Vars 由「4 个」收敛成表格：只保留 `DAMENG_DB_CONN_STR`（必配）+ `LLM_MODEL`（平台注入），并说明 `LLM_BASE_URL` / `LLM_API_KEY` 不用配 | 跟 `llm_config` 收敛保持一致，否则叫人配了不生效的变量 |
| `dmpython-airgap/README.md` | 末尾 tutorial 指向 → `../TEMPLATE.md` | 同上，死链 |
| — 已裁剪 — | cookbook 原目录里的 `tutorial-dameng-sql-agent.md`（含 DM8 建表种子数据引导、Playground 试问步骤、与 MCP 方案的取舍对比） | 完整版见 `nexau-cookbook/达梦数据库/tutorial-dameng-sql-agent.md` |

**逐字保留未动**：`custom_tools/dameng_sql.py`（含 `_preload_dmssl_libs()` 与三层 SQL 校验）、`nexau.json` 的 `excluded`、`download-whls.sh`、`.gitignore`。

> 注：`nexau.json` 的 `excluded` 平台**完全不解析**，只是打包端的约定（真正被消费的是 `agents` / `setup` / `backend` / `runtime.command`）。原样保留，不要写成「平台会按 excluded 排除文件」。

## 延伸

- 字段契约 / `${env.X}` 语义 / 密钥两条通路 → `../../references/agent-yaml-fields.md`
- 内置工具、沙箱预装依赖清单 → `../../references/builtin-tools.md`
- 表语义、业务口径怎么写进 SKILL → `03-text-to-sql`
- 把数据库能力挪到进程外、跨边界审计 → `04-mcp-server`
- 取数之后要出文档 / 报告（多工具组合） → `07-doc-generation`、`08-business-review`
