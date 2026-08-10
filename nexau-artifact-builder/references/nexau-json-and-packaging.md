# nexau.json 完整规范 + 打包与运行时文件系统边界

> **本文覆盖**：制品清单 `nexau.json` 的全部被平台真实消费的字段（`agents` / `setup` / `backend` / `runtime.command`，以及不被消费的 `excluded`）、`agents` 的上传期硬校验、打包硬约束（大小 / 条目类型 / 路径 / 格式）、以及运行时的目录布局与 skills 部署路径。
> **什么时候读它**：生成/修改 `nexau.json` 时；要装第三方依赖（尤其离线 whl）时；打包上传报 400/413 时；写 systemprompt 或脚本里出现文件路径时。
> agent.yaml 字段见 `references/agent-yaml-fields.md`；环境变量三通道见 `references/env-vars-and-secrets.md`。

---

## 0. 一句话结论表

| 问题 | 结论 |
|---|---|
| `nexau.json` 必须存在吗 | 必须，在制品根。缺失 → 上传 400 `Artifact validation failed: nexau.json is required` |
| 有 schema 校验吗 | **`agents` 有硬校验**（上传期 400，见 §2.0）；**其余字段没有** —— 只有下表列出的键被平台读，其余原样存进该版本的配置记录，写错/多写不报错 |
| 压缩包大小上限 | **100 MiB**，超限 413 |
| 能打软链吗 | **不能**。符号链接/设备/FIFO 一律 400 |
| `/agent` 能写吗 | Python Runtime 下 **只读挂载**；可写目录只有 `/home/user` 和 `/tmp` |
| setup 失败会阻止部署吗 | **不会**，只留一行 WARNING |
| skills 在沙箱里的路径 | `/home/user/.skills/<本地 skill 目录 basename>` |

---

# 上半部：nexau.json 完整规范

## 1. 字段总表

| 字段 | 类型 | 谁消费 | 不写会怎样 |
|---|---|---|---|
| `agents` | **必须是非空 JSON 对象** `{name: "path.yaml"}`（见 §2） | backend 上传期硬校验 + agent-runtime 加载期 | 缺失 / 是数组 / 是 `null` / 是空对象 → **上传直接 400**（见 §2.0） |
| `setup` | `string[]` | scheduler → runtime 容器 env `NEXAU_SETUP_COMMANDS` | 不跑任何安装命令 |
| `backend` | `"nexau" \| "python" \| "nexau-rs" \| "rust"` | backend publish 期，决定 runtime_image | 默认 Python Runtime |
| `runtime.flavor` | `"python" \| "rust"` | 同上，与 `backend` 交叉校验 | — |
| `runtime.command` | `string[]` | scheduler，覆盖默认启动命令 | 用镜像默认命令 |
| `excluded` | `string[]` | **无人消费**（见 §6） | 无影响 |

最小可用形态：

```json
{
  "agents": {
    "labor_law_qa": "agent.yaml"
  }
}
```

---

## 2. `agents` —— 在 NAC 上只有一种可用写法

### 2.0 结论先行：`{name: "相对路径.yaml"}`，别的都别用

```json
{ "agents": { "labor_law_qa": "agent.yaml" } }
```

> ⚠️ **`agents` 是 map，但「能声明多个」有运行期代价**：
> - 恰好 **1 个** agent 时，chat 请求不带 `agent` 字段，Runtime 自动选中它。
> - **≥2 个**时，每次 chat 的 body **必须**带 `agent: "<nexau.json 里的 key>"`，否则 **400** `Multiple agents registered, 'agent' parameter required`。
> - 名字写错是 **404** `Agent '<x>' not found`，别和上面那条 400 混。
> - 尤其阴：Playground 会自动带上 `agent` 所以一路是绿的，但平台「复制 API 脚本」生成的 curl/python/js **不带**这个字段，做 API 集成时才撞 400。
>
> **没有明确理由就只声明一个 agent**；要多个角色优先用 `sub_agents`（见 `references/mcp-and-subagents.md`）。

原因是 **两层校验的交集只剩这一种**：backend 在上传期就对 `agents` 做硬结构校验，任一条不满足 → **上传 400 `Artifact validation failed: <detail>`**，根本走不到 runtime。

