# llm_config：NAC 上的模型选择与采样参数

> **本文覆盖**：agent.yaml 里 `llm_config` 每个字段在 NAC 平台上的真实命运（哪些会坏、哪些被无条件覆盖、哪些由你决定）、`model` 的三种写法与回落判定、平台注入的三个 LLM env 的真实取值、采样参数优先级链、以及「模型不是我写的那个」怎么查。
> **什么时候读**：生成 / 修改任何 agent.yaml 的 `llm_config` 之前；排查 422 `LLM_PROVIDER_UNROUTABLE`、`ConfigError: Environment variable ... is not set`、「采样参数没生效」时。
> 相关：`${env.X}` 三通道与 scope 见 `references/env-vars-and-secrets.md`；字段校验强度分层见 `references/agent-yaml-fields.md`；中间件见 `references/middlewares.md`。

---

## 0. 一句话结论

**在 NAC 上，`llm_config` 只需要写 `model` + 你真正想控的采样参数。连接信息（`base_url` / `api_key`）永远不写——平台在运行期无条件覆盖它们。**

推荐最小写法（二选一）：

```yaml
# A. 跟随项目/环境默认模型（推荐给绝大多数 agent）
llm_config:
  model: ${env.LLM_MODEL}
  temperature: 0.2
```

```yaml
# B. 钉死某张已授权模型卡
llm_config:
  model: nex-agi/claude-opus-4-8   # provider/model_name 全键
  temperature: 0.3
  max_tokens: 8192
```

```yaml
# C. 完全不关心模型 —— 整段省略也合法（等价 A）
type: agent
name: my_agent
system_prompt: ./prompts/system.md
# 无 llm_config：agent-runtime 加载期纯内存补一份项目默认
# services/agent-runtime/nexau_cloud_agent_runtime/cli.py:160-199
```

A 与 B **语义不同，是选择题不是风格偏好**，见 §3。
C 只是 A 的省略写法，**不比 A 更耐操**：项目零可见卡时三种写法一样在加载期硬失败（§3.4）。

---

## 1. 字段三档表

同样是「不要写」，原因完全不同。别把三档混成一张 🚫 表。

### 档 ① 真禁 —— 写了会坏

| 字段 | 后果 | 证据 |
|---|---|---|
| `llm_config.api_key`（字面量） | **凭证进制品 = 安全事故**；A4A 制品静态校验器判 **error**（`agent.llm_config.api_key.literal`），制品过不了校验。且运行期照样被覆盖，写了纯亏 | `builtin-agents/Agent4Agent/skills/artifact-verifier/scripts/artifact_static_validator.py:324-331` |
| `sandbox_config`（agent.yaml 顶层，非 llm_config） | 平台注入是 **「你没写才注入」**：`if getattr(agent_config, "sandbox_config", None) is None: updates["sandbox_config"] = sandbox_config`。你一旦自己写了，平台的沙箱路由/凭证就不注入，沙箱基本必炸 | — |

> 唯一例外：**子 agent** 的 `sandbox_config` 是刻意保留的（同函数 docstring：“Explicit child sandbox_config values are preserved to keep intentional sub-agent isolation available”）。要给子代理换沙箱后端时才写，主 agent 一律别写。

### 档 ② 写了没用 —— 无害噪声，会被平台无条件覆盖

写了不报错、不影响部署，但**一定不生效**。生成制品时直接省略；看到样例里有就删掉。

| 字段 | 被谁覆盖成什么 | 覆盖点 file:line |
|---|---|---|
| `base_url` | 覆盖成 `LLM_BASE_URL`（= sidecar 本地地址） | （`updated.base_url = env_llm_config.base_url`）；catalog 请求路径另从**原始** `os.environ["LLM_BASE_URL"]` 重算，同样不复用你的值：`server.py:2817-2819` |
| `api_key` | 覆盖成 `LLM_API_KEY`（= 占位符字面量） | `server.py:1957`（`updated.api_key = env_llm_config.api_key`） |
| `api_type` | 只要最终 model 全键命中模型卡，按卡片派生值覆盖（日志明写 `overriding agent.yaml`） | `server.py:1496-1510` |
| `stream` | **流式 chat 路径**强制置 `True`（不管你写 true 还是 false） |  传 `enable_stream=True` → `nexau/archs/transports/base.py:133-135` |

