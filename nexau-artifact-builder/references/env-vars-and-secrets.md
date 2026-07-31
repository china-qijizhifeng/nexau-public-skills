# 环境变量与密钥注入（三条通路）

**本文覆盖**：agent.yaml 里的 `${env.X}` 插值机制、NAC 平台的 runtime / sandbox 两种 env scope、制品内的 `runtime.env` / `sandbox.env` 声明文件、chat 请求的 `variables` 三通道，以及「密钥该走哪条路、代码里怎么读」的决策表。
**什么时候读**：制品需要任何外部凭证（API token / AK-SK / 数据库口令）时；custom tool 或沙箱脚本 `os.getenv()` 读不到值时；agent 加载期报 `Environment variable 'X' is not set` 时；本地跑通、部署到云上就挂时。

> 一句话先行：**「CLI / 沙箱脚本读不到密钥」不是平台缺陷，是选错了通路**。给沙箱进程用的密钥要建成 **sandbox scope**，给 agent.yaml 插值用的要建成 **runtime scope**，两者互不可见。

---

## 1. 三条通路总表（全文骨架）

| # | 通路 | 配置在哪 | 值最终落到哪 | 谁能读到 | 谁读不到 |
|---|---|---|---|---|---|
| ① | agent.yaml 的 `${env.X}` | 直接写在 agent.yaml 文本里 | **只替换进配置文本**，不新增任何进程环境变量 | agent.yaml 自己的字段值（model / extra_kwargs / system_prompt 路径 …） | 任何进程的 `os.environ`；沙箱 shell |
| ② | **runtime scope** env var | `POST /api/projects/{id}/env-vars?scope=runtime`；或制品根的 `runtime.env` 文件 | agent-runtime **Pod 容器 env** | custom_tools 的 Python 函数 `os.getenv()`；`${env.X}` 从这里取值 | 沙箱里的 shell / 脚本 / CLI（云端） |
| ③ | **sandbox scope** env var<br>或 per-request `variables.sandbox_env` | `?scope=sandbox`；制品根的 `sandbox.env` 文件；或 chat body 的 `variables.sandbox_env` | 沙箱内**每条命令的 per-command env** | 沙箱 shell 的 `$VAR`、沙箱内脚本/CLI 的 `os.environ`；runtime 侧 `agent_state.get_sandbox_env()` | agent.yaml 的 `${env.X}`；custom_tools 的 `os.getenv()` |

②③ 的分叉点是一行代码：`lib.rs:726-729` —— scheduler 只把 `effective_env.runtime` 展开成 Pod env，**`effective_env.sandbox` 在此处被直接丢弃**，走 Gateway 的另一条链路。

---

## 2. ① agent.yaml 的 `${env.X}`：加载期整文本正则替换

**唯一实现**：`nexau/archs/main_sub/utils/common.py:78-95`（Python runtime 主路径）

```python
env_pattern = re.compile(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}")
def _replace_env(match):
    env_name = match.group(1)
    if env_name not in os.environ:
        raise ConfigError(f"Environment variable '{env_name}' is not set")   # common.py:88-89
    return os.environ[env_name]
config_text = env_pattern.sub(_replace_env, config_text)   # common.py:92
loaded_config = yaml.safe_load(config_text)                # common.py:95 ← 替换发生在解析【之前】
```

### 必须记住的 6 条硬规则