| 上传期硬规则 | 违反时的报错（400） |
|---|---|
| `agents` 必须存在且是 **JSON 对象** —— 数组、`null`、字符串全不行 | `nexau.json missing or invalid 'agents' field (expected non-empty object)` |
| 对象**非空** | `nexau.json 'agents' field is empty — at least one agent must be declared` |
| 每个 value 必须是**字符串路径**，或含 `path` 键的对象（forward-compat，见下方 🚫） | `agents.<name>: expected string path, got <value>` |
| agent 名不含 `/ \ % ? #` 和控制字符（会作为 A2A URL 路径段） | `agent name contains a character that breaks A2A URL routing: ...` |
| 每个 declared 路径在**归档里真实存在且 size > 0** | `agent yaml files declared in nexau.json not found or empty in artifact:\n  - '<path>' (declared as agent '<name>')` |

两条上传路径都无条件跑这套校验：代理上传与直传 confirm；DevBox / draft 发布走的也是同一套。

> 路径匹配是**后缀匹配**：归档条目路径与声明值相等、以 `/<声明值>` 结尾、或写成 `./<声明值>`，三者都算命中。所以 tar 多包一层（`my-agent/agent.yaml` vs 声明 `agent.yaml`）在上传期也能通过，与 §10 的 init 压平行为一致。

### 2.1 runtime 侧的四种形态（**只有形态 1 能上到 NAC**）

runtime 加载器本身比上传校验宽松。列出来是为了看懂日志、排障和本地直跑 runtime，**不是给你选写法用的**。

| # | 形态 | 示例 | runtime 行为 | 能过 NAC 上传吗 |
|---|---|---|---|---|
| 1 | dict，值是路径字符串 | `{"qa": "agent.yaml"}` | 路径相对**制品根** `/agent` | ✅ **唯一可用** |
| 2 | dict，值是对象 | `{"qa": {"agent_yaml": "cfg/qa.yaml"}}` | 读 `agent_yaml`，缺省 `<name>.yaml` | 🚫 400（backend 只认 `path` 键，见下） |
| 3 | list of name | `{"agents": ["qa","vis"]}` | 在 `agents/<name>.yaml` 找 | 🚫 400（不是对象） |
| 4 | 既非 dict 也非 list（含 `null`） | `{"agents": null}` | 扫描 `agents/*.yaml`（非递归） | 🚫 400（不是对象） |

🚫 **形态 2 两头不讨好，绝对不要用**：backend 只从对象里取 **`path`** 键，而 Python runtime 只读 **`agent_yaml`** 键。写 `{"agent_yaml": "x.yaml"}` → 上传 400；改写成 `{"path": "x.yaml"}` → 上传能过，但 runtime 读不到 `agent_yaml`、回落成 `<name>.yaml`，**加载到一个你没指定的文件或直接找不到**。

### ⚠️ 三条必须记住的行为

1. **`agents` key 完全缺失 ≠ 自动扫描**（部分老文档说法相反，以平台实测行为为准）：key 缺失时加载器拿到的是一个空字典，空字典仍然是 dict → 走形态 1 分支 → 零个 agent → `ValueError: No agents found in /agent`。自动扫描只在 `agents` 存在但既不是 dict 也不是 list 时触发（例如显式 `"agents": null`）—— 而那种写法上传就被 400 拦了。**结论：`agents` 必写，且必须是非空对象。**
2. **路径写错在 NAC 上是上传期 400，不是运行期静默少一个 agent**。runtime 里确实有「找不到文件就只打一行 `Agent config not found: <path>` 警告后跳过」的分支，但上传校验已经保证了 declared 路径在归档里存在 —— 这条分支在正常 NAC 流程下基本不可达。真在 pod 日志里看到 `Agent config not found:`，说明 declared 路径与运行时解析出的路径不一致（典型是靠后缀匹配蒙混过上传的多层目录），按 §10 重新从项目目录内打包。
3. **全空才 raise**：一个 agent 都没加载到时才抛 `ValueError` —— 这是 runtime 的最后一道兜底。

> **Rust Runtime（`backend: "nexau-rs"`）语义不同，别照搬形态表**：清单只认 `{name: "path"}` 或 `[路径字符串 | {name, file}]`。三点差异：(a) 形态 2 的嵌套 dict 直接反序列化失败（未实测，由它接受的清单形状推断）；(b) **list 里的字符串是「路径」不是「名字」** —— `["qa"]` 解析成 `/agent/qa`（直接拼在制品根后面，再拿文件名去掉扩展名当 agent 名），不是 Python 的 `agents/qa.yaml`；(c) **declared yaml 不存在是硬错误**（报 `yaml file not found`），不像 Python 那样 warn 跳过；agents 整体为空时才只 warn。综合上传校验，**Rust runtime 也只用形态 1**。