两条边角，知道即可，不改变「别写」的结论：

- `api_type` 的覆盖**条件是 model 命中卡片**。model 没命中且没回落时（见 §3.3），你写的 `api_type` 会原样留着 —— 但那种状态下每次 chat 已经 422 了，没有实际意义。
- `stream` 只在流式路径被强制；非流式 `query` 路径保留 yaml 值（`server.py:5897-5900` 未传 `enable_stream`）。仍然别写：NAC 的 `/agent-api/chat` 是流式路径。

### 档 ③ 由你决定 —— 平台只补缺，不改你写的值

| 字段 | 说明 |
|---|---|
| `model` | 见 §3。**唯一需要认真想的字段。** |
| `temperature` | 平台**不做任何运行期纠正**（`server.py:1611-1614`：「用户填什么就是什么…原 thinking→temperature=1 自动归一已删」）。填错由上游模型报错，见 §5 指南表 |
| `max_tokens` | 未写时：anthropic 家族兜底 **8192**（`server.py:1629-1634`，`_R1_CUSTOM_DEFAULT_MAX_TOKENS = 8192` @ `server.py:1314`）；openai 家族不兜底 |
| `top_p` / `frequency_penalty` / `presence_penalty` | 原样透传，无兜底 |
| `timeout` | 未写时兜底 **300.0 秒**（`server.py:1621-1622`，`_DEFAULT_LLM_TIMEOUT_SECS = 300.0` @ `server.py:1322`） |
| `thinking` / `output_config` / `budget_tokens` | anthropic 家族专属；跨 api_type 会被剔除（§5.4） |
| `reasoning` / `max_output_tokens` | openai_responses 专属；同上 |
| `max_iterations` 等 | **不属于 llm_config**，是 agent.yaml 顶层字段，见 `references/agent-yaml-fields.md` |

⚠️ **`llm_config` 内部字段完全不经过 pydantic 校验**：`LLMConfig.__init__` 把所有未知 key 吞进 `self.extra_params = kwargs`（`nexau/archs/llm/llm_config.py:114-115`）。拼错的键（`temperture`）不会报错，会作为 extra param 原样送给上游 SDK，可能触发 `unexpected keyword argument`，也可能被静默忽略。**别指望框架帮你抓拼写错误。**

---

## 2. `tracers`：运行期是合并，但官方规范禁写 → **结论仍是别写**

分两层看，两层结论不同，别只记一半：

| 层 | 结论 | 依据 |
|---|---|---|
| **运行期（框架/平台注入）** | 平台 tracer 与制品自带 `tracers` 是**合并**关系，不是互斥；写了功能上能用 | `server.py:2176-2177`，见下方代码 |
| **官方制品规范（静态校验器）** | `tracers` 与 `sandbox_config` 并列在 `forbidden_agent_fields`，出现即判 **error**（`agent.field.forbidden`） | `builtin-agents/Agent4Agent/skills/nexau-artifact-rules/references/builder-static-rules.json:71-74` |

**实践结论：别在 agent.yaml 里写 `tracers`，观测交给平台。**
（旧 skill 把它和 `api_key` 并列写进「🚫 禁止字段」，理由说错了——不是"写了会被覆盖/会坏"，
而是"规范不允许"；运行期其实是合并的。见 `artifact-spec-checklist.md` §3。）

合并逻辑（说明运行期确实支持自定义 tracer，仅供理解）：

```python
# services/agent-runtime/nexau_cloud_agent_runtime/server.py:2176-2177（函数 _inject_tracer_for_request）
combined = _flatten_tracers([tracer]) + _flatten_tracers(agent_config.tracers)
effective = combined[0] if len(combined) == 1 else CompositeTracer(combined)
```

平台 tracer（Langfuse / Jaeger composite）被放在队首（primary position），你的 tracers 追加在后。自定义 tracer 是**被支持的**能力。

---

## 3. `model`：三种写法与判定

### 3.1 三种合法写法

| 写法 | 语义 | 何时用 |
|---|---|---|
| `${env.LLM_MODEL}` | **follow-default**：跟随项目/环境默认模型；管理员改默认模型后该 agent 自动跟随（Gateway 缓存刷新即漂移） | 默认推荐。除非有明确锁定需求 |
| `provider/model_name` 全键（如 `nex-agi/claude-opus-4-8`） | **钉死**在那张卡上，不随平台默认变 | 业务对模型能力有硬依赖时 |
| 省略 `model` 键 / 省略整段 `llm_config` | 同样是 follow-default（⚠️ 但**不是**更安全的写法，见 §3.4） | 完全不关心模型时 |