| 规则 | 后果 | 证据 |
|---|---|---|
| 替换发生在 `yaml.safe_load` **之前**，对**整份文件文本**做 | 🚫 **注释里的 `${env.X}` 也会被解析**。`# TODO: 改回 ${env.OLD_KEY}` 这一行能让整个 agent 加载失败 | common.py:92 早于 :95 |
| 变量未设置 = **加载期 ConfigError 硬失败** | 用户看到 `Error loading configuration from /agent/agents/x.yaml: Environment variable 'FOO' is not set` | common.py:88-89 + `config/schema.py:153,183` |
| **不支持默认值语法** `${env.X:-default}` | 正则不匹配 → 不报错、**静默留成字面量字符串** `'${env.X:-default}'`（比报错更坏：到调 LLM 时才炸） | common.py:84 字符类只含 `[A-Za-z0-9_]` |
| **不支持转义**，`$${env.X}` 照样替换 | 无法在 agent.yaml 里写出一个字面的 `${env.X}` | common.py:84-92 无转义分支 |
| 插值逻辑**只读 `os.environ`，从不写回** | 写了 `${env.X}` 不会让任何子进程 / 沙箱多出一个环境变量 | 全框架对 `os.environ[...]` 唯一的下标访问是 common.py:90 的**读**；`grep -rnE 'os\.environ\[[^]]*\][[:space:]]*=[^=]\|environ\.setdefault\|environ\.update\|putenv' nexau/` 零命中。<br>唯一会改 `os.environ` 的是 `dotenv.load_dotenv()`（config.py:51 / agent.py:576），那是读本地 `.env`，与 `${env}` 无关 —— 见第 7 节 |
| 值是**文本注入**，会被 YAML 重新推断类型 | `123`→int、`yes`→bool、空串→None、含 `: ` → ScannerError、含换行 → 结构被劈开、以 `*` 开头 → ComposerError | common.py:92 + :95 |

**防坑写法**：一律加引号 `model: "${env.LLM_MODEL}"` 保住字符串类型（引号救不了值里含双引号的情况）。

### 只有 agent.yaml 家族支持插值

`tools/*.tool.yaml`、`SKILL.md` frontmatter、plugin manifest 全是裸 `yaml.safe_load`；`nexau.json` 是 `json.load`。在这些文件里写 `${env.X}` 得到的就是一个普通字符串，**不解析也不报错**。sub-agent 的 yaml 走 `AgentConfig.from_yaml` 递归，会各自独立插值一次。

### NAC 上 `${env.LLM_*}` 解析出来的是什么

