# nexau.json 完整规范 + 打包与运行时文件系统边界

> **本文覆盖**：制品清单 `nexau.json` 的全部被平台真实消费的字段（`agents` / `setup` / `backend` / `runtime.command`，以及不被消费的 `excluded`）、`agents` 的上传期硬校验、打包硬约束（大小 / 条目类型 / 路径 / 格式）、以及运行时的目录布局与 skills 部署路径。
> **什么时候读它**：生成/修改 `nexau.json` 时；要装第三方依赖（尤其离线 whl）时；打包上传报 400/413 时；写 systemprompt 或脚本里出现文件路径时。
> agent.yaml 字段见 `references/agent-yaml-fields.md`；环境变量三通道见 `references/env-vars-and-secrets.md`。

---

## 0. 一句话结论表

| 问题 | 结论 | 证据 |
|---|---|---|
| `nexau.json` 必须存在吗 | 必须，在制品根。缺失 → 上传 400 `Artifact validation failed: nexau.json is required` | — |
| 有 schema 校验吗 | **`agents` 有硬校验**（上传期 400，见 §2.0）；**其余字段没有** —— 只有下表列出的键被平台读，其余原样存进 DB `project_versions.config`，写错/多写不报错 | 校验：`artifacts.rs:202-271`、`:1104-1114`、`:1788-1798`；未知键透传： (`#[serde(flatten)] extra`) |
| 压缩包大小上限 | **100 MiB**，超限 413 | `artifacts.rs:74-101` |
| 能打软链吗 | **不能**。符号链接/设备/FIFO 一律 400 | `artifacts.rs:130-180` |
| `/agent` 能写吗 | Python Runtime 下 **只读挂载**；可写目录只有 `/home/user` 和 `/tmp` | — |
| setup 失败会阻止部署吗 | **不会**，只留一行 WARNING | — |
| skills 在沙箱里的路径 | `/home/user/.skills/<本地 skill 目录 basename>` | `nexau/archs/sandbox/base_sandbox.py:169,998-1005` |

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
> - **≥2 个**时，每次 chat 的 body **必须**带 `agent: "<nexau.json 里的 key>"`，否则 **400** `Multiple agents registered, 'agent' parameter required`（`server.py:3310-3313`）。
> - 名字写错是 **404** `Agent '<x>' not found`（`server.py:3302-3304`），别和上面那条 400 混。
> - 尤其阴：Playground 会自动带上 `agent` 所以一路是绿的，但平台「复制 API 脚本」生成的 curl/python/js **不带**这个字段，做 API 集成时才撞 400。
>
> **没有明确理由就只声明一个 agent**；要多个角色优先用 `sub_agents`（见 `references/mcp-and-subagents.md`）。

原因是 **两层校验的交集只剩这一种**：backend 在上传期就对 `agents` 做硬结构校验（`validate_agents_loadable`），任一条不满足 → **上传 400 `Artifact validation failed: <detail>`**，根本走不到 runtime。

| 上传期硬规则 | 违反时的报错（400） | 证据 |
|---|---|---|
| `agents` 必须存在且是 **JSON 对象** —— 数组、`null`、字符串全不行 | `nexau.json missing or invalid 'agents' field (expected non-empty object)` | `artifacts.rs:214-220`（`.as_object().ok_or_else(...)`） |
| 对象**非空** | `nexau.json 'agents' field is empty — at least one agent must be declared` | `artifacts.rs:222-226` |
| 每个 value 必须是**字符串路径**，或含 `path` 键的对象（forward-compat，见下方 🚫） | `agents.<name>: expected string path, got <value>` | `artifacts.rs:234-235` + `agent_path_from_value` `artifacts.rs:243-249` |
| agent 名不含 `/ \ % ? #` 和控制字符（会作为 A2A URL 路径段） | `agent name contains a character that breaks A2A URL routing: ...` | — |
| 每个 declared 路径在**归档里真实存在且 size > 0** | `agent yaml files declared in nexau.json not found or empty in artifact:\n  - '<path>' (declared as agent '<name>')` | `artifacts.rs:252-272`（`check_agents_present`），单测 `artifacts.rs:2223-2242` |