follow-default 判定代码（三种情况都返回 True）：

```python
# services/agent-runtime/nexau_cloud_agent_runtime/llm_model_provenance.py:157-175
#（常量 _LLM_MODEL_PLACEHOLDER = "${env.LLM_MODEL}" @ :17）
llm_config = raw.get("llm_config")
if llm_config is None:            return True      # 整段缺席
if not isinstance(llm_config, dict): return False  # 写成标量 → 不算 follow-default
raw_model = llm_config.get("model")
return (raw_model == "${env.LLM_MODEL}" or raw_model is None
        or (isinstance(raw_model, str) and not raw_model.strip()))
```

消费点：`server.py:2789-2792` —— `follows_default` 为 True 时用请求期 fresh `fallback_model`，否则保留你写死的全键。

> 全键按**第一个 `/`** 拆 provider（`server.py:1410-1414`），model 名本身可以再含 `/`。

### 3.2 🚫 裸名（无 `provider/` 前缀）—— 比写错全键更糟

`model: claude-opus-4-8` 这种写法：

1. **sidecar 直接 Reject，不走任何回落**：`proxy_routers.rs:1177-1187`
   ```rust
   if provider_prefix.is_none() {
       return ResolveOutcome::Reject { provider: None,
           reason: format!("model '{model_value}' has no provider_name/ prefix") };
   }
   ```
   → `proxy_routers.rs:880-896` 转成 **HTTP 422 + `{"code":"LLM_PROVIDER_UNROUTABLE"}`**，每次 chat 都失败。
2. **A4A 静态校验器判 error**（`artifact_static_validator.py:315-323`），制品过不了校验。

**规则：`model` 必须是 `provider/model_name` 全键，或 `${env.LLM_MODEL}`。没有第三种。**

### 3.3 ⚠️「优雅回落」是**有条件**的

旧 skill 把「model 写错 → 优雅回落项目默认」写成无条件成立，**错**。真实逻辑：

```python
# services/agent-runtime/nexau_cloud_agent_runtime/server.py:1466-1493
model_key = llm_config.model
if providers_meta and (not model_key or model_key not in providers_meta):
    fallback_model = os.environ.get("LLM_MODEL")
    if fallback_model:
        llm_config = LLMConfig(model=fallback_model,
                               base_url=llm_config.base_url,
                               api_key=llm_config.api_key)   # ← 采样参数全丢
    else:
        logger.warning("... leaving model as-is")            # ← 不回落
```

| 前提 | 结果 |
|---|---|
| `providers_meta` 非空 **且** `LLM_MODEL` 已注入 | 回落到 `LLM_MODEL`。**但整段 llm_config 被判为不可信** —— `temperature` / `max_tokens` / `top_p` / `thinking` / `output_config` / `reasoning` **全部丢弃**，只保留连接信息（`server.py:1481-1485`，单测 ，明确断言 `temperature is None` / `top_p is None`） |
| `providers_meta` 为空（项目一张可见卡都没有）**或** `LLM_MODEL` 未注入 | **不回落**，model 原样保留 → sidecar 每次 chat 返回 **422 `LLM_PROVIDER_UNROUTABLE`**（`proxy_routers.rs:1202-1214` → `:880-896`） |

> ⚠️ 别把「路由表空」等同 503。chat 路径上只要 body 里有 `model` 字段，路由表空 = `providers.resolve()` 返回 `None` → `Reject` → **仍是 422**（`proxy_routers.rs:1204-1215`）。503 `no LLM provider configured` 只出现在 `Fallback` 分支——**请求体不是合法 JSON 或压根没有 `model` 字段**（`proxy_routers.rs:1152-1170`）、或走非 chat 端点（`/v1/embeddings`、`/v1/models`，`:897-911`）**且**路由表为空时。制品作者日常见到的是 422。

两条必须写进制品作者脑子里的推论：

