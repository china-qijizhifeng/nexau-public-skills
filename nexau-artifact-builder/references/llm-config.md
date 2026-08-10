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
# 无 llm_config：运行时在加载期于内存里补一份项目默认（不写盘）
```

A 与 B **语义不同，是选择题不是风格偏好**，见 §3。
C 只是 A 的省略写法，**不比 A 更耐操**：项目零可见卡时三种写法一样在加载期硬失败（§3.4）。

---

## 1. 字段三档表

同样是「不要写」，原因完全不同。别把三档混成一张 🚫 表。

### 档 ① 真禁 —— 写了会坏

| 字段 | 后果 |
|---|---|
| `llm_config.api_key`（字面量） | **凭证进制品 = 安全事故**；制品静态校验器判 **error**（`agent.llm_config.api_key.literal`），制品过不了校验。且运行期照样被覆盖，写了纯亏 |
| `sandbox_config`（agent.yaml 顶层，非 llm_config） | 平台注入是 **「你没写才注入」**——只有制品里这一项缺席时，平台才把沙箱路由与凭证注进去。你一旦自己写了，注入整个跳过，沙箱基本必炸 |

> 唯一例外：**子 agent** 的 `sandbox_config` 是刻意保留的 —— 平台明确不覆盖子代理上显式声明的 `sandbox_config`，好让「有意让某个子代理跑在不同沙箱里」这种用法可行。要给子代理换沙箱后端时才写，主 agent 一律别写。

### 档 ② 写了没用 —— 无害噪声，会被平台无条件覆盖

写了不报错、不影响部署，但**一定不生效**。生成制品时直接省略；看到样例里有就删掉。

| 字段 | 被谁覆盖成什么 |
|---|---|
| `base_url` | 覆盖成 `LLM_BASE_URL`（= sidecar 本地地址）。模型目录（catalog）请求还会另从**原始**环境变量重算一次 base_url，同样不复用你写的值 |
| `api_key` | 覆盖成 `LLM_API_KEY`（= 占位符字面量） |
| `api_type` | 只要最终 model 全键命中模型卡，按卡片派生值覆盖（runtime 日志会明写 `overriding agent.yaml`） |
| `stream` | **流式 chat 路径**强制置 `True`（不管你写 true 还是 false） |

两条边角，知道即可，不改变「别写」的结论：

- `api_type` 的覆盖**条件是 model 命中卡片**。model 没命中且没回落时（见 §3.3），你写的 `api_type` 会原样留着 —— 但那种状态下每次 chat 已经 422 了，没有实际意义。
- `stream` 只在流式路径被强制；非流式 `query` 路径保留 yaml 值。仍然别写：NAC 的 `/agent-api/chat` 是流式路径。

### 档 ③ 由你决定 —— 平台只补缺，不改你写的值

| 字段 | 说明 |
|---|---|
| `model` | 见 §3。**唯一需要认真想的字段。** |
| `temperature` | 平台**不做任何运行期纠正**：用户填什么就是什么（早期「开 thinking 时自动把 temperature 归一成 1」的行为已删除）。填错由上游模型报错，见 §5 指南表 |
| `max_tokens` | 未写时：anthropic 家族兜底 **8192**；openai 家族不兜底 |
| `top_p` / `frequency_penalty` / `presence_penalty` | 原样透传，无兜底 |
| `timeout` | 未写时兜底 **300.0 秒** |
| `thinking` / `output_config` / `budget_tokens` | anthropic 家族专属；跨 api_type 会被剔除（§5.4） |
| `reasoning` / `max_output_tokens` | openai_responses 专属；同上 |
| `max_iterations` 等 | **不属于 llm_config**，是 agent.yaml 顶层字段，见 `references/agent-yaml-fields.md` |

⚠️ **`llm_config` 内部字段完全不经过 pydantic 校验**：构造 `LLMConfig` 时，所有它不认识的 key 会被原样收进 `extra_params`。拼错的键（`temperture`）不会报错，会作为 extra param 原样送给上游 SDK，可能触发 `unexpected keyword argument`，也可能被静默忽略。**别指望框架帮你抓拼写错误。**

---

## 2. `tracers`：运行期是合并，但官方规范禁写 → **结论仍是别写**

分两层看，两层结论不同，别只记一半：

| 层 | 结论 | 依据 |
|---|---|---|
| **运行期（框架/平台注入）** | 平台 tracer 与制品自带 `tracers` 是**合并**关系，不是互斥；写了功能上能用 | 平台侧实测行为，见下 |
| **官方制品规范（静态校验器）** | `tracers` 与 `sandbox_config` 并列在校验器的禁写字段表里，出现即判 **error**（`agent.field.forbidden`） | 制品静态校验规则 |

**实践结论：别在 agent.yaml 里写 `tracers`，观测交给平台。**
（旧 skill 把它和 `api_key` 并列写进「🚫 禁止字段」，理由说错了——不是"写了会被覆盖/会坏"，
而是"规范不允许"；运行期其实是合并的。见 `artifact-spec-checklist.md` §3。）

合并行为（说明运行期确实支持自定义 tracer，仅供理解）：平台在每次请求上装配 tracer 时，会把**自己注入的 tracer**和**你在 agent.yaml 里声明的 `tracers`** 拼成一个 composite 一起生效，而不是二选一。平台 tracer（Langfuse / Jaeger composite）排在队首（primary position），你的 tracers 依次追加在后。自定义 tracer 是**被支持的**能力。

---

## 3. `model`：三种写法与判定

### 3.1 三种合法写法

| 写法 | 语义 | 何时用 |
|---|---|---|
| `${env.LLM_MODEL}` | **follow-default**：跟随项目/环境默认模型；管理员改默认模型后该 agent 自动跟随（Gateway 缓存刷新即漂移） | 默认推荐。除非有明确锁定需求 |
| `provider/model_name` 全键（如 `nex-agi/claude-opus-4-8`） | **钉死**在那张卡上，不随平台默认变 | 业务对模型能力有硬依赖时 |
| 省略 `model` 键 / 省略整段 `llm_config` | 同样是 follow-default（⚠️ 但**不是**更安全的写法，见 §3.4） | 完全不关心模型时 |

平台按下面这套规则判定一份制品算不算 follow-default（前三条都算）：

| 制品里的写法 | 是否 follow-default |
|---|---|
| 整段 `llm_config` 缺席 | ✅ 是 |
| `model` 字面量就是 `${env.LLM_MODEL}` | ✅ 是 |
| `model` 键缺席、为 `null`、或是纯空白字符串 | ✅ 是 |
| `llm_config` 被写成标量（不是映射） | ❌ 否 |
| `model` 是具体的 `provider/model_name` 全键 | ❌ 否（钉死） |

判定为 follow-default 时，平台每次请求都用**当次重新算出的**兜底模型；否则保留你写死的全键。

> 全键按**第一个 `/`** 拆 provider，model 名本身可以再含 `/`。

### 3.2 🚫 裸名（无 `provider/` 前缀）—— 比写错全键更糟

`model: claude-opus-4-8` 这种写法：

1. **sidecar 直接 Reject，不走任何回落**：模型名缺 `provider_name/` 前缀时，sidecar 判定它不可路由并直接拒绝（拒绝原因就写着 `has no provider_name/ prefix`），对外表现为 **HTTP 422 + `{"code":"LLM_PROVIDER_UNROUTABLE"}`**，每次 chat 都失败。
2. **制品静态校验器判 error**，制品过不了校验。

**规则：`model` 必须是 `provider/model_name` 全键，或 `${env.LLM_MODEL}`。没有第三种。**

### 3.3 ⚠️「优雅回落」是**有条件**的

旧 skill 把「model 写错 → 优雅回落项目默认」写成无条件成立，**错**。回落只在两个前提同时成立时才发生：**① 项目至少有一张可见模型卡**，**② 平台注入了兜底模型 `LLM_MODEL`**。而且一旦触发回落，平台就把整段 `llm_config` 判为不可信，只留下连接信息。

| 前提 | 结果 |
|---|---|
| 项目有可见卡 **且** `LLM_MODEL` 已注入 | 回落到 `LLM_MODEL`。**但整段 llm_config 被判为不可信** —— `temperature` / `max_tokens` / `top_p` / `thinking` / `output_config` / `reasoning` **全部丢弃**，只保留连接信息 |
| 项目一张可见卡都没有 **或** `LLM_MODEL` 未注入 | **不回落**，model 原样保留 → sidecar 每次 chat 返回 **422 `LLM_PROVIDER_UNROUTABLE`**（runtime 日志会留一行 `LLM_MODEL not set; leaving model as-is`） |

> ⚠️ 别把「路由表空」等同 503。chat 路径上只要请求体里有 `model` 字段，路由表为空同样是解析失败 → 拒绝 → **仍是 422**。503 `no LLM provider configured` 只出现在另一条分支——**请求体不是合法 JSON 或压根没有 `model` 字段**、或走的是非 chat 端点（`/v1/embeddings`、`/v1/models`）**且**路由表为空时。制品作者日常见到的是 422。

两条必须写进制品作者脑子里的推论：

- **「模型名打错一个字母」= 采样参数静默全丢**，日志只有一行 INFO，很难自己发现。
- **未授权 / 隐藏未解锁的模型卡对项目「等同不存在」**：不进 sidecar 凭证表、不进 META、不进兜底候选。写了未授权卡片 ≡ 写了不存在的卡片。

### 3.4 ⚠️ `${env.LLM_MODEL}` 也可能让 agent 加载不起来

`LLM_MODEL` 这个环境变量是**条件注入**的：平台只有在能解析出兜底模型时才把它塞进 runtime pod；解析不出来时**这个 key 根本不存在**（不是空串）。

兜底模型的解析是四档漏斗，**全部以「项目可见卡片集」为唯一取数源**：

| tier | 规则 |
|---|---|
| tier-0 环境默认 | 环境配的全键必须 ∈ 可见集才用，否则降级 |
| tier-1 项目默认 | 项目配的全键必须 ∈ 可见集才用，否则降级 |
| tier-2 平台默认卡 | 从可见集里找标记为「平台默认」的卡 |
| tier-3 第一张可见卡 | 可见集为空才算彻底解析不出 |

**项目一张可见卡都没有 ⇒ 四档全落空 ⇒ `LLM_MODEL` 这个 env 根本不存在 ⇒ agent.yaml 里的 `${env.LLM_MODEL}` 在加载期直接抛 ConfigError，agent 起不来。**

原因：`${env.X}` 的替换发生在 YAML 解析**之前**，引用一个不存在的环境变量会直接抛
`ConfigError: Environment variable 'LLM_MODEL' is not set`。

⚠️ **省略写法并不能绕开这个失败**（本条已实测）。项目零可见卡时三种写法都在加载期挂，只是异常类型不同：

| 写法 | 项目零可见卡时的加载结果 |
|---|---|
| `model: ${env.LLM_MODEL}` | `ConfigError: Environment variable 'LLM_MODEL' is not set`，在 YAML 被解析之前就炸 |
| 有 `llm_config` 但省略 `model` 键 | `ValueError: Model not found in environment variables` —— 运行时的默认模型注入**只在整段 `llm_config` 缺席时才触发**，本例不触发；SDK 于是自己去环境里找，依次查 `MODEL` / `OPENAI_MODEL` / `LLM_MODEL`，全落空即抛错 |
| 整段省略 `llm_config` | 同样 `ValueError: Model not found in environment variables` —— 运行时补进去的默认模型取自 `LLM_MODEL`，而该 env 不存在时补进去的是**空串**，空串同样被判为「没给 model」，照样落回上面那条环境变量查找链 |

**推论：三种写法在「项目没有任何可见模型卡」这件事上没有安全差异，都是加载期硬失败。** 真正的修法是给项目授权至少一张模型卡，不是换 yaml 写法。

---

## 4. 平台注入的 LLM env 的真实取值

`${env.X}` 只能读到 **runtime pod 的环境变量**。NAC 上这三个 key 的真实值：

| env | 真实值 |
|---|---|
| `LLM_BASE_URL` | `http://localhost:{sidecar 的 llm 端口}/v1` —— **sidecar 的本地地址，不是任何上游 API** |
| `LLM_API_KEY` | 字面量 `"placeholder-sidecar-injected"` —— **占位符，不是真凭证**（运行时内部另有一处等价占位符 `sk-placeholder`） |
| `LLM_MODEL` | 平台解析出的兜底模型全键；**无兜底模型时该 env 不存在**（§3.4） |
| `LLM_API_TYPE` | 🚫 **平台不再注入**。见下 |