| key | runtime pod 里的实际值 | 证据 |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:<sidecar llm_port>/v1` | — |
| `LLM_API_KEY` | 字面量 `placeholder-sidecar-injected`；runtime 进程启动时**若** `NEXAU_AGENT_RUNTIME_LLM_BASE_URL` 已设置，会再改写成 `sk-placeholder` | runtime_env.rs:307； |
| `LLM_MODEL` | scheduler 专为这个占位注入的**兜底 model**，**仅当能解析出兜底 model 时才存在** | `runtime_env.rs:533-537` |
| `LLM_API_TYPE` | **不存在** —— 平台不注入它 | 同上，只注入 BASE_URL / API_KEY / MODEL |

推论（agent 生成制品时必须遵守）：
- 🚫 **不要写 `${env.LLM_API_TYPE}`** —— 未设置 → 直接 ConfigError 加载失败。
- ⚠️ `${env.LLM_MODEL}` 在「项目一张可见模型卡都没有」时**这个 env 不存在**，agent 加载失败。
- ℹ️ 打印 `LLM_API_KEY` 排查会拿到 placeholder，**这是设计如此不是 bug**，真凭证只在 sidecar 容器（`NEXAU_AGENT_RUNTIME_SIDECAR_*` 前缀）。

### Rust runtime（`backend: "nexau-rs"`）语义不同

`nexau.json` 写 `"backend": "nexau-rs"`（或别名 `"rust"`）时走 Rust runtime（ `resolve_backend`）。差异：

- 缺变量在 **readiness 期一次性列全**（`project_loader.rs:250` `validate_required_env_placeholders`），不是加载到哪炸到哪；文案 `missing required environment variable... ` + hint `add the listed keys to the version/environment runtime-scope env vars and redeploy`（`:155-157`、`:277`）。
- 该校验器**扫的是 `serde_yaml::Value` 解析树而不是原始文本**（`:282` `collect_env_placeholders_from_yaml` → `:288` `collect_env_placeholders` 只递归 String / Sequence / Mapping / Tagged → `:306` `collect_env_placeholders_from_str`），所以**注释里的 `${env.X}` 不会被它算成必需变量**。

⚠️ 但 `nexau-rs` crate 自身的插值实现不在本仓内（本仓只有 `backend.rs` 那层 trait wrapper），**未核实它是否也对注释免疫**。**写制品时一律按 Python runtime 的严格行为写**（假设注释里的 `${env.X}` 也会炸），这样两条链路都安全。

---

## 3. ② runtime scope：进 Pod env，给 custom_tools 用

- 配置：`POST /api/projects/{id}/env-vars?scope=runtime`（项目级，路由挂载见 `mod.rs:191`）或 `/api/projects/{id}/environments/{env_name}/env-vars?scope=runtime`（环境级）。`?scope=` 缺省按 runtime 处理（`env_vars.rs:113-120` `resolve_scope`）并回 `Deprecation: true` + `Sunset` header（`:122-127` `add_deprecation_headers`）。
- key 只允许 ASCII 字母数字和下划线、≤255 字符（env_vars.rs:65-76）。
- 落点：scheduler 取 `effective_env.runtime` 作 `user_env`，经 `merge_runtime_env` 展开成 agent-runtime **Pod 容器 env**（`lib.rs:1769`、`:2011`）。
- 读法：
  - custom tool 的 Python 函数**在 agent-runtime 进程内直接调用**（`nexau/archs/tool/tool.py:541` import + `:579` `impl(**filtered_params)`），所以裸 `os.getenv("MY_TOKEN")` 读到的就是 runtime scope。
  - agent.yaml 的 `${env.MY_TOKEN}` 也从这里取值。

### ⚠️ 平台保留键永远压过用户 runtime env

`runtime_env.rs:280-293`：

```rust
let mut out = user_env.clone();          // 先铺用户 env
out.insert("PORT".to_string(), port_value);
for (k, v) in platform_base { out.insert(k.clone(), v.clone()); }   // 平台覆盖写
```

`platform_base` 的实际内容见 `runtime_env.rs:102-270` `platform_env_base`，逐条核实过的保留键（撞上就被**静默覆盖，不报错**）：

| 保留键 | 行号 |
|---|---|
| `PORT` | runtime_env.rs:288（`merge_runtime_env` 直接写） |
| `PATH` | :124-127（值固定为 `/opt/venv/bin:/usr/local/bin:...`） |
| `DISKCACHE_DIRECTORY` | :134-137（`/tmp/.tool_cache`） |
| `LLM_BASE_URL` / `LLM_API_KEY` | :300-310 `platform_llm_env_for_runtime`，由 :245-247 并进 |
| `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | :249-261（API 层本来也 400 拦截） |
| `NEXAU_CLOUD_*` / `NEXAU_AGENT_RUNTIME_*` / `NEXAU_SANDBOX_DOMAIN`(:241) / `NEXAU_LOG_LEVEL` / `NEXAU_WEB_PROXY_URL`(:117) / `NEXAU_MEMORY_LOG_INTERVAL` … | :114-241 散布 |
| `LLM_MODEL` / `NEXAU_AGENT_RUNTIME_LLM_*` | `lib.rs:1784-1791` —— 在 `merge_runtime_env` **之后**才插入，同样压过用户值 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_SERVICE_NAME` | :264-269（仅当 scheduler 自身有该 env 时） |

**自定义 key 一律加自有前缀（如 `MYAPP_`）避让**；尤其别用 `NEXAU_` / `LLM_` / `LANGFUSE_` / `OTEL_` 开头。

---

## 4. ③ sandbox scope / `variables.sandbox_env`：进沙箱进程，给脚本和 CLI 用

**完整链路（逐跳都已核实）**：

| 跳 | 代码位置 | 做了什么 |
|---|---|---|
| 1 | （router）+ `:113-120`（`?scope=sandbox` 解析） | 建 sandbox scope 变量 |
| 2 |  `build_env_snapshot` → `:114` `serialize_resolved_env` | deploy 时冻结进 `project_versions.resolved_env` |
| 3 |  `resolve_sandbox_env_from_version` | Gateway 从快照读 `.sandbox` |
| 4 |  `merge_governance_sandbox_env`（调用点 `handlers/chat.rs:701,710`） | merge 进 `variables.sandbox_env`，**per-request 优先**（`:50` `entry().or_insert_with`，已有 key 不被治理值覆盖） |
| 5 | — | `create_kwargs["envs"] = user_vars` → `Sandbox.create(envs=...)` |
| 6 | `nexau/archs/main_sub/agent.py:804-807`（create 期：`merged_envs = {**sandbox_config.envs, **self._variables.sandbox_env}`）/ `:1072-1077`（每次 run 期：`sandbox_instance.envs = {**sandbox_instance.envs, **effective_variables.sandbox_env}`） | 变量并进 sandbox 实例的 `envs` |
| 7 | `nexau/archs/sandbox/base_sandbox.py:520-536` `_merge_envs` → `e2b_sandbox.py:674`（background）/ `:775`（foreground）`commands.run(..., envs=self._merge_envs(envs))` | 逐条塞进每次命令调用（**前台、后台两条路径都带**） |
| 8 | — | `for (k, v) in envs { command.env(k, v); }` ← **落到子进程 OS 环境** |

**结果**：沙箱 shell 的 `$MY_TOKEN`、沙箱内 Python 脚本的 `os.environ["MY_TOKEN"]`、沙箱内 CLI 工具读环境变量 —— **全都能读到**。

runtime 侧要读同一个值，用 `agent_state.get_sandbox_env("MY_TOKEN")` / `agent_state.all_sandbox_env`（`nexau/archs/main_sub/agent_state.py:171-191`）。

### ⚠️ 关键边界：K8s 非 DevBox 沙箱**不会**把它写进 Pod 容器 env

`k8s.rs`：`build_pod`（:931）到 `build_devbox_pod`（:1855）之间 **grep `config.env_vars` 零命中**；全文命中只有 `:1963`（DevBox 路径 `if let Some(user_env) = &config.env_vars`）与 `:2889` / `:2929`（`create_from_template` 里纯透传进 `SandboxCreateConfig`）。Docker backend 才另行写进容器 env。

⚠️ 由此推出一个链路事实：**第 5 跳的 `Sandbox.create(envs=...)`（以及 `e2b_sandbox.py:2336` `envs=self.envs or None`）在 K8s 非 DevBox 路径上到 Sandbox Manager 就被丢弃了**；真正把变量送进沙箱进程的是第 7 / 8 跳的 per-command env。

推论（必须写进 systemprompt / 脚本约定）：

- ✅ 通过 `run_shell_command` 等 SDK 工具启动的进程 → 能读到（走第 8 跳的 per-command env）。
- 🚫 **沙箱里长驻的、非 SDK 启动的进程读不到** —— 比如你自己 `nohup ... &` 起的守护进程、或在变量注入之前就已经在跑的进程。需要密钥的守护进程要么由 SDK 工具重新拉起，要么在启动命令里显式 `MY_TOKEN=$MY_TOKEN cmd` 传递。

### 平台强制注入的两个值

| 通道 | key | 值 | 证据 |
|---|---|---|---|
| runtime_vars | `NEXAU_SESSION_ID`（有 token 时另加 `NEXAU_SESSION_TOKEN`） | 当前 session id | `server.py:865` |
| sandbox_env | `NEXAU_UPLOADED_FILES_DIR` | `/home/user/uploads` | `server.py:368,5823,6621` |

---

## 5. 制品内声明：`runtime.env` / `sandbox.env` 文件

制品**根目录**可以放两个 dotenv 风格文件，deploy / redeploy / promote 时被 backend 读出来，作为**最高优先级 overlay** 叠加到项目级 + 环境级 env 之上，写进 `resolved_env` 快照（ `read_version_env_file_overrides_from_artifact`、`:1038-1047` `env_overlay_from_artifact`、`:109` `effective.merge(artifact_overlay)`）。

| 文件 | 落到哪个 scope |
|---|---|
| `runtime.env` | runtime scope（②） |
| `sandbox.env` | sandbox scope（③） |

解析规则（`versions.rs:1074-1112` `parse_env_file` + `:1049-1072` `parse_env_file_value`）：

| 语法 | 行为 |
|---|---|
| 空行、`#` 开头整行 | 跳过 |
| `export KEY=value` | 允许，`export ` 前缀被剥掉 |
| 行内没有 `=` | **400** `runtime.env:{行号} is missing '='`（versions.rs:1086-1090） |
| 行以 `=` 开头（key 为空） | **400** `runtime.env:{行号} has an empty env var key`（versions.rs:1091-1095） |
| key 含 ASCII 字母数字下划线以外字符 / >255 | **400** `runtime.env:{行号} has invalid env var key 'X'`（versions.rs:1097-1101） |
| `KEY="a\nb"` | 双引号：处理 `\n` `\r` `\t` `\"` `\\` 转义 |
| `KEY='a b'` | 单引号：原样取内容，不处理转义 |
| `KEY=abc #comment`（`#` 前有空格） | 值被截断成 `abc`；`abc#def`（无空格）不截断 |
| 同名 key 出现多次 | 后者覆盖前者（BTreeMap 累积） |