两条上传路径都无条件跑这套校验：代理上传 `artifacts.rs:1104-1114`、直传 confirm `artifacts.rs:1788-1798`（DevBox / draft 发布同样调用它：`devbox.rs:1484`、`artifact_drafts.rs:1187`）。

> 路径匹配是**后缀匹配**：`artifact_path_matches`（`artifacts.rs:366-373`）认 `path == decl`、`path.ends_with("/" + decl)`、`./decl`。所以 tar 多包一层（`my-agent/agent.yaml` vs 声明 `agent.yaml`）在上传期也能通过，与 §10 的 init 压平行为一致。

### 2.1 runtime 侧的四种形态（**只有形态 1 能上到 NAC**）

runtime 加载器本身比上传校验宽松：`cli.py:206-280` `load_agents_from_project`。列出来是为了看懂日志、排障和本地直跑 runtime，**不是给你选写法用的**。

| # | 形态 | 示例 | runtime 行为 | 能过 NAC 上传吗 |
|---|---|---|---|---|
| 1 | dict，值是路径字符串 | `{"qa": "agent.yaml"}` | 路径相对**制品根** `/agent`（cli.py:234-237） | ✅ **唯一可用** |
| 2 | dict，值是对象 | `{"qa": {"agent_yaml": "cfg/qa.yaml"}}` | 读 `agent_yaml`，缺省 `<name>.yaml`（cli.py:238-241） | 🚫 400（backend 只认 `path` 键，见下） |
| 3 | list of name | `{"agents": ["qa","vis"]}` | 在 `agents/<name>.yaml` 找（cli.py:254-265） | 🚫 400（不是对象） |
| 4 | 既非 dict 也非 list（含 `null`） | `{"agents": null}` | 扫描 `agents/*.yaml`（非递归，cli.py:267-275） | 🚫 400（不是对象） |

🚫 **形态 2 两头不讨好，绝对不要用**：backend 的 `agent_path_from_value` 只从对象里取 **`path`** 键（`artifacts.rs:243-249`），而 Python runtime 只读 **`agent_yaml`** 键（cli.py:240）。写 `{"agent_yaml": "x.yaml"}` → 上传 400；改写成 `{"path": "x.yaml"}` → 上传能过，但 runtime 读不到 `agent_yaml`、回落成 `<name>.yaml`，**加载到一个你没指定的文件或直接找不到**。

### ⚠️ 三条必须记住的行为

1. **`agents` key 完全缺失 ≠ 自动扫描**（与部分内部文档说法相反，以代码为准）：`agents_config = config.get("agents", {})`（cli.py:230）在 key 缺失时返回 `{}`，`{}` 是 dict → 走形态 1 分支 → 零个 agent → `ValueError: No agents found in /agent`（cli.py:277-278）。自动扫描只在 `agents` 存在但既不是 dict 也不是 list 时触发（例如显式 `"agents": null`）—— 而那种写法上传就被 400 拦了。**结论：`agents` 必写，且必须是非空对象。**
2. **路径写错在 NAC 上是上传期 400，不是运行期静默少一个 agent**。runtime 里确实有「找不到文件只 `logging.warning(f"Agent config not found: {agent_yaml}")` 跳过」的分支（cli.py:251-252），但上传校验已经保证了 declared 路径在归档里存在 —— 这条分支在正常 NAC 流程下基本不可达。真在 pod 日志里看到 `Agent config not found:`，说明 declared 路径与运行时解析出的路径不一致（典型是靠后缀匹配蒙混过上传的多层目录），按 §10 重新从项目目录内打包。
3. **全空才 raise**：`if not agents: raise ValueError(...)`（cli.py:277-278）—— 这是 runtime 的最后一道兜底。