- **「模型名打错一个字母」= 采样参数静默全丢**，日志只有一行 INFO，很难自己发现。
- **未授权 / 隐藏未解锁的模型卡对项目「等同不存在」**：不进 sidecar 凭证表、不进 META、不进兜底候选。写了未授权卡片 ≡ 写了不存在的卡片。

### 3.4 ⚠️ `${env.LLM_MODEL}` 也可能让 agent 加载不起来

`LLM_MODEL` 由 scheduler **仅在能解析出兜底模型时**才注入：

```rust
// crates/nexau_cloud_scheduler/src/runtime_env.rs:527-537
if let Some(m) = fallback_model {
    env.insert("LLM_MODEL".to_string(), m.to_string());
}
```

兜底模型解析是四档漏斗，**全部以「项目可见卡片集」为唯一取数源**（`runtime_env.rs:423-465` `pick_fallback_model`）：

| tier | 规则 |
|---|---|
| tier-0 环境默认 | 环境配的全键必须 ∈ 可见集才用，否则降级 |
| tier-1 项目默认 | 项目配的全键必须 ∈ 可见集才用，否则降级 |
| tier-2 平台默认卡 | 从可见集里找 `is_platform_default` 的卡 |
| tier-3 第一张可见卡 | 可见集为空才返回 `None`（`cards.first()?`） |

**项目一张可见卡都没有 ⇒ 四档全落空 ⇒ `LLM_MODEL` 这个 env 根本不存在 ⇒ agent.yaml 里的 `${env.LLM_MODEL}` 在加载期直接抛 ConfigError，agent 起不来。**

```python
# nexau/archs/main_sub/utils/common.py:86-92
if env_name not in os.environ:
    raise ConfigError(f"Environment variable '{env_name}' is not set")
```

⚠️ **省略写法并不能绕开这个失败**（本条已实测）。项目零可见卡时三种写法都在加载期挂，只是异常类型不同：

| 写法 | 项目零可见卡时的加载结果 |
|---|---|
| `model: ${env.LLM_MODEL}` | `ConfigError: Environment variable 'LLM_MODEL' is not set`（`common.py:88-89`，在 `yaml.safe_load` 之前就炸） |
| 有 `llm_config` 但省略 `model` 键 | `ValueError: Model not found in environment variables` —— `cli.py` 的内存注入**只在整段 `llm_config` 缺席时才触发**（`cli.py:183` `config.get("llm_config") is None`），本例不触发；`LLMConfig.__init__` 走 `self.model = model or self._get_model_from_env()`，依次查 `MODEL` / `OPENAI_MODEL` / `LLM_MODEL` 全落空即 raise（`llm_config.py:88` + `:127-141`） |
| 整段省略 `llm_config` | 同样 `ValueError: Model not found in environment variables` —— `cli.py:192-196` 注入的是 `os.environ.get("LLM_MODEL", "")`，**空串在 `model or ...` 里是 falsy**，照样落进 `_get_model_from_env()` |

**推论：三种写法在「项目没有任何可见模型卡」这件事上没有安全差异，都是加载期硬失败。** 真正的修法是给项目授权至少一张模型卡，不是换 yaml 写法。

---

## 4. 平台注入的 LLM env 的真实取值

`${env.X}` 只能读到 **runtime pod 的环境变量**。NAC 上这三个 key 的真实值：

| env | 真实值 | 注入点 |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:{sidecar.llm_port}/v1` —— **sidecar 的本地地址，不是任何上游 API** | — |
| `LLM_API_KEY` | 字面量 `"placeholder-sidecar-injected"` —— **占位符，不是真凭证**（agent-runtime 侧另有一处写 `sk-placeholder`，`server.py:1004-1005`） | 同上 |
| `LLM_MODEL` | scheduler 解析出的兜底模型全键；**无兜底模型时该 env 不存在**（§3.4） | `runtime_env.rs:527-537`（在 merge 之后插入） |
| `LLM_API_TYPE` | 🚫 **平台不再注入**。见下 | — |

真凭证只在 **sidecar 进程内**（`NEXAU_AGENT_RUNTIME_SIDECAR_*` 前缀），runtime 容器永远拿不到。这就是「制品里写 `api_key` 毫无意义」的物理原因。

### 4.1 🚫 `api_type: ${env.LLM_API_TYPE}` 会让 agent 直接加载失败

平台已不注入 `LLM_API_TYPE`（`grep LLM_API_TYPE crates/nexau_cloud_scheduler/src/` 只命中一条**断言其不存在**的单测：`lib.rs:3314`；agent-runtime-rs 侧注释亦写「旧 `LLM_API_TYPE`/`LLM_EXTRA_PARAMS` 已忽略」`backend_nexau_rs.rs:1396`）。而未设置的 `${env.X}` 抛 ConfigError（§3.4）。

**历史文档 / 老模板里如果出现 `api_type: ${env.LLM_API_TYPE}`，直接删掉整行。**

### 4.2 用户自建 env var 覆盖不了这三个 key

`merge_runtime_env` 先铺 user_env、再用 platform_base 覆盖写（`runtime_env.rs:280-293`，注释 "Reserved keys: platform always wins"）。另外 backend 侧还有 scope 守卫：`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 设成 sandbox scope 直接 **400**，`LANGFUSE_*` 任何 scope 都 400。
唯一例外：项目无可见卡时平台不注入 `LLM_MODEL`，此时用户在 runtime scope 设的 `LLM_MODEL` 能存活。