约束与警告：
- 同样受 `guard_special_key_scope` 拦截（`versions.rs:1005-1028`）：`LANGFUSE_*` 任何 scope 400；`LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` 放进 `sandbox.env` 400。
- 这两个文件**不写 `environment_env_vars` 表**，只作为部署时的 overlay —— 制品里删掉某个 key，重新部署后旧 key 不会残留。
- 🚫 **不要把真实密钥写进 `runtime.env` / `sandbox.env`**：文件在 tar 包里，凭证随制品分发 = 安全事故。这两个文件适合放**非敏感默认值**（feature flag、超时、外部服务的公开 base_url）；真凭证走 API 建 env var，或 per-request `variables`。
- ⚠️ 匹配是「路径结尾匹配」（`versions.rs:1236-1239` `archive_path_matches`：`entry == expected || entry.ends_with("/runtime.env")`），子目录里同名文件也会命中。**只在制品根放一份**，别在示例目录里再塞一个 `runtime.env`。

---

## 6. 选型口诀 + 密钥决策表

> **给 agent.yaml 插值 → runtime scope；给沙箱脚本 / CLI → sandbox scope；两者互不可见。**

| 我要给谁用这个密钥 | 用哪条通路 | 代码里怎么读 |
|---|---|---|
| agent.yaml 的字段（如 tool `extra_kwargs` 的 token、某个 base_url） | **runtime scope** | agent.yaml 写 `"${env.MY_TOKEN}"`（加引号） |
| custom tool 的 Python 函数（跑在 agent-runtime 进程内） | **runtime scope** | 函数里 `os.getenv("MY_TOKEN")` |
| 沙箱里用 `run_shell_command` 跑的脚本 / CLI | **sandbox scope** | shell 里 `$MY_TOKEN`；脚本里 `os.environ["MY_TOKEN"]` |
| 只对某一次会话生效的临时凭证（终端用户自带 token） | per-request `variables.sandbox_env`（沙箱用）或 `variables.runtime_vars`（runtime 用） | 沙箱同上；runtime 用 `agent_state.get_variable("...")` |
| 同一个密钥两边都要用 | **建两份**（runtime + sandbox 各一条同名变量） | 分别按上面两行读 |
| **非敏感**默认值，想随制品一起走 | 制品根的 `runtime.env` / `sandbox.env` | 同对应 scope |
| LLM 的 key / base_url | **谁都不要建** —— 平台通过 sidecar 注入 | agent.yaml 里连 `llm_config` 都可以整段省略 |