> **Rust Runtime（`backend: "nexau-rs"`）语义不同，别照搬形态表**：清单只认 `{name: "path"}` 或 `[路径字符串 | {name, file}]`。三点差异：(a) 形态 2 的嵌套 dict 直接反序列化失败（未跑用例实测，从 untagged enum 推断）；(b) **list 里的字符串是「路径」不是「名字」** —— `["qa"]` 解析成 `/agent/qa`（`project_loader.rs:405-419` `project_dir.join(path)` + `file_stem` 取名），不是 Python 的 `agents/qa.yaml`；(c) **declared yaml 不存在是硬错误**（`RuntimeError::InvalidAgentYaml { message: "yaml file not found" }`，`project_loader.rs:443-448`），不像 Python 那样 warn 跳过；agents 整体为空才只 warn（`project_loader.rs:121-126`）。综合上传校验，**Rust runtime 也只用形态 1**。

---

## 3. `setup` —— 唯一的依赖安装入口

### 3.1 契约

| 项 | 事实 | 证据 |
|---|---|---|
| 类型 | **必须是字符串数组**。不是数组 / 元素非字符串 → 被静默丢弃（`as_array()?` + `filter_map(as_str)`），不报错 | `k8s.rs:2623-2634` `setup_commands_from_config` |
| 注入位置 | **runtime 容器**的 env `NEXAU_SETUP_COMMANDS`（多条用 `\n` 拼接）。**不在 init 容器**——init 容器只负责下载解压，没有 python/pip | `k8s.rs:1951-1957`；单测硬断言 `k8s.rs:3503-3555` `"NEXAU_SETUP_COMMANDS must NOT be on the init container"` |
| 执行时机 | runtime 进程启动**之前**，`cd /agent` 后逐行 `eval` | `scripts.rs:227-237` |
| 失败语义 | `eval "$cmd" \|\| log "WARNING: setup command failed: $cmd"` —— **失败不中断部署** | `scripts.rs:233` |
| 执行环境 | `echo "$NEXAU_SETUP_COMMANDS" \| while IFS= read -r cmd` → **子 shell** | `scripts.rs:230-235` |
| 触发频率 | **每次 pod 创建都重跑**（首次部署、扩缩容、滚动更新、节点驱逐后重建） | 同上，脚本在容器 entrypoint 里 |

启动脚本原文（`scripts.rs:227-237`）：

```sh
if [ -n "${NEXAU_SETUP_COMMANDS:-}" ]; then
  log "running setup commands..."
  cd /agent
  echo "${NEXAU_SETUP_COMMANDS}" | while IFS= read -r cmd; do
    if [ -n "$cmd" ]; then
      log ">>> $cmd"
      eval "$cmd" || log "WARNING: setup command failed: $cmd"
    fi
  done
  log "setup complete"
fi
```

### 3.2 🚫 四个必踩的坑

| 坑 | 为什么 | 正确做法 |
|---|---|---|
| **以为「部署成功 = 依赖装上了」** | setup 失败只打 WARNING，runtime 照常起，直到真正 `import` 时才炸，报错出现在 chat 期而不是部署期 | **每条安装命令后面跟一条自检**，见下方范例 |
| **`cd` / `export` / `source venv/bin/activate` 写在 setup 里** | 跑在管道子 shell 里，且 runtime 进程最终 `cd /home/user` 后才启动（`scripts.rs:273-276`），子 shell 的 cwd/env 全丢 | 用绝对路径 + 显式 `--python /opt/venv/bin/python` 装进 runtime 已有的 venv |
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

- `/opt/venv` 是 runtime 镜像自带的 venv，容器 PATH 前置 `/opt/venv/bin`，镜像里 `VIRTUAL_ENV=/opt/venv`且 `chown -R user:user ... /opt/venv` + `USER user`（`Dockerfile:126,147`），所以 `uv pip install` 有写权限。**显式写 `--python /opt/venv/bin/python` 最稳**，别依赖 VIRTUAL_ENV 被继承。
- `uv` 二进制确实在 `/usr/local/bin/uv`（`Dockerfile:53` `COPY --from=ghcr.io/astral-sh/uv:… /uv /usr/local/bin/uv`，单阶段构建，最终镜像里就有）。
- **第二条自检命令是必需品**，不是可选装饰。它会在 pod 日志里留下 `>>> ...python -c 'import dmPython...'` 与结果；没有它你无法区分「装成功」和「装失败但部署绿了」。
- 平台的资源目录（resource catalog bundle）也是把 `bundle_dependencies.setup` 追加进 `nexau.json.setup`，官方示例就是同一形状（ 字段定义、`:853-885` 解析 + doc 注释里的离线 `uv pip install --no-index --find-links` 示例）。