---

## 3. `setup` —— 唯一的依赖安装入口

### 3.1 契约

| 项 | 事实 |
|---|---|
| 类型 | **必须是字符串数组**。不是数组 / 元素非字符串 → 被静默丢弃，不报错 |
| 注入位置 | **runtime 容器**的 env `NEXAU_SETUP_COMMANDS`（多条用 `\n` 拼接）。**不在 init 容器**——init 容器只负责下载解压，没有 python/pip |
| 执行时机 | runtime 进程启动**之前**，`cd /agent` 后逐行 `eval` |
| 失败语义 | 单条失败只打一行 `WARNING: setup command failed: <cmd>` —— **失败不中断部署** |
| 执行环境 | 整段命令是喂给 `while read` 循环逐行执行的 → 每条都跑在**子 shell** 里 |
| 触发频率 | **每次 pod 创建都重跑**（首次部署、扩缩容、滚动更新、节点驱逐后重建），脚本在容器 entrypoint 里 |

启动脚本的实际行为：`NEXAU_SETUP_COMMANDS` 非空时，先 `cd /agent`，再把它按行拆开逐条 `eval`；每条执行前往日志打一行 `>>> <命令>`，失败则打一行 `WARNING: setup command failed: <命令>` 后**继续下一条**，全部跑完打一行 `setup complete`。

### 3.2 🚫 四个必踩的坑

| 坑 | 为什么 | 正确做法 |
|---|---|---|
| **以为「部署成功 = 依赖装上了」** | setup 失败只打 WARNING，runtime 照常起，直到真正 `import` 时才炸，报错出现在 chat 期而不是部署期 | **每条安装命令后面跟一条自检**，见下方范例 |
| **`cd` / `export` / `source venv/bin/activate` 写在 setup 里** | 跑在管道子 shell 里，且 runtime 进程最终 `cd /home/user` 后才启动，子 shell 的 cwd/env 全丢 | 用绝对路径 + 显式 `--python /opt/venv/bin/python` 装进 runtime 已有的 venv |
| **往 `/agent` 写东西**（`pip install --target /agent/...`、生成缓存、改 yaml） | Python Runtime 下 `/agent` 是只读挂载 → `Errno 30 Read-only file system` | 写 `/home/user` 或 `/tmp` |
| **依赖从公网 pip 拉** | 每次 pod 重建都会重跑一遍；离线/信创环境根本没有出网 | 把 whl 打进制品，用 `--no-index --find-links /agent/<dir>` 离线装 |

### 3.3 ✅ 范例：离线安装达梦数据库驱动

制品里放一个装满 whl 的目录（`.whl` 是普通文件，不违反归档限制）：

```
my-agent/
├── nexau.json
├── agent.yaml
└── dmpython-airgap/
    ├── dmPython-2.5.32-cp312-cp312-manylinux_2_17_x86_64.whl
    └── ...（依赖的传递 whl 也要一起放）
```

```json
{
  "agents": { "dameng_sql_agent": "agent.yaml" },
  "setup": [
    "/usr/local/bin/uv pip install --python /opt/venv/bin/python --no-index --find-links /agent/dmpython-airgap dmpython==2.5.32",
    "/opt/venv/bin/python -c 'import dmPython; print(\"[setup-check] dmPython OK\", dmPython.__file__)'"
  ]
}
```

要点：

- `/opt/venv` 是 runtime 镜像自带的 venv，容器 PATH 前置 `/opt/venv/bin`，镜像里 `VIRTUAL_ENV=/opt/venv`，且该目录归容器运行用户所有（容器以非 root 的 `user` 身份跑），所以 `uv pip install` 有写权限。**显式写 `--python /opt/venv/bin/python` 最稳**，别依赖 VIRTUAL_ENV 被继承。
- `uv` 二进制确实在 `/usr/local/bin/uv`（runtime 镜像里预置，不用自己装）。
- **第二条自检命令是必需品**，不是可选装饰。它会在 pod 日志里留下 `>>> ...python -c 'import dmPython...'` 与结果；没有它你无法区分「装成功」和「装失败但部署绿了」。
- 平台的资源目录（resource catalog bundle）也是把 `bundle_dependencies.setup` 追加进 `nexau.json.setup`，官方示例给的就是同一形状的离线 `uv pip install --no-index --find-links` 命令。

---

## 4. `backend` —— 选运行时镜像