⚠️ 密钥**绝不能**写进 agent.yaml 字面量、`llm_config.api_key`、`runtime.env`/`sandbox.env`，或任何进 tar 包的文件 —— 凭证进制品即随制品分发 = 安全事故。

> 补充说明：backend 的上传/部署校验（ 的 `validate_*` 系列）**并不会**替你拦住字面量密钥 —— 它只查归档路径、tar/zip entry 合法性和 agents 可加载性。别指望平台兜底。
>
> 唯一会拦字面量密钥的是 **A4A 制品静态校验器**（就在本仓 `builtin-agents/Agent4Agent/skills/artifact-verifier/scripts/`）：它对顶层 `llm_config.api_key` 的非空字面量判 error `agent.llm_config.api_key.literal`（`artifact_static_validator.py:324-331`，值里含 `${` 则豁免）。但两点边界要记牢：① 它**不是上传硬门**，Backend 链路根本不调用它（见 `artifact-spec-checklist.md` §0）；② 它只取 `agent_yaml.get("llm_config")`，**middleware params / `fallback_providers` / `extra_kwargs` 里的字面量密钥一概扫不到**（见 `llm-config.md` §7.1）。

---

## 7. ⚠️ 本地能读到 ≠ 云上能读到（本地调通、上云就挂的头号来源）