### 4.3 `base_url` / `api_key` 省略永远安全；`model` 省略只在有卡时安全

SDK `LLMConfig` 构造时会自己从 env 找（`nexau/archs/llm/llm_config.py:88-90`）：
`model` 查 `[MODEL, OPENAI_MODEL, LLM_MODEL]`（:127-141）、`base_url` 查 `[OPENAI_BASE_URL, BASE_URL, LLM_BASE_URL]`（:143-157）、`api_key` 查 `[LLM_API_KEY, OPENAI_API_KEY, API_KEY, ANTHROPIC_API_KEY]`（:159-174）。**三者各自找不到时都抛 `ValueError`。**

- `base_url` / `api_key`：平台**必定**注入（`runtime_env.rs:300-310` 无条件插两个 key），所以省略永远拿得到值 → 安全。写 `${env.LLM_BASE_URL}` / `${env.LLM_API_KEY}` 是**三重冗余**：SDK 自己会读，读到的值紧接着又被 `_inject_llm_config` 覆盖一次。
- `model`：`LLM_MODEL` 是**条件注入**（§3.4）。项目零可见卡时省略 `model` → `ValueError: Model not found in environment variables`，agent 起不来。

---

## 5. 采样参数优先级链

### 5.1 部署期链（无 Gateway catalog 的请求）

```
agent.yaml 显式  >  纯 switch 三选一（环境固化 | 项目固化 | 模型卡 default_params）  >  平台兜底
```

⚠️ **中间那层是 switch，不是逐键 union**：

```python
# services/agent-runtime/nexau_cloud_agent_runtime/server.py:1596-1609
if isinstance(per_model_env, dict):
    _fill_missing_params(per_model_env, "environment defaults")        # 命中即整块用，跳过下面两档
elif isinstance(per_model_project, dict):
    _fill_missing_params(per_model_project, "project defaults")
elif isinstance(card_default_params, dict):
    _fill_missing_params(card_default_params, f"model card '{model_key}' params")
```

环境对该模型有固化就**整块用环境那份**，项目和卡片的键一个都不补（哪怕环境那份是空 dict）。极易误写成「三层逐键合并」。
`_fill_missing_params` 只填当前为 `None` 的键（`server.py:1529-1576`）。

### 5.2 请求期链（经 Gateway 下发 catalog）

```
per-request 顶层 params  >  per-request providers 点名 params  >  agent.yaml 显式  >  环境固化  >  项目固化  >  模型卡默认
```

判定「yaml 显式」的实现：`server.py:2851` `if not forced and _yaml_declared_param(base, k): continue`；`_yaml_declared_param` 定义在 `server.py:1281-1291`（别名族命中 / direct 字段非 None / extra_params 已有，任一即算显式）。

⚠️ 边角（会咬人）：这里的 `base` 是**已经过部署期 `_apply_platform_llm_runtime_rules` 填充过的** llm_config（`server.py:3089` 存入 `self._agents`），因此部署期兜底填进去的 `timeout=300` 和 anthropic `max_tokens=8192` 会被当成「yaml 显式」，从而挡掉 catalog 下发的同名键（除非该键在 per-request `request_param_keys` 里被强制）。

### 5.3 平台兜底（恒定）