---

## 4. `backend` —— 选运行时镜像

```json
{ "agents": {...}, "backend": "nexau" }
```

| 取值 | 含义 | 证据 |
|---|---|---|
| `"nexau"` / `"python"` | Python Runtime（默认，本 skill 全部内容按它写） | `artifacts.rs:844-855` `normalize_backend_kind` |
| `"nexau-rs"` / `"rust"` | Rust Runtime（agent-runtime-rs 镜像） | 同上 |
| 其它任意值 | **publish 400** `unknown nexau.json.backend value '<x>'` | 同上 |

`runtime.flavor` 是同一语义的第二个入口，但取值窄一档：只认 `"python"` / `"rust"`，其它 400（`artifacts.rs:856-867` `normalize_flavor_kind`）。

🚫 **两者同时声明且不一致 → publish 直接 400**：

```
nexau.json.backend (nexau) is inconsistent with runtime.flavor (rust); ...
```
（`artifacts.rs:790-800`）

> 建议：**只写 `backend`，不写 `runtime.flavor`**，从源头消灭这个 400。
> `backend: "nexau-rs"` 还额外受生产准入 gate（`runtime_rs_execution_ready`）控制，gate 关时 publish 直接被拒（`artifacts.rs:810-819`，报错文案含 `NEXAU_BACKEND_RUNTIME_RS_EXECUTION_READY=true`；gate 开着但平台没配 Rust 镜像时另有一条 400，`artifacts.rs:821-827`）。没有明确理由不要选 Rust runtime。

---

## 5. `runtime.command` —— 覆盖启动命令（escape hatch）

```json
{
  "agents": {...},
  "runtime": { "command": ["python", "-m", "my_custom_entry", "--port", "8100"] }
}
```

| 项 | 事实 | 证据 |
|---|---|---|
| 类型 | `string[]`；数组内任一元素不是字符串 → **整个字段被丢弃**（`item.as_str()?` 直接 return None） | `k8s.rs:2591-2604` |
| 语义 | 每个元素被 shell-escape 后空格拼接，追加成 wrapper 脚本末尾的 `exec <cmd>` | `k8s.rs:2214-2228` |
| 默认值 | Python 镜像：`python -m nexau_cloud_agent_runtime.cli --project-dir /agent --port ${PORT:-8100}`；Rust 镜像：`/app/bin` | `k8s.rs:25-27,2606-2612` |
| 与 setup 的关系 | wrapper 脚本**总是**套上，所以写了 `runtime.command` 也照样执行 `setup` | `k8s.rs:2207-2209` 注释 |

⚠️ 这是逃生舱，不是常规配置。写了它 = 你自己负责监听 `$PORT` 并实现平台的 chat 协议；99% 的制品**不应该**出现这个字段。

---

## 6. `excluded` —— 平台完全不解析

```json
{ "agents": {...}, "excluded": [".nexau/", ".env", "__pycache__/"] }
```

**🚫 不要写成「平台会按 excluded 排除文件」。** 核实结论：

- 在平台后端代码库（backend / scheduler / agent-runtime）grep `"excluded"`（backend / scheduler / agent-runtime / agent-runtime-rs / sandbox-manager / artifact-init）**只命中一处，且是测试 fixture**。
- NexAU SDK（`nexau/`）里也没有任何解析代码。
- 它只是随整个 JSON 存进 DB `project_versions.config`（backend 上传期只会**额外追加**一个 `_agents_meta` 键做 A2A Agent Card 元数据，`artifacts.rs:1122-1126,1805-1809`；你写的键一个不改、一个不删）。

真实语义：**打包端（`nac` CLI / DevBox 导出）的约定**，由打包工具决定要不要遵守。服务端既不校验也不执行。