| 沙箱后端 | 是否继承 runtime 进程的 `os.environ` | 证据 |
|---|---|---|
| **LocalSandbox**（本地 CLI 调试） | **会** —— `{**os.environ, **merged}`；`merged` 为 None 时直接返回 None 让子进程继承父进程环境 | `nexau/archs/sandbox/local_sandbox.py:147-163` |
| **E2B / K8s 沙箱**（云端） | **不会** —— 只带 `self.envs + per-call envs` | `base_sandbox.py:520-536` `_merge_envs`；`e2b_sandbox.py:2336` `envs=self.envs or None` |

所以：**本地 `.env` 里放一个 token、沙箱脚本能读到，不代表云上能读到**。云上只有第 4 节那条链路送进去的变量才存在。

框架会在启动路径上 `dotenv.load_dotenv()`（`nexau/archs/main_sub/config/config.py:51` 模块级 + `agent.py:576`），本地 `.env` 因此会喂给 `${env.X}` 和 runtime 进程。**这只是本地行为，因为 `.env` 被 `nac` CLI 的打包器硬编码排除在制品之外**（排除清单含 `".env"`，并有回归测试覆盖）。推论有两条：

- 云上不会有 `.env` 帮你兜底 —— 每个 `${env.X}` 都必须有对应的 runtime scope 变量。
- 反过来也别指望「把 `.env` 塞进制品」当密钥通路：它根本不会被打进 tar。要随制品走的**非敏感**默认值请用第 5 节的 `runtime.env` / `sandbox.env`。

**自检做法**：本地验证密钥时，让脚本打印相关前缀的 `os.environ` key 列表，确认它来自你显式注入的通道，而不是"碰巧继承到了"。

---

## 8. 硬性禁令（写了会被 400 拒 / 被静默覆盖）

`env_vars.rs:81-100` `guard_special_key_scope`：

| key | 限制 | 报错 |
|---|---|---|
| `LANGFUSE_*`（任意后缀） | **任何 scope 都禁止设置** | 400 `'X' is managed by the platform (Langfuse sidecar credentials) and cannot be set via env_vars` |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | **只能 runtime scope**，设到 sandbox scope 被拒 | 400 `'X' is consumed by the LLM sidecar and must be in Runtime scope` |
| 撞上平台保留键的其它 runtime 变量（`PORT` / `PATH` / `NEXAU_*` 等） | 不报错，**静默被平台值覆盖** | 无（runtime_env.rs:285-292） |
| key 含字母数字下划线以外的字符，或 >255 字符 | 建不出来 | 400（env_vars.rs:65-76） |

另：🚫 **不要在顶层 agent.yaml 里自己写 `sandbox_config`**（哪怕只为了塞 `envs`）。

`server.py:2191-2216` `_inject_sandbox_config_for_request`：平台**只在 `agent_config.sandbox_config is None` 时**（`:2215`）才把本次请求的沙箱配置写进去；已有值一律保留（源码注释原话：*Explicit child sandbox_config values are preserved to keep intentional sub-agent isolation available*）。

后果分层，别混：

- **顶层 agent 写了 `sandbox_config`** → 平台的 `template` / `api_url` / `api_key` / `envs` 全不注入，你得自己在 yaml 里凑齐这些云端坐标 —— 而 sidecar 地址和 per-session token 是运行期才生成的，yaml 里写不出来，**云上必挂**。
- **sub_agent 写了 `sandbox_config`** → 这是**被有意支持的**用法（让子代理跑独立沙箱），不是 bug；但它同样拿不到平台注入的 `sandbox_env`。
- 要给沙箱塞变量，走第 4 / 5 节的通路，不要碰 `sandbox_config`。

---

## 9. 改了 env var 必须 Redeploy 才生效

版本是 immutable 模型：env var 在 **deploy 时**被冻结进 `project_versions.resolved_env` 快照（写侧 `versions.rs:95-115` `build_env_snapshot`），scheduler 与 Gateway 都优先读快照（无快照才 fallback 到 `:703-724` 的实时解析；`sandbox_env.rs:17-31`）。

- 改完 env var **不重新部署 = 没改**。
- runtime scope 的变化还要 Pod 重建才进容器 env。
- 唯一不需要 Redeploy 的口子是 per-request `variables.sandbox_env` / `variables.runtime_vars`（每次请求现传现用，且 `sandbox_env` **优先级高于治理值**）。