| 条件 | 兜底值 | file:line |
|---|---|---|
| `timeout` 未写（且别名族未命中） | `300.0` 秒 | `server.py:1621-1622` |
| `api_type ∈ {anthropic_chat_completion, anthropic}` 且 `max_tokens` 未写 | `8192` | `server.py:1629-1634` |

（anthropic SDK `messages.create` 缺 `max_tokens` 会每个 turn 首次调用即失败，所以这个兜底是必需的。）

### 5.4 跨 api_type 专属键会被剔除

`_strip_foreign_api_type_params`（`server.py:1325-1342`）按下表只保留本 api_type 的专属键，其余专属键 warn + 删（通用键 / 未知键不动）：

| api_type | 允许的专属 extra 键 |
|---|---|
| `anthropic_chat_completion` / `anthropic` | `thinking` / `output_config` / `budget_tokens` |
| `openai_responses` | `reasoning` / `max_output_tokens` |
| `openai_chat_completion` | （空集） |
| `gemini_rest` | `thinking_budget` / `include_thoughts` |

（`server.py:1218-1224`）所以在 anthropic 上写 `reasoning`、在 openai_responses 上写 `thinking` 都会被静默删掉。

### 5.5 temperature 选择指南

平台**不再**对 temperature 做任何运行期纠正（`server.py:1611-1614`：原 `thinking → temperature=1` 自动归一已删）。**填什么就是什么，合法性由上游模型裁决。**

| 场景 | temperature | 理由 |
|---|---|---|
| 法律 / 医疗 / 金融问答 | 0.0 – 0.2 | 需要精确引用，禁止发挥 |
| 通用问答 / 客服 | 0.2 – 0.4 | 准确性优先 |
| 创意写作 / 头脑风暴 | 0.5 – 0.7 | 需要多样性 |

⚠️ **anthropic 家族开 `thinking` 时上游要求 `temperature: 1`**，平台不会帮你改。要么显式写 `temperature: 1`，要么整个别写 temperature（让它保持 None）。写 `temperature: 0.2` + `thinking: enabled` 会原样发上去，由上游报错。
> 「上游会拒」是模型侧约束，本仓无法直接断言，但代码注释旁证：`server.py:1478-1480` 解释回落时丢弃 temperature 的理由正是「避免把 agent 的 temperature 灌进开思考的 anthropic 调用而**被上游拒**」。

---

## 6. 排障心智

### 6.1 部署成功 ≠ 模型配对了

**上传 / 部署期完全不校验 `llm_config` 的 model / provider 可路由性。**

> `versions.rs:1296-1299`：「deploy 不再读取 / 校验 agent.yaml 的 llm_config…**不**校验 provider/model 是否可路由…即非法 provider 不再 deploy 期 fail-fast，而是 **chat 期每请求 422**」

上传期只做结构校验（agent 文件存在 / 非空）。所以：**部署绿了什么都不代表，必须发一次真 chat 才算验证过。**

### 6.2 「Agent 用的模型不是 yaml 写的那个」查证顺序

| # | 检查 | 怎么查 |
|---|---|---|
| 1 | model 是不是裸名？ | 没有 `provider/` 前缀 → 必 422，先修这个（§3.2） |
| 2 | 全键是否命中**本项目可见**的卡片？ | 未授权 / 隐藏未解锁的卡 ≡ 不存在。在平台模型配置里确认该卡对本项目可见 |
| 3 | runtime 日志有没有回落记录？ | 搜 `has no matching model card`：带 `falling back to project LLM config (model='...')` = 走了回落（**采样参数已全丢**）；带 `LLM_MODEL not set; leaving model as-is` = 没回落，随后 422 |
| 4 | api_type 被改了？ | 搜 `deriving api_type for model card` —— 平台按卡片覆盖是**预期行为**，不是 bug |
| 5 | 采样参数明明写了却没生效？ | 先排 3（回落连坐丢参数），再看是不是被环境/项目固化的 switch 整块取代（§5.1），最后看 `_fill_missing_params` 的 tier 日志（`environment defaults` / `project defaults` / `model card '...' params`） |
| 6 | 请求返回 422 `LLM_PROVIDER_UNROUTABLE` | 报文 `message` 会写 `not found in routing table (was the card deleted/hidden/renamed after upload?)` 或 `has no provider_name/ prefix` —— 直接指出是哪一类 |
| 7 | 请求返回 503 `no LLM provider configured` | **不是**「model 写错」这一类。只可能是：请求体非法 JSON / 无 `model` 字段，或走的是非 chat 端点，**且**路由表为空（`proxy_routers.rs:870-877`、`:904-911`）。chat 路径的模型问题一律 422 |
| 8 | agent 起不来，`ConfigError: Environment variable 'LLM_MODEL' is not set` | 项目一张可见卡都没有（§3.4）。不是你的 yaml 语法问题 |
| 9 | agent 起不来，`ValueError: Model not found in environment variables` | 同 8 的根因，只是你的 yaml 省略了 `model`（或整段 `llm_config`），异常从 SDK 侧抛出（§3.4 表）。修法一样：给项目授权模型卡 |
| 10 | agent 起不来，`ConfigError: Environment variable 'LLM_API_TYPE' is not set` | 删掉 `api_type: ${env.LLM_API_TYPE}` 那一行（§4.1） |