```json
{ "agents": {...}, "backend": "nexau" }
```

| 取值 | 含义 |
|---|---|
| `"nexau"` / `"python"` | Python Runtime（默认，本 skill 全部内容按它写） |
| `"nexau-rs"` / `"rust"` | Rust Runtime（agent-runtime-rs 镜像） |
| 其它任意值 | **publish 400** `unknown nexau.json.backend value '<x>'` |

`runtime.flavor` 是同一语义的第二个入口，但取值窄一档：只认 `"python"` / `"rust"`，其它 400。

🚫 **两者同时声明且不一致 → publish 直接 400**：

```
nexau.json.backend (nexau) is inconsistent with runtime.flavor (rust); ...
```

> 建议：**只写 `backend`，不写 `runtime.flavor`**，从源头消灭这个 400。
> `backend: "nexau-rs"` 还额外受一道平台准入开关控制，开关没开时 publish 直接被拒（报错文案里会点名 `NEXAU_BACKEND_RUNTIME_RS_EXECUTION_READY=true`）；开关开着但平台没配 Rust 镜像时另有一条 400。没有明确理由不要选 Rust runtime。

---

## 5. `runtime.command` —— 覆盖启动命令（escape hatch）

```json
{
  "agents": {...},
  "runtime": { "command": ["python", "-m", "my_custom_entry", "--port", "8100"] }
}
```

| 项 | 事实 |
|---|---|
| 类型 | `string[]`；数组内任一元素不是字符串 → **整个字段被丢弃** |
| 语义 | 每个元素被 shell-escape 后空格拼接，追加成 wrapper 脚本末尾的 `exec <cmd>` |
| 默认值 | Python 镜像：`python -m nexau_cloud_agent_runtime.cli --project-dir /agent --port ${PORT:-8100}`；Rust 镜像：`/app/bin` |
| 与 setup 的关系 | wrapper 脚本**总是**套上，所以写了 `runtime.command` 也照样执行 `setup` |

⚠️ 这是逃生舱，不是常规配置。写了它 = 你自己负责监听 `$PORT` 并实现平台的 chat 协议；99% 的制品**不应该**出现这个字段。

---

## 6. `excluded` —— 平台完全不解析

```json
{ "agents": {...}, "excluded": [".nexau/", ".env", "__pycache__/"] }
```

**🚫 不要写成「平台会按 excluded 排除文件」。** 核实结论：

- 平台服务端（backend / scheduler / agent-runtime / agent-runtime-rs / sandbox-manager / init 容器）**没有任何一处读它**，唯一出现的地方是一处测试用例的样例数据。
- NexAU SDK 侧也没有任何解析代码。
- 它只是随整个 JSON 原样存进该版本的配置记录（backend 上传期只会**额外追加**一个 `_agents_meta` 键做 A2A Agent Card 元数据；你写的键一个不改、一个不删）。

真实语义：**打包端（`nac` CLI / DevBox 导出）的约定**，由打包工具决定要不要遵守。服务端既不校验也不执行。

实际结论：
- 你手工 `tar` 打包时，`excluded` 里写什么都不会阻止文件进包 —— **必须在 tar 命令里自己 `--exclude`**。
- 保留它无害（cookbook 样例普遍带着），但**不要指望它保护 `.env` 不进制品**。凭证一律走环境变量，不进制品（见 `references/env-vars-and-secrets.md`）。

---

# 下半部：打包与运行时文件系统边界

## 7. 打包硬约束（三条 + 格式）

> 第四条硬约束是 `agents` 的结构与存在性校验，已在 §2.0 讲完，别漏。

条目级校验（软链 / 路径）在 backend 遍历归档时逐条跑，而且跑两遍：提取 `nexau.json` 时一遍，核对 declared agent yaml 时又一遍。任一条不满足 → 整个 publish 失败，不留半确认状态（直传路径还会尽力删掉刚传上去的对象存储文件）。

### 7.1 100 MiB 压缩包上限 → 超限 413

压缩包超过 **100 MiB** 即被拒，报文是 `Agent Artifact exceeds the 100MB compressed archive size limit.`，并带上实际字节数。这道检查在 4 个入口都会跑（代理上传、直传 confirm、运行前复查等），超限返回 **413 Payload Too Large**。

🚫 **别和 backend 的全局请求体上限 500 MB 混淆**。那是 HTTP 框架层的另一道限制；你能塞进 500 MB 的 body，但依然会在 100 MiB 处被 413 拒。