真凭证只在 **sidecar 进程内**（`NEXAU_AGENT_RUNTIME_SIDECAR_*` 前缀），runtime 容器永远拿不到。这就是「制品里写 `api_key` 毫无意义」的物理原因。

### 4.1 🚫 `api_type: ${env.LLM_API_TYPE}` 会让 agent 直接加载失败

平台已不再注入 `LLM_API_TYPE`（连同同期废弃的 `LLM_EXTRA_PARAMS`，两者现在都被忽略）。而引用一个未设置的 `${env.X}` 会在加载期抛 ConfigError（§3.4）。

**历史文档 / 老模板里如果出现 `api_type: ${env.LLM_API_TYPE}`，直接删掉整行。**

### 4.2 用户自建 env var 覆盖不了这三个 key

合并环境变量时，平台先铺你自建的那份、再用平台自己那份覆盖写 —— 这几个 key 是保留键，**平台永远赢**。另外后端还有一道 scope 守卫：`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 设成 sandbox scope 直接 **400**，`LANGFUSE_*` 任何 scope 都 400。
唯一例外：项目无可见卡时平台不注入 `LLM_MODEL`，此时用户在 runtime scope 设的 `LLM_MODEL` 能存活。

### 4.3 `base_url` / `api_key` 省略永远安全；`model` 省略只在有卡时安全

你不写这三个字段时，SDK 会自己去环境变量里找，各自有一条按序查找链：
`model` 查 `[MODEL, OPENAI_MODEL, LLM_MODEL]`、`base_url` 查 `[OPENAI_BASE_URL, BASE_URL, LLM_BASE_URL]`、`api_key` 查 `[LLM_API_KEY, OPENAI_API_KEY, API_KEY, ANTHROPIC_API_KEY]`。**三者各自整条链都落空时都抛 `ValueError`。**

- `base_url` / `api_key`：平台**无条件**注入这两个 key，所以省略永远拿得到值 → 安全。写 `${env.LLM_BASE_URL}` / `${env.LLM_API_KEY}` 是**三重冗余**：SDK 自己会读，读到的值紧接着又被平台覆盖一次。
- `model`：`LLM_MODEL` 是**条件注入**（§3.4）。项目零可见卡时省略 `model` → `ValueError: Model not found in environment variables`，agent 起不来。

---

## 5. 采样参数优先级链

### 5.1 部署期链（无 Gateway catalog 的请求）

```
agent.yaml 显式  >  纯 switch 三选一（环境固化 | 项目固化 | 模型卡 default_params）  >  平台兜底
```

⚠️ **中间那层是 switch，不是逐键 union**：平台按「环境固化 → 项目固化 → 模型卡默认」的顺序找**第一个存在的那一份**，用它去补参数，然后**直接跳过**剩下两档。

环境对该模型有固化就**整块用环境那份**，项目和卡片的键一个都不补（哪怕环境那份是个空表）。极易误写成「三层逐键合并」。
补参数时也只填**当前还是空**的键，不会覆盖你已经写了值的键。运行时日志会写明这次用的是哪一档（`environment defaults` / `project defaults` / `model card '...' params`）。

### 5.2 请求期链（经 Gateway 下发 catalog）

```
per-request 顶层 params  >  per-request providers 点名 params  >  agent.yaml 显式  >  环境固化  >  项目固化  >  模型卡默认
```

「算不算 yaml 显式」的判定口径：该键的**任一别名**命中、或它作为直接字段有非空值、或它已经躺在 `extra_params` 里 —— 满足任一条就算显式，catalog 下发的同名键不再覆盖它（除非该键在这次请求里被点名强制）。

⚠️ 边角（会咬人）：这里参与比对的那份 llm_config 是**已经过部署期兜底填充**的版本，因此部署期兜底填进去的 `timeout=300` 和 anthropic `max_tokens=8192` 也会被当成「yaml 显式」，从而挡掉 catalog 下发的同名键。

### 5.3 平台兜底（恒定）

| 条件 | 兜底值 |
|---|---|
| `timeout` 未写（且别名族未命中） | `300.0` 秒 |
| `api_type ∈ {anthropic_chat_completion, anthropic}` 且 `max_tokens` 未写 | `8192` |

（anthropic SDK `messages.create` 缺 `max_tokens` 会每个 turn 首次调用即失败，所以这个兜底是必需的。）

### 5.4 跨 api_type 专属键会被剔除

平台按下表只保留**本 api_type 的**专属键，其余家族的专属键会 warn + 删掉（通用键 / 未知键不动）：

| api_type | 允许的专属 extra 键 |
|---|---|
| `anthropic_chat_completion` / `anthropic` | `thinking` / `output_config` / `budget_tokens` |
| `openai_responses` | `reasoning` / `max_output_tokens` |
| `openai_chat_completion` | （空集） |
| `gemini_rest` | `thinking_budget` / `include_thoughts` |

所以在 anthropic 上写 `reasoning`、在 openai_responses 上写 `thinking` 都会被静默删掉。

### 5.5 temperature 选择指南

平台**不再**对 temperature 做任何运行期纠正（早期那套「开 `thinking` 就自动把 temperature 归一成 1」的行为已经删除）。**填什么就是什么，合法性由上游模型裁决。**

| 场景 | temperature | 理由 |
|---|---|---|
| 法律 / 医疗 / 金融问答 | 0.0 – 0.2 | 需要精确引用，禁止发挥 |
| 通用问答 / 客服 | 0.2 – 0.4 | 准确性优先 |
| 创意写作 / 头脑风暴 | 0.5 – 0.7 | 需要多样性 |

⚠️ **anthropic 家族开 `thinking` 时上游要求 `temperature: 1`**，平台不会帮你改。要么显式写 `temperature: 1`，要么整个别写 temperature（让它保持 None）。写 `temperature: 0.2` + `thinking: enabled` 会原样发上去，由上游报错。
> 「上游会拒」是模型侧约束。一个旁证：平台在 §3.3 那种回落场景里**特意丢弃** temperature，给出的理由正是「避免把 agent 的 temperature 灌进开了思考的 anthropic 调用而**被上游拒**」。

---

## 6. 排障心智

### 6.1 部署成功 ≠ 模型配对了

**上传 / 部署期完全不校验 `llm_config` 的 model / provider 可路由性。**

> 平台侧的部署逻辑已经明确不再读取 / 校验 agent.yaml 的 `llm_config`，**不**校验 provider/model 是否可路由 —— 即非法 provider 不再在 deploy 期 fail-fast，而是 **chat 期每请求 422**。

上传期只做结构校验（agent 文件存在 / 非空）。所以：**部署绿了什么都不代表，必须发一次真 chat 才算验证过。**

### 6.2 「Agent 用的模型不是 yaml 写的那个」查证顺序

| # | 检查 | 怎么查 |
|---|---|---|
| 1 | model 是不是裸名？ | 没有 `provider/` 前缀 → 必 422，先修这个（§3.2） |
| 2 | 全键是否命中**本项目可见**的卡片？ | 未授权 / 隐藏未解锁的卡 ≡ 不存在。在平台模型配置里确认该卡对本项目可见 |
| 3 | runtime 日志有没有回落记录？ | 搜 `has no matching model card`：带 `falling back to project LLM config (model='...')` = 走了回落（**采样参数已全丢**）；带 `LLM_MODEL not set; leaving model as-is` = 没回落，随后 422 |
| 4 | api_type 被改了？ | 搜 `deriving api_type for model card` —— 平台按卡片覆盖是**预期行为**，不是 bug |
| 5 | 采样参数明明写了却没生效？ | 先排 3（回落连坐丢参数），再看是不是被环境/项目固化的 switch 整块取代（§5.1），最后看 runtime 日志里那行「这次补参数用的是哪一档」（`environment defaults` / `project defaults` / `model card '...' params`） |
| 6 | 请求返回 422 `LLM_PROVIDER_UNROUTABLE` | 报文 `message` 会写 `not found in routing table (was the card deleted/hidden/renamed after upload?)` 或 `has no provider_name/ prefix` —— 直接指出是哪一类 |
| 7 | 请求返回 503 `no LLM provider configured` | **不是**「model 写错」这一类。只可能是：请求体非法 JSON / 无 `model` 字段，或走的是非 chat 端点，**且**路由表为空。chat 路径的模型问题一律 422 |
| 8 | agent 起不来，`ConfigError: Environment variable 'LLM_MODEL' is not set` | 项目一张可见卡都没有（§3.4）。不是你的 yaml 语法问题 |
| 9 | agent 起不来，`ValueError: Model not found in environment variables` | 同 8 的根因，只是你的 yaml 省略了 `model`（或整段 `llm_config`），异常从 SDK 侧抛出（§3.4 表）。修法一样：给项目授权模型卡 |
| 10 | agent 起不来，`ConfigError: Environment variable 'LLM_API_TYPE' is not set` | 删掉 `api_type: ${env.LLM_API_TYPE}` 那一行（§4.1） |

### 6.3 平台不改写你的 agent.yaml

以上所有解析全部在**运行期内存**里完成 —— 平台是复制一份配置再改，不回写文件；制品目录在运行期本来就是只读挂载。
**推论：拉下来的制品 agent.yaml 永远是你上传的字节 —— 用它来判断「实际生效的模型/参数」是错的，必须看 runtime 日志。**

---

## 7. `base_url` / `api_key` 的合法出现位置

「顶层 `llm_config` 不写 base_url/api_key」**不等于**「制品里任何地方都不能出现 base_url/api_key」。以下两处是合法且必要的：

### 7.1 LLMFailoverMiddleware 的 `fallback_providers`

主 provider 失败时切备用端点，备用端点的连接信息**必须**由你提供 —— 它不经过 sidecar 路由，中间件是拿你这份配置直接拼出一个新的 LLM 客户端去打。

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
- fallback 里**没写的字段继承主 provider**：中间件是以主 config 为底、再拿你写的这几个键逐个覆盖上去。
- ⚠️ **凭证仍然不要写字面量**：静态校验器只扫顶层 `llm_config.api_key`，middleware params 里的字面量 key **不会被拦下**，但一样是凭证进制品。用 `${env.X}` + runtime scope 环境变量（见 `references/env-vars-and-secrets.md`）。
- 备用端点必须是 runtime pod 能直连的地址；离线 / 内网环境要先确认网络策略放行。
- ⚠️ `${env.MY_BACKUP_LLM_KEY}` 这类自建 key **必须先建成 runtime scope 环境变量再部署**，否则 agent 在加载期就 `ConfigError: Environment variable '...' is not set`（`${env.X}` 的替换发生在 YAML 解析之前，**写在 YAML 注释里的占位也一样会被解析**）。

### 7.2 「接自己的 LLM 网关」= per-request，不是 agent.yaml

在 agent.yaml 里把 `base_url` 指向自己的网关是**彻底无效的**（§1 档②：部署期覆盖和 catalog 请求两条路径都强制用平台注入的 `LLM_BASE_URL`）。正确做法是走 chat 请求体的 `override_llm_configs`（旧名 `llm`）：

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

字段名与形状由**平台网关**定义：新名 `override_llm_configs`，旧名 `llm` 仍作回落；形状是「顶层 `model` / `base_url` / `api_key` / `api_type` / `params` + 可选 `providers`」。

| 目的 | 请求体 | 效果 |
|---|---|---|
| 换端点 + 换 key | `{"override_llm_configs": {"base_url": "...", "api_key": "..."}}` | 两者都换成你给的 |
| 只换 key，端点仍走平台 | `{"override_llm_configs": {"api_key": "sk-..."}}` | `base_url` 保留平台值 |
| 只换模型（平台已授权卡） | `{"override_llm_configs": {"model": "provider/model"}}` | — |
| 只调采样 | `{"override_llm_configs": {"params": {"temperature": 0.3}}}` | — |

⚠️ **给了自定义 `base_url` 却没给 `api_key` → 网关直接 400**（防止把平台的真 key 发到第三方端点）。报文会指出是哪个 key 上「base_url 为客户端来源但 api_key 为平台来源」。这是这条路径上唯一保留的语义 400，其余残缺组合都不报错。

⚠️ 上表是**网关下发 catalog** 这条路径的语义。运行时侧还有一条**不经 catalog 的旧路径**，它对 `{model, base_url, api_key, api_type}` 做**严格四规则分类**，残缺组合不报错、而是静默回落到 agent 默认模型并推一帧 `MODEL_FALLBACK`：

| 规则 | 组合 | 行为 |
|---|---|---|
| R1 | 四个全非空 | 自定义模型直连 |
| R2 | `base_url` + `api_key` 非空，`model` / `api_type` 空 | 只换连接 |
| R3 | 只有 `model` 非空 | 平台预设，走 sidecar |
| noop | 四个都空 | 什么都不改 |
| 其余 | 含只给 `api_key`、只给 `base_url` | 回落 + `MODEL_FALLBACK` |

**结论：跨两条路径都稳妥的写法只有 R1 / R2 / R3 三种完整组合。**「我传了 override 但模型没变」先对照这三条。

---

## 8. 反例速查（照着删）

老模板 / cookbook 里常见的写法，逐行标注：

```yaml
llm_config:
  model: ${env.LLM_MODEL}
  base_url: ${env.LLM_BASE_URL}      # ← 删：被 sidecar 地址无条件覆盖
  api_key: ${env.LLM_API_KEY}        # ← 删：被占位符覆盖；写字面量还会被静态校验器判 error
  api_type: openai_chat_completion   # ← 删：被模型卡派生值覆盖
  stream: True                       # ← 删：流式路径平台强制 True
  max_tokens: 32000                  # ← 保留：有效
  temperature: 0.2                   # ← 保留：有效
```

老模板里 `api_type` 还有另一个变体 `api_type: ${env.LLM_API_TYPE}`（本文没把它写进上面这段，因为 **`${env.X}` 的替换发生在 YAML 解析之前，写在 YAML 注释里同样会被解析并 ConfigError**）。见到它 **🚫 必删整行**（§4.1）。

清理后：

```yaml
llm_config:
  model: ${env.LLM_MODEL}
  max_tokens: 32000
  temperature: 0.2
```