---

## 10. chat API 的 `variables` 三通道

结构在 Gateway 与 Runtime 两侧同构：`chat.rs:139-147`（Rust）/ `server.py:532-542`（pydantic），三个字段都有默认空 map。

| 通道 | 落到哪 | 谁消费 | 是否对 LLM 可见 |
|---|---|---|---|
| `template` | `AgentContext` → systemprompt 的 Jinja2 渲染上下文 | `{{ my_var }}` | ✅ 会进 prompt |
| `runtime_vars` | runtime 进程内的变量表 | `agent_state.get_variable("k")`（agent_state.py:159-169） | ❌ 不进 prompt |
| `sandbox_env` | 沙箱进程 OS 环境（见第 4 节链路） | 沙箱 `$K` / `os.environ`；runtime 侧 `agent_state.get_sandbox_env("k")` | ❌ 不进 prompt |

### 可直接抄的调用示例

> **鉴权二选一**（ 的调度表）：
> - **AK/SK**：`Authorization: Basic base64(ak:sk)` —— 凭据本身绑定 project，**不需要** `X-Project-Id`。
> - **PAT**：`Authorization: Bearer nacp_xxx` —— 必须**同时**带 `X-Project-Id`（`auth.rs:439-445` `authenticate_via_pat` 强制要求）。
>
> 🚫 `Bearer` 后面接**非 `nacp_` 开头**的 token → 401（`auth.rs:338`）。下面示例走 PAT 形态。

```bash
# 1) 先建 session（POST /agent-api/sessions，body 只要 distinct_id）
#    $NAC_TOKEN 必须是 nacp_ 开头的 PAT
SESSION_ID=$(curl -sS -X POST "$GATEWAY/agent-api/sessions" \
  -H "Authorization: Bearer $NAC_TOKEN" \
  -H "X-Project-Id: $PROJECT_ID" \
  -H "Content-Type: application/json" \
  -d '{"distinct_id":"user-42"}' | jq -r '.session_id')

# 2) 带三通道变量发起 chat（SSE 流式；平台自己生成的 API 脚本也是这个形态）
curl -sS -N -X POST "$GATEWAY/agent-api/chat" \
  -H "Authorization: Bearer $NAC_TOKEN" \
  -H "X-Project-Id: $PROJECT_ID" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d "{
    \"session_id\": \"$SESSION_ID\",
    \"distinct_id\": \"user-42\",
    \"environment\": \"production\",
    \"stream\": true,
    \"messages\": [{\"role\":\"user\",\"content\":\"帮我拉一下仓库里的 open issue\"}],
    \"variables\": {
      \"template\":     {\"project_name\": \"my-app\", \"language\": \"zh\"},
      \"runtime_vars\": {\"tenant_id\": \"t-001\"},
      \"sandbox_env\":  {\"GITHUB_TOKEN\": \"ghp_xxx\"}
    }
  }"
```

- `project_id` 由网关从认证上下文 / `X-Project-Id` 注入，**不放在 body 里**（`ChatRequest` 结构体里根本没有这个字段，见 `handlers/chat.rs:62-95`）。
- `session_id` 是**必填**（`chat.rs` `ChatRequest.session_id: String` 非 Option），必须先建 session。
- 路由维度优先级：`deployment_id` > `version_id` > `version_tag` > `environment`，都缺省时回落 `environment="production"`（实现见 `handlers/chat.rs:179-187`：`req.deployment_id.or(req.version_id)` → `version_tag` → `environment` → `VersionRef::Environment("production")`）。
- `variables` 整个字段可省略；三个子通道可只填其中一个。
- ⚠️ **`stream` 决定 Gateway 用哪个 HTTP client，进而决定有没有整请求超时**：`stream: true` 走专用的
  no-timeout client；`stream: false`（含省略，默认 false）走带 `request_timeout_secs` 的 client，
  **默认 300 秒、生产在跑的也是 300**（`chat.rs:791-796` +
  `lib.rs:224,229-238`；默认值 `lib.rs:2619-2624`）。跑得久的 agent 用非流式会在 ~5 分钟处被网关掐断，
  而 pod 里 agent 还在跑——这跟 agent.yaml 的 `timeout` 无关，改那个没用。所以示例默认用流式。