⚠️ **离线 whl 最容易撞这条**。manylinux 的科学计算 whl 体积很大（`pandas`+`numpy`+`scipy` 一组就可能过百 MB —— 量级经验值，不是实测数字），确实要补时只打**必需**的那几个 whl，并本地 `du -h` 确认。

⚠️ 打之前先确认**到底哪个环境缺**（两个环境依赖集不同，见 `references/custom-tools.md`）：`setup` 装进的是 **runtime 镜像的 `/opt/venv`**，只对 agent-runtime 进程内跑的 custom tool 有效；沙箱里 `run_shell_command` 跑的脚本用的是**沙箱镜像**自带的 venv，两者互不影响。runtime 镜像已含 `numpy` / `requests` / `httpx` / `PyMuPDF` / `Pillow` / `beautifulsoup4` / `psycopg2-binary` 等，但**不含 `pandas` / `scipy`**。

### 7.2 归档只允许普通文件和目录

归档里的每个条目只能是**普通文件**或**目录**，其余一律 400，报文形如：

```
unsupported tar entry `<path>`: only regular files and directories are allowed
```

zip 同规则（按条目的 unix 权限位判断类型）。

被拒的条目类型：**符号链接（含硬链接条目）、设备文件、FIFO、socket**。

🚫 **推论：`tar -czf` 打含软链的 `node_modules/` / `venv/` / `.venv/` 必然 400。** venv 的 `bin/python` 就是指向解释器的软链。要带依赖只能带 **whl 文件**（普通文件）+ `setup` 里现场安装，不能带已安装好的 venv 目录。

同时路径本身必须满足（tar 还额外要求路径是合法 UTF-8）：

| 禁止 | 报错 |
|---|---|
| 空路径 | `path must not be empty` |
| 含 NUL | `path must not contain NUL` |
| 以 `/` 开头（绝对路径） | `absolute paths are not allowed` |
| 含反斜杠 `\` | `backslash paths are not allowed` |
| Windows 盘符前缀（`C:`） | `Windows drive prefixes are not allowed` |
| 任意 `..` 路径段 | `parent traversal is not allowed` |
| 非 UTF-8 路径（tar） | `tar entry path must be valid UTF-8` |

⚠️ 在 Windows 或含中文文件名的环境打包时，用 `tar`/`zip` 的 UTF-8 模式；`.`、`./` 作为目录条目被特判放行。

### 7.3 必须含 nexau.json；多份时的择优规则

缺失 → **400** `Artifact validation failed: nexau.json is required`。

包里有多份 `nexau.json` 时：**深度更浅者优先；同深度按路径字符串字典序**（tar 与 zip 两条路径同语义）。深度只数常规路径段，根级 `nexau.json` 深度为 1。

⚠️ 这条在**多 agent / 带样例子目录**的制品里最容易踩：子目录里如果留了一份旧的 `nexau.json`，只要根目录那份还在就没事；但**根目录那份缺失时会静默取到子目录那份**，表现为「Playground 里 agent 列表不对」。打包前 `tar -tf a.tar | grep nexau.json` 确认只有一份。

### 7.4 支持的格式

`tar` / `tar.gz` / `zip`，**按魔数识别，不看扩展名**（zip 认 `PK\x03\x04` / `PK\x05\x06` / `PK\x07\x08`，gzip 认 `\x1f\x8b`；都不是就按裸 tar 解）。

init 容器解压端更宽松一档：用 `file -b` 探测，认 zip / tar / gzip / XZ / bzip2，未知类型先试 `tar -tf` 再试 `unzip -t`。**但上传端只认前三种**，所以 `.tar.xz` 走裸 tar 分支解析必然失败，在 backend 提取 config 阶段就被 400 挡住（推论，未构造 `.tar.xz` 实测；无论报 `failed to extract nexau.json` 还是 `nexau.json is required`，都是 400）。**统一用 `tar.gz`。**

推荐打包命令（从项目目录内打，不多包一层；见 §10，init 的压平行为其实也容忍多一层，但别依赖它）：

```bash
cd my-agent/
tar --exclude='.nexau' --exclude='.env' --exclude='__pycache__' \
    --exclude='.git' --exclude='node_modules' --exclude='.venv' \
    -czf ../my-agent.tar.gz .