实际结论：
- 你手工 `tar` 打包时，`excluded` 里写什么都不会阻止文件进包 —— **必须在 tar 命令里自己 `--exclude`**。
- 保留它无害（cookbook 样例普遍带着），但**不要指望它保护 `.env` 不进制品**。凭证一律走环境变量，不进制品（见 `references/env-vars-and-secrets.md`）。

---

# 下半部：打包与运行时文件系统边界

## 7. 打包硬约束（三条 + 格式）

> 第四条硬约束是 `agents` 的结构与存在性校验，已在 §2.0 讲完，别漏。

条目级校验（软链 / 路径）在 backend 遍历归档时逐条跑：提取 `nexau.json` 时一遍（`require_config_from_archive` → `extract_config_from_tar` / `extract_config_from_zip`），核对 declared agent yaml 时又一遍（`validate_agents_loadable` → `scan_declared_agents_in_tar` / `_in_zip`，`artifacts.rs:288-302,327-341`），两处都调 `validate_tar_entry` / `validate_zip_entry`。任一条不满足 → 整个 publish 失败，不留半确认状态（直传路径还会 best-effort 删掉刚传上去的 S3 对象，`artifacts.rs:1794`）。

### 7.1 100 MiB 压缩包上限 → 超限 413

```rust
pub(crate) const MAX_ARTIFACT_SIZE: i64 = 100 * 1024 * 1024;   // artifacts.rs:74
const ARTIFACT_SIZE_LIMIT_MESSAGE: &str =                      // artifacts.rs:76-77
    "Agent Artifact exceeds the 100MB compressed archive size limit.";
```
`check_artifact_size` 在 4 个入口都会跑（代理上传、直传 confirm、运行前复查等，`artifacts.rs:113,1086,1561,1714`），超限返回 **413 Payload Too Large**，文案带实际字节数。

🚫 **别和 backend 的全局 body 上限 500 MB 混淆**（ `MAX_BODY_SIZE`）。那是 axum `DefaultBodyLimit`，是另一层；你能塞进 500 MB 的 body 但依然会在 100 MiB 处被 413 拒。

⚠️ **离线 whl 最容易撞这条**。manylinux 的科学计算 whl 体积很大（`pandas`+`numpy`+`scipy` 一组就可能过百 MB —— 量级经验值，非本仓事实），确实要补时只打**必需**的那几个 whl，并本地 `du -h` 确认。

⚠️ 打之前先确认**到底哪个环境缺**（两个环境依赖集不同，见 `references/custom-tools.md`）：`setup` 装进的是 **runtime 镜像的 `/opt/venv`**，只对 agent-runtime 进程内跑的 custom tool 有效；沙箱里 `run_shell_command` 跑的脚本用的是**沙箱镜像**自带的 venv，两者互不影响。runtime 镜像已含 `numpy` / `requests` / `httpx` / `PyMuPDF` / `Pillow` / `beautifulsoup4` / `psycopg2-binary` 等，但**不含 `pandas` / `scipy`**。

### 7.2 归档只允许普通文件和目录

```rust
// artifacts.rs:130-154 validate_tar_entry
if entry_type.is_file() || entry_type.is_dir() { return Ok(()); }
Err(format!("unsupported tar entry `{path}`: only regular files and directories are allowed"))
```
zip 同规则，额外查 `unix_mode() & 0o170000`（`artifacts.rs:156-180`）。

被拒的条目类型：**符号链接（含硬链接条目）、设备文件、FIFO、socket**。

🚫 **推论：`tar -czf` 打含软链的 `node_modules/` / `venv/` / `.venv/` 必然 400。** venv 的 `bin/python` 就是指向解释器的软链。要带依赖只能带 **whl 文件**（普通文件）+ `setup` 里现场安装，不能带已安装好的 venv 目录。

同时路径本身必须满足（ `normalize_artifact_path`，tar 还额外要求路径是合法 UTF-8，`artifacts.rs:133-135`）：