### 6.3 平台不改写你的 agent.yaml

以上所有解析全部在**运行期内存**完成（`server.py:1950-1958` 用 `yaml_config.copy()` + `model_copy(update=...)`；`cli.py` 的默认注入明确注释「不写盘：运行期 `/agent` 是只读挂载」）。
**推论：拉下来的制品 agent.yaml 永远是你上传的字节 —— 用它来判断「实际生效的模型/参数」是错的，必须看 runtime 日志。**

---

## 7. `base_url` / `api_key` 的合法出现位置

「顶层 `llm_config` 不写 base_url/api_key」**不等于**「制品里任何地方都不能出现 base_url/api_key」。以下两处是合法且必要的：

### 7.1 LLMFailoverMiddleware 的 `fallback_providers`

主 provider 失败时切备用端点，备用端点的连接信息**必须**由你提供 —— 它不经过 sidecar 路由，`_apply_fallback` 直接用这份 dict 覆盖出一个新 `LLMConfig` 并新建 client（`nexau/archs/main_sub/execution/middleware/llm_failover.py:334-356`）。

```yaml
middlewares:
  - import: nexau.archs.main_sub.execution.middleware.llm_failover:LLMFailoverMiddleware
    params:
      trigger:
        status_codes: [500, 502, 503, 529]
        exception_types: ["RateLimitError", "InternalServerError"]
      fallback_providers:
        - name: "backup-gateway"
          llm_config:
            base_url: "https://backup.example.com/v1"
            api_key: ${env.MY_BACKUP_LLM_KEY}    # ← 走 runtime scope 环境变量，不写字面量
        - name: "emergency"
          llm_config:
            model: "gpt-4o"
            base_url: "https://emergency.example.com/v1"
            api_key: ${env.MY_EMERGENCY_LLM_KEY}
            api_type: "openai_chat_completion"
      circuit_breaker:
        failure_threshold: 3
        recovery_timeout_seconds: 60
```

要点：
- `import` 路径必须带 `execution` 层（`main_sub.execution.middleware.llm_failover`），见 `references/middlewares.md`。
- fallback 里**没写的字段继承主 provider**（`llm_failover.py:334-342` 基于主 config `.copy()` 再逐键覆盖）。
- ⚠️ **凭证仍然不要写字面量**：A4A 静态校验器只扫顶层 `llm_config.api_key`（`artifact_static_validator.py:308-331` 只取 `agent_yaml.get("llm_config")`），middleware params 里的字面量 key **不会被拦下**，但一样是凭证进制品。用 `${env.X}` + runtime scope 环境变量（见 `references/env-vars-and-secrets.md`）。
- 备用端点必须是 runtime pod 能直连的地址；离线 / 内网环境要先确认网络策略放行。
- ⚠️ `${env.MY_BACKUP_LLM_KEY}` 这类自建 key **必须先建成 runtime scope 环境变量再部署**，否则 agent 在加载期就 `ConfigError: Environment variable '...' is not set`（`common.py:88-89`，`${env.X}` 替换发生在 `yaml.safe_load` 之前，注释里的占位也一样会被解析）。

### 7.2 「接自己的 LLM 网关」= per-request，不是 agent.yaml

在 agent.yaml 里把 `base_url` 指向自己的网关是**彻底无效的**（§1 档②，两条代码路径都强制用 `os.environ["LLM_BASE_URL"]`：`server.py:1956`、`server.py:2817-2819`）。正确做法是走 chat 请求体的 `override_llm_configs`（旧名 `llm`）：