```

---

## 8. 运行时路径速查

| 路径 | 是什么 | 可写？ |
|---|---|---|
| `/agent` | 制品解压根 | **Python Runtime 下只读**；仅 Rust Runtime 可写 |
| `/home/user` | runtime 进程 cwd；沙箱 HOME | ✅ 可写 |
| `/tmp` | 临时目录（`DISKCACHE_DIRECTORY=/tmp/.tool_cache`） | ✅ 可写 |
| `/opt/venv` | runtime 的 Python venv | ✅ 可写（目录归容器运行用户所有） |
| `/home/user/.skills/<dir>` | 沙箱内的 skills（见 §9） | 沙箱内可写 |

### ⚠️ 四条最容易搞混的路径规则

**(1) cwd 是 `/home/user`，不是 `/agent`。**
runtime 用 `--project-dir /agent` 拿项目（默认启动命令就是 `python -m nexau_cloud_agent_runtime.cli --project-dir /agent --port ${PORT:-8100}`），进程 cwd 却是 `/home/user`。任何在 custom tool 里写**裸相对路径** `open("data/x.json")` 的代码，打开的是 `/home/user/data/x.json`，**不是**制品里的文件。

读制品内文件的两种正确写法（等价，都能解析到 `/agent/...`）：

```python
from pathlib import Path
DATA = Path(__file__).resolve().parent.parent / "data" / "x.db"   # ✅ 推荐：锚定文件自身位置，不硬编码挂载点
DATA = Path("/agent/data/x.db")                                    # ✅ 也对，但硬编码 /agent，本地裸跑 NexAU 时挂
```

真正的禁令是**不能用裸相对路径**，不是「必须写死 `/agent`」。详见 `references/custom-tools.md` §1。

**(2) 但 agent.yaml 里的相对路径按「agent.yaml 所在目录」解析，不是 cwd。**
`system_prompt` / `tools[].yaml_path` / `skills[]` 走同一套解析规则，三选一：

- **绝对路径** → 原样使用；
- **含 `:` 的写法**（如 `pkg:res/x.yaml`）→ 按 Python 包资源解析；
- **其余（普通相对路径）** → 相对 **agent.yaml 所在的目录**解析。

于是：
- agent.yaml 在制品根 → `./skills/x` = `/agent/skills/x` ✅（本 skill 全部模板的布局）
- agent.yaml 在 `agents/` 子目录 → **同样写法变成 `/agent/agents/skills/x`** ❌

> 结论：**把 agent.yaml 放在制品根**，`nexau.json` 用 `{"name": "agent.yaml"}`。要放子目录就把所有相对路径同步下移。

**(3) 制品里的 Python 模块可以直接 import。**
runtime 启动时会把 `/agent` 和 `/agent/src` 前插进 `sys.path` 和 `PYTHONPATH`，所以 tool binding 写 `custom_tools.dameng_sql:run_sql` 能解析。注意 binding 的 import 根是**制品根**，与上面 (2) 的「agent.yaml 所在目录」是**两套不同基准**。

**(4) 沙箱是 session 级实体，不是 request 级 —— 上表只讲空间，这条讲时间。**
同一个 `session_id` 的后续每一轮**复用同一个沙箱**（先查 session 已绑定的沙箱，状态是 `running` / `paused` 就直接接着用）。推论：
- 沙箱 `/home/user` 下的中间产物、编译缓存、下载的依赖，**下一轮还在**，多步骤制品可以放心分轮做、不用每轮重来。
- **换 `session_id` = 一个全新的空沙箱**，上一个 session 的产物全部不可见。要跨 session 留东西只能落外部存储（对象存储 / 数据库），别指望沙箱文件系统。
- 已绑定的沙箱失联时 Runtime **按设计拒绝创建替身**，直接报 `Session is bound to sandbox <id>, but Runtime could not connect to it.` —— 处理办法是换新 `session_id`，不是重试。

---

## 9. skills 部署路径

### 9.1 形状固定，取值用 LoadSkill

**路径形状**（可以写死在 systemprompt 里）：

```
/home/user/.skills/<本地 skill 目录的 basename>
```

构成方式（已核实）：沙箱工作目录（默认就是 `/home/user`）+ `.skills/` + **本地 skill 目录名的 basename**。上传目标与运行期注册表用的是同一套拼法，两边不会不一致。

- 只有远程沙箱才上传；local sandbox 与 runtime 共享文件系统，这一步直接跳过。
- ⚠️ 精确说法：**agent.yaml 的 `skills[]` 里写的本地路径不会被就地改写**；带沙箱路径的是**运行期注册表里另建的那份 Skill 副本**。LoadSkill 读的正是这份副本，所以它的返回值就是沙箱路径。

**权威取值方式**：让模型调 `LoadSkill`，用返回体里的 `<SkillFolder>` 作为路径事实源 —— 返回体里会带一段 `<SkillFolder>/home/user/.skills/<dir></SkillFolder>`，并附一句 `Note that the paths mentioned in skill description are relative to the skill folder.`。

LoadSkill 的工具描述里本来就内嵌了每个 skill 的 `Skill Folder:` 绝对路径，所以模型在调用前就能看到。

### 9.2 两条都要写，不冲突

| 写在哪 | 写什么 | 为什么 |
|---|---|---|
| **systemprompt.md** | 显式声明「skills 根目录位于 `/home/user/.skills/`」 | 平台自带的制品静态校验器有正则强校验这句话，不写会被判不合规 |
| **systemprompt.md / SKILL.md 的操作规则** | 「用 `LoadSkill` 返回的 `<SkillFolder>` 拼后续文件路径，不要凭记忆猜」 | LoadSkill 返回值是唯一保证正确的来源 |

二者不矛盾：LoadSkill 返回的**就是** `/home/user/.skills/<目录名>`。声明形状是给校验器和模型的锚点，LoadSkill 是取值的权威方式。

🚫 **绝不要教模型猜 `/agent/skills/...`** —— 那是制品里的源路径，沙箱里不存在。

### 9.3 ⚠️ 最大的坑：两套 skills 路径不能混

| 场合 | 用哪个 | 例子 |
|---|---|---|
| **制品里**（`agent.yaml` 的 `skills:` 列表、打包目录结构） | `skills/`（**无点**，相对 agent.yaml 目录） | `skills: [./skills/labor_law]` |
| **运行时沙箱里**（systemprompt、SKILL.md 里让模型去读的路径、`run_shell_command` 的脚本路径） | `/home/user/.skills/`（**有点**，绝对路径） | `cat /home/user/.skills/labor_law/references/INDEX.md` |

任一处写反 = 运行期「找不到文件」。

另外：`.skills/` 是相对 `/home/user` 的隐藏目录。在 systemprompt 里写相对路径 `.skills/xxx` 只有在 cwd 恰好是 `/home/user` 时才成立 —— **一律写绝对路径**。

### 9.4 ⚠️ 目录 basename 决定路径，frontmatter `name` 决定调用名

这是两个独立的标识符：

| 标识符 | 来源 | 决定什么 |
|---|---|---|
| **目录 basename** | 本地 skill 目录名，如 `skills/pdf_to_md` | 沙箱路径 `/home/user/.skills/pdf_to_md`（只取目录名的 basename） |
| **frontmatter `name`** | `SKILL.md` YAML frontmatter 的 `name:`，如 `pdf-to-md` | 模型调用时写 `LoadSkill(skill_name="pdf-to-md")` |

cookbook 里就有目录 `pdf_to_md` / name `pdf-to-md` 的现成不一致案例。**强烈建议两者取同名**（都用下划线或都用短横线），否则模型很容易用 `name` 去拼路径而找不到文件。

> 每个 skill 目录**必须**有 `SKILL.md`，否则加载该 skill 时直接 `FileNotFoundError: SKILL.md not found in <folder>`。
> `references/` 内层索引框架不管叫什么，本 skill 一律用 **`INDEX.md`**（`SKILL.md` 是 skill 入口专用名，知识库层级不该占用）。规范要求「`references/` 非空时，根索引与每个非空子目录索引都必须存在」这一条本身是对的、必须遵守；⚠️ 但校验器规则文件把 `index_file` 配成了 `SKILL.md`（平台缺陷），用 `INDEX.md` 会被它误报。见 `artifact-spec-checklist.md` §8。

---

## 10. init 脚本的「单顶层目录压平」

如果你用 `tar -czf a.tar.gz my-agent/`（多包了一层目录），部署**仍然成功**：init 脚本发现 `/agent/nexau.json` 不存在时，会去看 `/agent` 下是不是恰好只有一个子目录、且那个子目录里有 `nexau.json`；是的话就把该子目录的内容（**含隐藏文件**）整体搬到 `/agent`，再删掉那层空壳目录。

触发条件（三条同时满足）：
1. `/agent/nexau.json` 不存在
2. `/agent` 下**恰好一个**子目录 —— 顶层散文件不计数，隐藏目录也不计数
3. 该子目录里有 `nexau.json`

上传期不受这一层影响：`agents` 声明的路径走**后缀匹配**，`my-agent/agent.yaml` 能匹配声明 `agent.yaml`；`nexau.json` 本身走「最浅路径优先」，多包的那一层里那份就是最浅的。

⚠️ 两个反例：
- 打包时多包一层 **且** 顶层还散落了别的目录 → 不压平 → runtime 启动脚本在检查 `/agent/nexau.json` 时直接失败退出，日志里只有一行 `ERROR: /agent/nexau.json not found.`。此时上传期不会报错（backend 只按最浅路径找 nexau.json、按后缀匹配找 agent yaml），**失败发生在部署期的 runtime pod 日志里**。
- 压平是 init 容器的兜底，backend 提取 config 时**不做压平**，走的是 §7.3 的「最浅路径优先」。两套逻辑在正常制品下结论一致，异常制品下可能分歧 —— **不要依赖压平，老老实实从项目目录内打包**。

---

## 11. 上传前自检清单

逐条勾，全绿再上传：

**nexau.json**
- [ ] 文件在制品**根目录**，且**全包只有这一份** —— `tar -tf a.tar.gz | grep nexau.json` 只输出一行
- [ ] `agents` 是**非空 JSON 对象**，值是**字符串路径** —— 不是数组、不是 `null`、不是 `{...: {"agent_yaml": ...}}`（这三种上传就 400，见 §2.0）
- [ ] `agents` 每个值指向的 yaml 文件**真实存在且非空** —— 逐个 `test -s`（空文件同样 400）
- [ ] agent 名不含 `/ \ % ? #` 与控制字符
- [ ] JSON 语法合法 —— `python -c 'import json,sys; json.load(open("nexau.json"))'`
- [ ] 若有 `setup`：是**字符串数组**；每条安装命令后面**跟了一条 `import` 自检**；没有 `cd`/`export`/`source`；没有往 `/agent` 写
- [ ] 若有 `backend`：取值在 `nexau`/`python`/`nexau-rs`/`rust` 内；**没有同时写 `runtime.flavor`**（写了就必须一致）
- [ ] 没指望 `excluded` 生效 —— 排除项已写进 `tar --exclude`