| 禁止 | 报错 |
|---|---|
| 空路径 | `path must not be empty` |
| 含 NUL | `path must not contain NUL` |
| 以 `/` 开头（绝对路径） | `absolute paths are not allowed` |
| 含反斜杠 `\` | `backslash paths are not allowed` |
| Windows 盘符前缀（`C:`） | `Windows drive prefixes are not allowed` |
| 任意 `..` 路径段 | `parent traversal is not allowed` |
| 非 UTF-8 路径（tar） | `tar entry path must be valid UTF-8` |

⚠️ 在 Windows 或含中文文件名的环境打包时，用 `tar`/`zip` 的 UTF-8 模式；`.`、`./` 作为目录条目被特判放行（`artifacts.rs:137-144`）。

### 7.3 必须含 nexau.json；多份时的择优规则

缺失 → **400** `Artifact validation failed: nexau.json is required`（`artifacts.rs:673-683`）。

包里有多份 `nexau.json` 时：**深度更浅者优先；同深度按路径字符串字典序**（`artifacts.rs:602-654` tar / `:696-745` zip，两条路径同语义）。深度只数常规路径段，根级 `nexau.json` 深度为 1。

⚠️ 这条在**多 agent / 带样例子目录**的制品里最容易踩：子目录里如果留了一份旧的 `nexau.json`，只要根目录那份还在就没事；但**根目录那份缺失时会静默取到子目录那份**，表现为「Playground 里 agent 列表不对」。打包前 `tar -tf a.tar | grep nexau.json` 确认只有一份。

### 7.4 支持的格式

`tar` / `tar.gz` / `zip`，**按魔数识别，不看扩展名**（分派 `artifacts.rs:662-672`；`is_zip_archive` `:685-690` 认 `PK\x03\x04` / `PK\x05\x06` / `PK\x07\x08`，`is_gzip_archive` `:692-694` 认 `\x1f\x8b`；都不是就按裸 tar 解）。

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

| 路径 | 是什么 | 可写？ | 证据 |
|---|---|---|---|
| `/agent` | 制品解压根（`TARGET_DIR`） | **Python Runtime 下只读**；仅 Rust Runtime 可写 | `k8s.rs:1762-1765`（`TARGET_DIR=/agent`）、`k8s.rs:2074-2082`（挂载 + `read_only = !is_rust_runtime_image(...)`）、`scripts.rs:162-169`（`chmod a+rX`，仅 `TARGET_WRITABLE=1` 时才 `a+rwX`） |
| `/home/user` | runtime 进程 cwd；沙箱 HOME | ✅ 可写 | `scripts.rs:273-276` `cd /home/user`；镜像 `WORKDIR /home/user`（`Dockerfile:149`） |
| `/tmp` | 临时目录（`DISKCACHE_DIRECTORY=/tmp/.tool_cache`） | ✅ 可写 | `runtime_env.rs:134-137` |
| `/opt/venv` | runtime 的 Python venv | ✅ 可写（`chown -R user:user` 且容器以 `USER user` 跑） | — |
| `/home/user/.skills/<dir>` | 沙箱内的 skills（见 §9） | 沙箱内可写 | `base_sandbox.py:169,998-1005` |

### ⚠️ 四条最容易搞混的路径规则

**(1) cwd 是 `/home/user`，不是 `/agent`。**
runtime 用 `--project-dir /agent` 拿项目（默认命令串 `k8s.rs:25-26` `python -m nexau_cloud_agent_runtime.cli --project-dir /agent --port ${PORT:-8100}`），进程 cwd 却是 `/home/user`（`scripts.rs:273-276`）。任何在 custom tool 里写**裸相对路径** `open("data/x.json")` 的代码，打开的是 `/home/user/data/x.json`，**不是**制品里的文件。

读制品内文件的两种正确写法（等价，都能解析到 `/agent/...`）：

```python
from pathlib import Path
DATA = Path(__file__).resolve().parent.parent / "data" / "x.db"   # ✅ 推荐：锚定文件自身位置，不硬编码挂载点
DATA = Path("/agent/data/x.db")                                    # ✅ 也对，但硬编码 /agent，本地裸跑 NexAU 时挂
```

真正的禁令是**不能用裸相对路径**，不是「必须写死 `/agent`」。详见 `references/custom-tools.md` §1。

**(2) 但 agent.yaml 里的相对路径按「agent.yaml 所在目录」解析，不是 cwd。**
`system_prompt` / `tools[].yaml_path` / `skills[]` 走同一个解析器：
```python
# nexau/archs/main_sub/config/config.py:88-112 _resolve_config_path
path = Path(raw_path)
if path.is_absolute(): return path        # 绝对路径原样（config.py:104-106）
if ":" in raw_path: ...                   # "pkg:res/x.yaml" 走 importlib.resources（:107-111）
return base_path / raw_path               # 否则相对 base_path（= agent.yaml 的 .parent，:112）
```
调用点：`system_prompt` `config.py:1109`、`tools[].yaml_path` `config.py:1211`、`skills[]` `config.py:869`。
- agent.yaml 在制品根 → `./skills/x` = `/agent/skills/x` ✅（本 skill 全部模板的布局）
- agent.yaml 在 `agents/` 子目录 → **同样写法变成 `/agent/agents/skills/x`** ❌

> 结论：**把 agent.yaml 放在制品根**，`nexau.json` 用 `{"name": "agent.yaml"}`。要放子目录就把所有相对路径同步下移。

**(3) 制品里的 Python 模块可以直接 import。**
runtime 启动时把 `/agent` 和 `/agent/src` 前插进 `sys.path` 和 `PYTHONPATH`（ `_prepend_to_python_path` / `_ensure_project_importable`，在 `load_agents_from_project` 开头调用，cli.py:220），所以 tool binding 写 `custom_tools.dameng_sql:run_sql` 能解析。注意 binding 的 import 根是**制品根**，与上面 (2) 的「agent.yaml 所在目录」是**两套不同基准**。

**(4) 沙箱是 session 级实体，不是 request 级 —— 上表只讲空间，这条讲时间。**
同一个 `session_id` 的后续每一轮**复用同一个沙箱**（：先查 session 已绑定的 sandbox_id，状态是 `running`/`paused` 就直接接着用）。推论：
- 沙箱 `/home/user` 下的中间产物、编译缓存、下载的依赖，**下一轮还在**，多步骤制品可以放心分轮做、不用每轮重来。
- **换 `session_id` = 一个全新的空沙箱**，上一个 session 的产物全部不可见。要跨 session 留东西只能落外部存储（对象存储 / 数据库），别指望沙箱文件系统。
- 已绑定的沙箱失联时 Runtime **按设计拒绝创建替身**，直接报 `Session is bound to sandbox <id>, but Runtime could not connect to it.`（`server.py:4586-4623`）——处理办法是换新 `session_id`，不是重试。

---

## 9. skills 部署路径

### 9.1 形状固定，取值用 LoadSkill

**路径形状**（可以写死在 systemprompt 里）：

```
/home/user/.skills/<本地 skill 目录的 basename>
```

推导链（全部已核实）：
```python
# nexau/archs/main_sub/agent.py:850-852 —— 上传目标与运行期注册表共用这一个函数
def _sandbox_skill_folder(self, local_folder: str) -> str:
    return str(Path(self.sandbox_manager.work_dir) / ".skills" / os.path.basename(local_folder))