---

## 11. 澄清：顶层 `variables:` 块 ≠ 运行时 `variables`

agent.yaml 顶层的 `variables:` 块与 chat 请求的 `variables` **同名但毫无关系**：

| | agent.yaml 顶层 `variables:` | chat 请求 `variables` |
|---|---|---|
| 消费方式 | `${variables.a.b}` 加载期**文本宏** | `{{ }}` / `agent_state.get_variable()` / 沙箱 env |
| 生命周期 | 解析完就被 `pop` 掉，不进 `AgentConfig`（common.py:100-129） | 贯穿整次 run |
| 来源 | 同一个 yaml 文件自己 | HTTP 请求体 |

顶层 `variables:` 块的完整语义（不递归、无块时静默留字面量、不跨文件继承、必须是 mapping）见 `references/agent-yaml-fields.md`。

---

## 12. 排错速查表

| 症状 | 最可能的原因 | 处置 |
|---|---|---|
| 加载期 `Environment variable 'X' is not set` | ① 该 key 没建成 **runtime scope**；② 建了但没 Redeploy；③ **注释里**还留着 `${env.X}` | 建 runtime scope 变量并重新部署；注释掉的配置要**真删**，注释不豁免 |
| 沙箱脚本 `os.environ['X']` KeyError，但本地跑得好好的 | 变量建成了 runtime scope；本地 LocalSandbox 继承父进程环境掩盖了问题 | 改建 **sandbox scope**（或用 per-request `sandbox_env`） |
| custom tool 里 `os.getenv('X')` 是 None | 变量建成了 sandbox scope；custom tool 跑在 runtime 进程内 | 改建 **runtime scope**（两边都要就建两份） |
| agent.yaml 里某字段变成 `'${env.X:-default}'` 这串字面量 | 用了不支持的默认值语法，正则不匹配 → 静默留字面量 | 删掉 `:-default`，改用「必设变量 + 部署前检查」 |
| 打印 `LLM_API_KEY` 得到 `placeholder-sidecar-injected` / `sk-placeholder` | 设计如此，真凭证在 sidecar | 不要排查，不要试图绕过 |
| 建 env var 返回 400 `managed by the platform` | key 命中 `LANGFUSE_*` | 平台凭证不允许用户设置 |
| 建 env var 返回 400 `must be in Runtime scope` | `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` 建到了 sandbox scope | 改 `?scope=runtime` |
| deploy 报 `runtime.env:N is missing '='` / `has an empty env var key` / `has invalid env var key` | 制品里的 `runtime.env` / `sandbox.env` 格式不合法 | 按第 5 节的语法表修 |
| 我建的 `PATH` / `PORT` / `NEXAU_XXX` 没生效 | 平台保留键覆盖用户值，静默无提示 | 换成带自有前缀的 key |
| `agent_state.get_sandbox_env('X')` 在 runtime 侧读得到，但沙箱里 nohup 起的守护进程读不到 | 变量确实送达了，只是 K8s 非 DevBox 沙箱不把它写进 Pod 容器 env —— per-command env 只覆盖 SDK 拉起的那一次命令 | 启动命令里显式 `X=$X cmd`，或改由 SDK 工具拉起 |
| agent.yaml 加载报 YAML 语法错，但文件看着没问题 | env 值里含 `: ` / 换行 / ` #` / 开头 `*`，文本注入把 YAML 搞坏了 | 给占位加双引号；清理变量值 |
| 环境变量改了但行为没变 | 没 Redeploy（版本 immutable，env 冻结在 `resolved_env` 快照） | 重新部署 |

---

## 13. 交叉引用

- agent.yaml 字段全集、顶层 `variables:` / `context:` 语义、校验强度分层 → `references/agent-yaml-fields.md`
- custom tool 的进程边界、`extra_kwargs` 与 `additionalProperties: false` 互斥 → `references/custom-tools.md`
- `llm_config` 的真禁 / 无效 / 回落条件 → `references/llm-config.md`
- `/agent` 只读、`/home/user` 可写、`nexau.json` 的 `setup` 装依赖、100MB 打包上限 → `references/nexau-json-and-packaging.md`