**打包**
- [ ] 包大小 < 100 MiB —— `ls -lh a.tar.gz`
- [ ] 包内**无符号链接 / 硬链接 / 设备节点** —— `tar -tvf a.tar.gz | grep -E '^[lhbcps]'` 应为空（zip 用 `unzip -l` 后逐项确认）
- [ ] 未打进 `.venv/` `node_modules/` `.git/` `__pycache__/` `.nexau/` `.env`
- [ ] 路径无 `..`、无绝对路径、无反斜杠、无非 UTF-8 文件名
- [ ] 格式是 `tar` / `tar.gz` / `zip`（**不要用 `.tar.xz`**）

**路径一致性**
- [ ] `agent.yaml` 在制品根；其中 `system_prompt` / `tools[].yaml_path` / `skills[]` 的相对路径都能从制品根解析到真实文件
- [ ] 每个 `skills/<dir>/` 下都有 `SKILL.md`，frontmatter 有 `name` + `description`
- [ ] `name` 与目录 basename **建议**同名（不是硬要求：basename 决定路径、`name` 决定 `LoadSkill` 调用名，
      两者可以不一致——`templates/07-doc-generation` 就是活例子）。若不同名，确认 systemprompt 里
      所有 `LoadSkill(...)` 用的是 `name`、所有路径用的是 basename
- [ ] systemprompt.md 里显式写了「skills 根目录位于 `/home/user/.skills/`」
- [ ] systemprompt.md / SKILL.md 里**没有出现** `/agent/skills/...` 这种沙箱内不存在的路径
- [ ] custom tool 的 Python 代码里，读制品文件用的是 `Path(__file__).resolve().parent…` 锚定（推荐）或绝对路径 `/agent/...`；
      **没有裸相对路径** `open("data/x.json")`（那打开的是 runtime cwd 下的 `/home/user/data/x.json`，见 §8 规则 (1)）

**部署后（不做等于没验）**
- [ ] runtime pod 日志里 grep `ERROR: /agent/nexau.json not found.` —— 应为空（有则是多包了一层且顶层不干净，见 §10）
- [ ] runtime pod 日志里 grep `Agent config not found:` —— 应为空
- [ ] 有 `setup` 时，grep `WARNING: setup command failed` —— 应为空；并确认自检命令的正向输出在日志里