```
- 远程沙箱才上传，local sandbox 共享文件系统直接跳过（`agent.py:845-848`）；上传对 `(本地目录, 沙箱目录)` 由 `_build_skill_upload_assets` 生成（`agent.py:854-864`）。
- `work_dir` 默认 `E2B_DEFAULT_WORK_DIR = "/home/user"`（`base_sandbox.py:169,192,216`）。
- 同款拼法在 SDK 的 `BaseSandbox.upload_skill` 里也有一份（`base_sandbox.py:998-1005`，`Path(self.work_dir)/".skills"/os.path.basename(skill.folder)`），结论一致。
- ⚠️ 精确说法：**`config.skills` 里的 `folder` 不会被就地改写**（`_build_runtime_skills` docstring：「without mutating `self.config.skills`」）；带沙箱路径的是**运行期注册表里新建的那份 Skill 副本**（`agent.py:866-885`，远程沙箱时 `folder = _sandbox_skill_folder(...)`）。LoadSkill 读的正是这份副本，所以返回值就是沙箱路径。

**权威取值方式**：让模型调 `LoadSkill`，用返回体里的 `<SkillFolder>` 作为路径事实源。
```python
# nexau/archs/main_sub/skill.py:187-201 load_skill
"Note that the paths mentioned in skill description are relative to the skill folder."   # :194
f"<SkillFolder>{skill.folder}</SkillFolder>"                                             # :197
```
LoadSkill 的工具描述里本来就内嵌了每个 skill 的 `Skill Folder:` 绝对路径（`skill.py:212`），所以模型在调用前就能看到。

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
| **目录 basename** | 本地 skill 目录名，如 `skills/pdf_to_md` | 沙箱路径 `/home/user/.skills/pdf_to_md`（`base_sandbox.py:1002` `os.path.basename`） |
| **frontmatter `name`** | `SKILL.md` YAML frontmatter 的 `name:`，如 `pdf-to-md` | 模型调用时写 `LoadSkill(skill_name="pdf-to-md")`（`skill.py:34-46` `Skill.from_folder` 读 frontmatter） |

cookbook 里就有目录 `pdf_to_md` / name `pdf-to-md` 的现成不一致案例。**强烈建议两者取同名**（都用下划线或都用短横线），否则模型很容易用 `name` 去拼路径而找不到文件。

> 每个 skill 目录**必须**有 `SKILL.md`，否则 `Skill.from_folder` 直接 `FileNotFoundError: SKILL.md not found in <folder>`（`skill.py:34-46`）。
> `references/` 内层索引框架不管叫什么，本 skill 一律用 **`INDEX.md`**（`SKILL.md` 是 skill 入口专用名，知识库层级不该占用）。规范要求「`references/` 非空时，根索引与每个非空子目录索引都必须存在」这一条本身是对的、必须遵守；⚠️ 但校验器规则文件把 `index_file` 配成了 `SKILL.md`（平台缺陷），用 `INDEX.md` 会被它误报。见 `artifact-spec-checklist.md` §8。

---

## 10. init 脚本的「单顶层目录压平」

如果你用 `tar -czf a.tar.gz my-agent/`（多包了一层目录），部署**仍然成功**：

```sh
# crates/nexau_cloud_scheduler/src/scripts.rs:139-159
if [ ! -f "${TARGET_DIR}/nexau.json" ]; then
  # 数 TARGET_DIR 下的子目录
  if [ "$SUBDIR_COUNT" -eq 1 ] && [ -f "${SINGLE_SUBDIR}/nexau.json" ]; then
    cp -a "${SINGLE_SUBDIR}/." "${TARGET_DIR}/"   # 含隐藏文件
    rm -rf "${SINGLE_SUBDIR}"
  fi
fi
```

触发条件（三条同时满足）：
1. `/agent/nexau.json` 不存在
2. `/agent` 下**恰好一个**子目录 —— 顶层散文件不计数，`*` glob 也不含隐藏目录（`scripts.rs:140-148`）
3. 该子目录里有 `nexau.json`

上传期不受这一层影响：`agents` 声明的路径走**后缀匹配**（`artifacts.rs:366-373`），`my-agent/agent.yaml` 能匹配声明 `agent.yaml`；`nexau.json` 本身走「最浅路径优先」，多包的那一层里那份就是最浅的。

⚠️ 两个反例：
- 打包时多包一层 **且** 顶层还散落了别的目录 → 不压平 → runtime 启动脚本在 `if [ ! -f "/agent/nexau.json" ]` 处直接 `exit 1`（`scripts.rs:220-223` `ERROR: /agent/nexau.json not found.`）。此时上传期不会报错（backend 只按最浅路径找 nexau.json、按后缀匹配找 agent yaml），**失败发生在部署期的 runtime pod 日志里**。
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