```bash
curl -X POST https://<nac>/agent-api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "s1",
    "messages": [{"role":"user","content":"hi"}],
    "override_llm_configs": {
      "base_url": "https://your-llm-gateway.example.com",
      "api_key": "sk-your-own-key"
    }
  }'
```

对外字段名与形状由 **Gateway** 定义（：新名 `override_llm_configs`，旧名 `llm` 仍作回落；形状见 `proxy.rs:331` 「顶层 `model/base_url/api_key/api_type/params` + 可选 `providers`」）。agent-runtime 侧的同名 `RequestLlmOverride` 见 `server.py:567-588`。

| 目的 | 请求体 | 证据 |
|---|---|---|
| 换端点 + 换 key | `{"override_llm_configs": {"base_url": "...", "api_key": "..."}}` | `llm_override.rs` merge 路径 |
| 只换 key，端点仍走平台 | `{"override_llm_configs": {"api_key": "sk-..."}}` | 单测 `merge_top_key_only_swaps_key_keeps_endpoint`（`llm_override.rs:2013-2026`，断言 `base_url` 保留平台值） |
| 只换模型（平台已授权卡） | `{"override_llm_configs": {"model": "provider/model"}}` | — |
| 只调采样 | `{"override_llm_configs": {"params": {"temperature": 0.3}}}` | — |

⚠️ **给了自定义 `base_url` 却没给 `api_key` → Gateway 400**（防止把平台真 key 发到第三方端点）：

```rust
// services/agent-gateway/src/llm_override.rs:609-616（v4 唯一保留的语义 400）
if e.base_url_from_client && !e.api_key_from_client {
    return Err(ApiError::bad_request(format!(
        "override_llm_configs: full_key `{full_key}` 的 base_url 为客户端来源但 api_key 为平台来源..."
    )));
}
```
单测 `merge_pair_invariant_base_url_without_key_400`（`llm_override.rs:2031-2041`）。

⚠️ 上表是 **Gateway 下发 catalog** 这条路径的语义。agent-runtime 侧还有一条**不经 catalog 的旧路径**，它对 `{model, base_url, api_key, api_type}` 做**严格四规则分类**，残缺组合不报错、而是静默回落到 agent 默认模型并推一帧 `MODEL_FALLBACK`：

```python
# services/agent-runtime/nexau_cloud_agent_runtime/server.py:2226-2246 _classify_request_llm
R1 = model + base_url + api_key + api_type 全非空   # 自定义模型直连
R2 = base_url + api_key 非空，且 model / api_type 空  # 只换连接
R3 = 只有 model 非空                                 # 平台预设走 sidecar
noop = 四个都空
其余（含只给 api_key、只给 base_url）→ fallback + MODEL_FALLBACK
```

**结论：跨两条路径都稳妥的写法只有 R1 / R2 / R3 三种完整组合。**「我传了 override 但模型没变」先对照这三条。

---

## 8. 反例速查（照着删）

老模板 / cookbook 里常见的写法，逐行标注：

```yaml
llm_config:
  model: ${env.LLM_MODEL}
  base_url: ${env.LLM_BASE_URL}      # ← 删：被 sidecar 值无条件覆盖（server.py:1956）
  api_key: ${env.LLM_API_KEY}        # ← 删：被占位符覆盖（server.py:1957）；写字面量还会被静态校验器判 error
  api_type: openai_chat_completion   # ← 删：被模型卡派生值覆盖（server.py:1496-1510）
  stream: True                       # ← 删：流式路径平台强制 True（transports/base.py:133-135）
  max_tokens: 32000                  # ← 保留：有效
  temperature: 0.2                   # ← 保留：有效
```

老模板里 `api_type` 还有另一个变体 `api_type: ${env.LLM_API_TYPE}`（本文没把它写进上面这段，因为 **`${env.X}` 的替换发生在 `yaml.safe_load` 之前，写在 YAML 注释里同样会被解析并 ConfigError**，`common.py:83-92`）。见到它 **🚫 必删整行**（§4.1）。

清理后：

```yaml
llm_config:
  model: ${env.LLM_MODEL}
  max_tokens: 32000
  temperature: 0.2
```
