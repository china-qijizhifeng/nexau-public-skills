# 会话、沙箱与文件 IO —— 制品的「时间维度」与调用契约

> **本文覆盖什么**：一个制品跑起来之后、**跨轮**发生的事——多轮历史谁存的、沙箱活多久、
> 用户上传的文件落在哪、生成的文件怎么回到用户手里、多 agent 制品每次 chat 要带什么。
>
> **什么时候读**：写任何**对话型 / 多步骤 / 处理用户上传材料**的制品之前必读；
> 出现「历史变两份 / 换了 prompt 老对话还在 / Agent 找不到用户上传的文件 /
> 上一轮生成的文件不见了 / 集成方调 chat 报 400」时先查这里。
>
> 其余三份的分工：路径**空间**布局在 `nexau-json-and-packaging.md` §8；`variables` 三通道与鉴权
> 在 `env-vars-and-secrets.md` §10；上下文压缩在 `middlewares.md`。本文只讲**时间**与 **IO**。

---

## 0. 30 秒结论表

| 结论 | 一句话 | 详见 |
|---|---|---|
| 历史是框架存的 | 按 `(user_id, session_id, agent_id)` 自动持久化 + 自动恢复，制品和调用方都不用管 | §1.1 |
| **多轮记忆没有开关** | 是默认行为，`agent.yaml` 里配不了、也别问用户「要不要」 | §1.5 |
| **`messages` 只传本轮新消息** | 回传全历史 = 和恢复出来的历史**叠加**，一轮翻一倍 | §1.2 |
| 换 systemprompt **清不掉**历史 | 只换 system 消息，历史原样保留；要干净上下文只能换 `session_id` | §1.3 |
| 同一 session 里换 `agent` 名**不给你新历史** | 顶层 agent 共用 session 的 `root_agent_id` → 共用同一条历史 | §1.3 |
| 沙箱是 **session 级**的 | 同 session 跨轮复用；`/home/user` 的中间产物、缓存下一轮还在 | §2 |
| 换 `session_id` = 全新空沙箱 | 上个 session 的文件全部不可见；跨 session 留东西必须落外部存储 | §2 |
| 用户上传落 `/home/user/uploads` | 沙箱内 `$NEXAU_UPLOADED_FILES_DIR`；PDF 平台**已经替你转好** Markdown | §3 |
| ≥2 个 agent 时 chat **必须带 `agent`** | 否则 Runtime 400 | §4 |
| 非流式 chat 有 300s 整请求上限 | 长任务必须 `"stream": true` | §5 |

---

## 1. 多轮记忆：历史由框架持久化，调用方只传本轮新消息

### 1.1 机制（这是整个对话行为的地基）

Agent 的 `history` 不是普通 list，是一个会自动落库的 `HistoryList`，键是三元组：

```python
# nexau/archs/main_sub/agent.py:251-258
self._history: HistoryList = HistoryList(
    session_manager=self._session_manager,
    history_key=AgentRunActionKey(
        user_id=self._user_id,
        session_id=self._session_id,
        agent_id=self.agent_id,
    ),
    agent_name=self.agent_name,
)
```

`AgentRunActionKey` 定义在 `nexau/archs/session/agent_run_action_service.py:136-140`。
存储走 Session Manager（事件溯源，APPEND / UNDO / REPLACE 三类 action）。

**每次 chat 请求，Runtime 都新建一个 Agent 对象**（非流式 `server.py:5985-5993`，
流式 `server.py:6932-6940`，两处都是 `Agent.create(config=…, session_manager=…, user_id=…, session_id=…)`）。
所以每轮都会走一遍「恢复 → 追加」：

| 步骤 | 代码 | 行为 |
|---|---|---|
| ① 判断是不是本进程首次 run | `agent.py:1171` `if not self.history:` | 新建的 Agent 恒为空 → **每个请求都会进这个分支** |
| ② 从存储恢复 | `agent.py:1172` `load_messages(key=history_key)` | 取回该三元组下的全部历史 |
| ③ 换掉 system 消息 | `agent.py:1183-1189` `replace_all(system_messages + stored_non_system_messages)` | **只有 system 被换成本次渲染的 prompt**，非 system 消息原样保留 |
| ④ 追加调用方给的 `history=`（NAC 不用） | `agent.py:1207-1209` `self.history.extend(...)` | NAC 两条路径都不传 `history` 形参 |
| ⑤ 追加本轮 `message` | `agent.py:1211-1216` | `message` 是 **list 就整个 extend 进去** |

第 ⑤ 步是坑的来源：NAC 把请求体里**整个 `messages` 数组**当作「本轮消息」传进去——
`server.py:5934`/`6867` `messages = self._convert_messages(messages_raw)` → `server.py:6031-6037`/`7002-7007`
`agent.run_async(message=messages, …)`。而 `_convert_messages`（`server.py:7288-7294`）调
`messages_from_legacy_openai_chat`（`nexau/core/adapters/legacy.py:59-71`）
**逐条转换，不去重、不过滤、不只取最后一条**。

`user_id` 就是 `distinct_id`：网关 `chat.rs:390`
`user_id: auth.distinct_id.clone()`。

### 1.2 调用契约（照这个写集成代码 / 写文档给集成方）

| 字段 | 该传什么 | 传错的后果 |
|---|---|---|
| `messages` | **只传本轮新消息**，通常就一条 `[{"role":"user","content":"…"}]` | 回传完整对话 → 与恢复出的历史叠加，第 N 轮上下文膨胀 ~2 倍，模型会看到重复问答 |
| `session_id` | 一次会话固定一个（先 `POST /agent-api/sessions` 拿） | 每轮换一个 = 每轮都是新对话 + 新空沙箱 |
| `distinct_id` | 同一终端用户固定一个 | 换了 = 换 `user_id` = 换一条历史（键含 `user_id`） |

> 这条契约与平台自己生成的 API 脚本一致：`frontend/src/pages/Playground/buildApiScript.ts:100,152,220`
> 三种语言的 body 都只写 `messages: [{role:"user", content:"Hello"}]` 一条。

### 1.3 三件「你以为能做、实际做不到」的事

| 想干什么 | 实际 | 依据 |
|---|---|---|
| 改 systemprompt 让老对话「重新开始」 | ❌ 只有 system 消息被换掉，非 system 历史全部保留（§1.1 第 ③ 步）。用户会看到 Agent 顶着新人设继续接旧话茬 | `agent.py:1183-1203` |
| 调个 API 把某个 session 的历史清空 | ❌ **没有这样的端点**。`/agent-api/*` 只有 sessions(建) / chat / stop / user-message / files* / events / actions / runs；backend 的 sessions 路由只有 `list` | 同左 |
| 同一 session 里换 `agent: "b"` 拿一条独立历史 | ❌ **共用同一条**。NAC 建 Agent 时不传 `agent_id`、`is_root` 用默认 `True`（`agent.py:290`），`register_agent` 在 `is_root=True` 且 session 已有 `root_agent_id` 时**直接复用它**（`session_manager.py:170-194`）→ 三元组里的 `agent_id` 不随 agent 名变 | 同左 |

**唯一可靠的「重置对话」= 换一个新的 `session_id`。** 这也是为什么 `middlewares.md` 与
`troubleshooting.md` 里遇到上下文污染类问题一律建议「引导用户开新会话」。

### 1.4 对制品写法的影响

- **systemprompt 不要写「如果这是我们第一次对话…」这类分支**——你无法判断，历史是框架塞进来的。
- **别在 systemprompt 里塞会话状态**（「上一步你已经做完了 X」）：prompt 每轮重渲染，历史却是累积的，两者会打架。状态要么靠历史本身，要么落沙箱文件（§2）。
- **历史会一直涨**。上下文预算是顶层 `max_context_tokens`（默认 128000，`nexau/archs/main_sub/config/base.py:91`，
  经 `agent.py:764` 传进 Executor），真正做压缩的是 `ContextCompactionMiddleware`（见 `middlewares.md`）——
  两个旋钮管的正是这份累积历史。**不挂压缩中间件的长会话迟早会撞预算。**
- `save_memory` **不是**跨会话长期记忆：它把事实追加进沙箱 work_dir 下的 `GEMINI.md`
  （`nexau/archs/tool/builtin/session_tools/save_memory.py:19,128-129`），
  即 `/home/user/GEMINI.md` —— **随 session 走**，而且框架里没有任何地方会自动把它读回 prompt
  （全仓 grep `GEMINI.md` 只有该文件自己命中）。要用它就得在 systemprompt 里显式让 Agent 自己去读。

### 1.5 生成 agent.yaml 时：多轮记忆**不是一个要配的开关**

平台 A4A 的装配约定是：「生成或改写 `agent.yaml` 时必须默认支持同一会话内的多轮对话上下文记忆，
**不得询问用户是否需要该能力**。」

⚠️ **先把这条约定的真实含义说破**，否则很容易去找一个不存在的配置项：

**`agent.yaml` 里根本没有多轮记忆的开关。** §1.1 已经说清——历史由框架按
`(user_id, session_id, agent_id)` 三元组**无条件**持久化并在每次 chat 时自动恢复，
这是 `Agent` 的固有行为，不由任何字段控制。所以：

- 别去写 `memory:` / `enable_history:` / `conversation:` 这类字段——顶层是 `extra='forbid'`，
  写了直接加载期 `ConfigError`（见 `agent-yaml-fields.md` §6）。
- 别把「要不要多轮记忆」当成需求澄清题去问用户。**它已经是默认行为**，问了只会让用户以为可以关掉。
- 真正需要跟用户确认 / 需要你做取舍的相关项**只有一个**：这份会一直增长的历史**怎么压**
  （`max_context_tokens` + `ContextCompactionMiddleware`，见 §1.4 与 `middlewares.md`）。

**反过来，下面这些做法会真的破坏多轮记忆**——排查「Agent 记不住上文 / 上下文乱套」时按这张表查：

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| 调用方每轮回传**完整** `messages` | 与框架恢复出的历史**叠加**，一轮翻一倍，模型看到重复问答 | 只传本轮新消息（§1.2） |
| 每轮换一个新 `session_id` | 每轮都是新对话 + **新空沙箱**，前一轮产物全丢 | 一次会话固定一个（`POST /agent-api/sessions` 拿一次） |
| 每轮 `distinct_id` 传随机值 | `user_id` 变 → 三元组变 → 换了一条历史 | 同一终端用户固定一个（§1.2） |
| 以为「要自己存历史」：custom tool 往沙箱写 history 文件、或每轮把摘要拼进 systemprompt | 与框架恢复的历史打架，等于两份上下文；prompt 每轮重渲染，历史却累积（§1.4） | 交给框架；**跨轮要留的是业务状态、不是对话**，落沙箱文件（§2.1） |
| 靠换 systemprompt / 换顶层 `agent` 名来「开新对话」 | 都做不到，见 §1.3 | 换 `session_id` 是唯一可靠的重置 |
| 长会话不挂 `ContextCompactionMiddleware` | 历史一直涨到撞 `max_context_tokens` | 见 §1.4 / `middlewares.md` |

> 这是**装配约定**，不是上传期校验项：不写、写错都不会让部署失败，坏的是线上对话体验。

---

## 2. 沙箱的时间维度：session 级实体

| 问题 | 答案 | 依据 |
|---|---|---|
| 一次 chat 一个沙箱吗 | ❌ **一个 session 一个**。请求进来先查 session 已绑定的 `sandbox_id`，状态 `running`/`paused` 就直接接着用 | `server.py:4528-4542`（`Reusing existing sandbox`）；绑定关系存在 `nexau_sessions` 行上，查询走 `server.py:4755`（按 `project_id` + `user_id` + `session_id` 找 session 取 `sandbox_id`） |
| 上一轮写的文件还在吗 | ✅ 在。同一个沙箱，`/home/user` 就是上一轮那个 | 同上 |
| 空闲久了会怎样 | 自动 **pause**（不是删）：默认每 30s 巡检，空闲 300s 触发 idle auto-pause，pause 会先存快照 | （`check_interval_secs: 30, idle_timeout_secs: 300`）、`idle.rs:517-561`（走统一 `pause_sandbox_core`，K8s 下调 `save_snapshot_for_pause`） |
| 快照存了哪些目录 | `/home/user` + `/tmp` | （`tar -cf … -C / home/user`）、`config.rs:40-41,97`（`HOME_DIR` 默认 `/home/user`） |
| 换 `session_id` 呢 | 全新空沙箱，上个 session 的产物**一个都看不到** | `server.py:4528-4542` 查不到绑定 → 走 create new |
| 沙箱失联了会自动换一个吗 | ❌ 按设计**拒绝**建替身，直接报错 `Session is bound to sandbox <id>, but Runtime could not connect to it.` | `server.py:4635-4639`（设计注释：`A non-empty session sandbox_id is authoritative`）/ `server.py:4683`（报错文案） |

**内置文件工具全部作用在沙箱里**，相对路径按沙箱 `work_dir` 解析，而 `work_dir` 默认就是 `/home/user`
（`nexau/archs/tool/builtin/_sandbox_utils.py:26-30`、
`nexau/archs/sandbox/base_sandbox.py:169,192`）。

### 2.1 这条事实解锁的三种设计（多步骤制品照抄）

| 场景 | 设计 | 为什么成立 |
|---|---|---|
| 先解析材料、再逐条审核 | 第 1 轮把解析结果写 `/home/user/work/parsed.json`，后续轮次直接读它 | 同 session 跨轮同一沙箱 |
| 先生成结构化数据、再渲染成文档 | 生成阶段落 `/home/user/work/report.json`，渲染阶段读它产出 docx | 同上 |
| 首次编译 / 首次装依赖很贵 | 只在文件不存在时做，做完落沙箱当缓存 | 同上；`templates/07-doc-generation` 的渲染引擎缓存就是这个套路 |

写法建议：**固定一个工作目录**（如 `/home/user/work/`）并在 systemprompt 里写清楚布局，
让 Agent 每轮开工先 `list_directory` 一下——这比让它凭记忆猜文件在不在稳得多。

### 2.2 反模式

- ❌ **靠沙箱文件做跨用户 / 跨会话的持久化**（用户档案、审计留痕、统计）。换 session 就没了，
  更别提沙箱本身会被 idle pause / 回收。要持久化就走外部对象存储或数据库（凭据经 `sandbox_env` 注入，见 `env-vars-and-secrets.md`）。
- ❌ **每轮都从零重跑重活**（重新解析同一份 PDF、重新编译）。既慢又容易撞 §5 的 300s 超时。
- ❌ **写 `/agent`**。那是制品解压根，Python Runtime 下只读，见 `nexau-json-and-packaging.md` §8。

---

## 3. 用户上传的文件：`/home/user/uploads`

### 3.1 落点

| 事实 | 值 | 依据 |
|---|---|---|
| 上传落点 | `/home/user/uploads/<文件名>` | （`SANDBOX_UPLOADS_DIR` + `upload_target_path`）；Runtime 侧同一常量  |
| 沙箱内环境变量 | `$NEXAU_UPLOADED_FILES_DIR` = `/home/user/uploads` | `server.py:5886,6684`（注入进 `sandbox_env`） |
| 重名怎么办 | 平台自动改名（`a.txt` → `a (1).txt` …），不覆盖 | — |
| PDF 转换产物 | `/home/user/uploads/converted/{file_id}/` | — |

**这是 Agent 拿到用户材料的唯一入口。** 它在沙箱里、不在制品里，所以只能用内置文件工具（`read_file` /
`list_directory` / `Glob` / `read_visual_file` …）去读，不能用 custom tool 里的 `Path(__file__)` 那套。

### 3.2 平台的 session 文件通路（给集成方 / 给你写文档用）

网关六个端点，全部注册在 `lib.rs:471-495`，body 结构见
`files.rs:100-141`：

| 端点 | 干什么 | body |
|---|---|---|
| `POST /agent-api/files` | 上传（multipart），写进沙箱 `/home/user/uploads/` | multipart + `session_id`（header `X-Nexau-Session-Id` 优先，否则从 multipart 前缀解析；`files.rs:29,167-176`） |
| `POST /agent-api/files/list` | 列出本 session 已上传的文件（元数据） | `{session_id}` |
| `POST /agent-api/files/read` | 读回一个文件（按 `file_id` 或按沙箱绝对 `path`） | `{session_id, file_id? , path?}` |
| `POST /agent-api/files/delete` | 删除 | `{session_id, file_id}` |
| `POST /agent-api/files/listdir` | 列沙箱任意目录（分页） | `{session_id, path, offset?, limit?}` |
| `POST /agent-api/files/pdf-convert` | 把 PDF 转成 Markdown 包 | `{session_id, file_id? , path?}` |

> `files/read` 支持按 **path** 读 → 这就是「Agent 生成的文件怎么给用户」的答案（§3.5）。

### 3.3 ⚠️ PDF：平台通常**已经替你转好了**，别让 Agent 再转一遍

Playground / SimpleChat 上传 PDF 后会**自动**调 `pdf-convert`
（`frontend/src/pages/Playground/index.tsx:2758` `convertCloudSessionFile(...)`），
并把该文件的路径从原始 PDF 换成转换目录（`index.tsx:2782-2786`）。产物是固定约定：

```
/home/user/uploads/converted/{file_id}/
├── full_text.md      # 整篇正文（先读这份拿全貌）
├── page_{N}.md       # 单页正文
├── page_{N}.png      # 单页截图（看版面/表格/图片细节时用）
└── source.pdf        # 原始 PDF，一般不用
```

依据：`mod.rs:20-32,70`（渲染 + 写回）、
`frontend/src/services/api/cloudChat.ts:523-530,546`（同一约定的前端镜像）、
`frontend/src/pages/Playground/messageHelpers.ts:255-264`（拼给模型的四类路径）。

**所以：systemprompt 里教 Agent「先自己跑 OCR / pdf 转 md 脚本」在 Playground 主路径上是重复劳动**，
还多背一个 OCR 凭据依赖。正确写法是**先看有没有转好的 Markdown，没有才回退**。

> 另有一个平台内置工具 `pdf_to_markdown`（binding
> `nexau_cloud_agent_runtime.builtin_tools.pdf_to_markdown:pdf_to_markdown`，内置 Agent4Agent 在用：
> `builtin-agents/Agent4Agent/agent.yaml:41-43`），效果就是替你调 `pdf-convert`。
> **⚠️ 未核实它在普通用户制品里是否被放行**：它不在官方 canonical 内置工具映射表里
> （`nexau-artifact-rules/references/builtin-tool-bindings.json` 无此条），实测静态校验器会把它当
> 自定义 binding 处理并报 `tool.binding.import_error`。想用先跑一次校验器确认。

### 3.4 systemprompt 里该怎么写（可直接抄）

前端两个 composer 会把上传文件的**绝对沙箱路径**拼进 user message 正文，marker 是
`\n\nUploaded files:\n`（`frontend/src/pages/Playground/messageHelpers.ts:120,242-270`）——
所以走 Playground 时模型开局就有路径。但**纯 API 集成方不会自动做这件事**，
`buildApiScript.ts` 生成的官方脚本 body 里也没有任何文件路径。两种情况都要兜住：

```markdown
## 用户材料在哪

1. 如果本轮消息里带了 `Uploaded files:` 段落，**以里面给出的绝对路径为准**，不要另行猜测。
2. 消息里没给路径时，用 `list_directory` 看 `/home/user/uploads`（等同环境变量
   `$NEXAU_UPLOADED_FILES_DIR`），那是用户上传文件的落点。
3. 遇到 PDF：先看同名 `file_id` 下有没有 `/home/user/uploads/converted/<file_id>/full_text.md`。
   **有就直接读它**（平台已完成 OCR），只有确实只拿到未转换的 `.pdf` 时才自己动手转。
4. 找不到材料时**直接问用户**（`ask_user`），不要用 `Glob` 在整个文件系统里乱搜。
```

### 3.5 产物怎么回到用户手里

| 方式 | 怎么用 | 依据 |
|---|---|---|
| **在回复里给绝对路径**（最省事） | Agent 输出 `/home/user/work/report.docx`，Playground 自动把它渲染成可点的 FileTag | `frontend/src/pages/Playground/filePathDetect.ts`（扩展名白名单含 `md`/`pdf`/`docx`/`xlsx`） |
| 侧边栏文件树 | Playground 的沙箱文件树按目录懒加载，走 `files/listdir` + `files/read` | `frontend/src/pages/Playground/useSandboxLazyTree.ts:83`、`SnapshotDrawer.tsx` |
| 集成方自取 | `POST /agent-api/files/read` 带 `{session_id, path}` 直接下载 | — |

**制品侧唯一要做的事：把产物写进沙箱 `/home/user/…`，并在回复里给出绝对路径。**
不要 base64 塞进回复正文（撑爆上下文），也不要指望有「附件」字段——chat 响应里没有。

---

## 4. 多 agent 制品的调用约定

| 情形 | 行为 | 依据 |
|---|---|---|
| `nexau.json.agents` 恰好 1 个 | chat 不带 `agent`，Runtime 自动选中 | `server.py:3340-3341` |
| **≥2 个且请求没带 `agent`** | **400** `Multiple agents registered, 'agent' parameter required` | `server.py:3343-3346` |
| 带了 `agent` 但名字不在清单里 | **404** `Agent '<name>' not found` | `server.py:3335-3338` |

字段名就是 `agent`（网关 `ChatRequest.agent: Option<String>`，
`chat.rs:95-99`，注释也写着「omitted + multiple → Runtime returns 400」），
值是 **`nexau.json` 里的 key**。

⚠️ **最晚暴露的坑**：Playground 在 agent 数 >1 时会自动带上这个字段
（`frontend/src/pages/Playground/index.tsx:3245`），所以你在 Playground 一路是绿的；
而平台「复制 API 脚本」生成的 curl / Python / JS **不带**它（`buildApiScript.ts` 全文无 `agent` 键）——
集成方照抄脚本就 100% 撞 400。

> 选型建议：**没有硬理由就只声明一个顶层 agent**，多角色用 `sub_agents`。
> 还有一条被忽略的代价见 §1.3——同 session 下多个顶层 agent **共用同一条历史**。
> 上传期结构校验与四种形态见 `nexau-json-and-packaging.md` §2。

---

## 5. 超时三层（调用方视角）

| 层 | 谁掐 | 生效吗 |
|---|---|---|
| agent.yaml 顶层 `timeout` | —— | ❌ **死配置**，改了没用 |
| `llm_config.timeout` | 单次 LLM 请求 | ✅ |
| **网关整请求超时**（默认 **300s**，仅**非流式**） | 一次 `/agent-api/chat` 的总时长 | ✅ 最容易先掐断的一环 |

分支在 `chat.rs:848-853`：`stream: true` 走
**no-timeout** 的 `runtime_stream_client`（`lib.rs:229-238`），否则走带
`.timeout(request_timeout_secs)` 的 `http_client`（`lib.rs:223-226`）；默认 300 来自
`lib.rs:2902-2904` → `:3323`，生产环境也是 300。

**调用契约：长任务一律 `"stream": true`**（省略 `stream` 等于 `false`）。
逐层证据与 `max_iterations` 的组合坑见 `agent-yaml-fields.md` §8（canonical），调用示例见
`env-vars-and-secrets.md` §10。

---

## 6. 交叉引用

| 想深入 | 去哪 |
|---|---|
| 运行时路径的**空间**布局（`/agent` 只读、两套相对路径基准） | `nexau-json-and-packaging.md` §8 |
| `nexau.json.agents` 的上传期校验与四种形态 | `nexau-json-and-packaging.md` §2 |
| chat 请求的鉴权、`variables` 三通道、可直接抄的 curl | `env-vars-and-secrets.md` §10 |
| 历史太长怎么压（`max_context_tokens` / ContextCompaction） | `middlewares.md` §3 |
| 超时三层的完整证据 | `agent-yaml-fields.md` §8 |
| `max_iterations` 该给多大（含它与 300s 超时的撞车） | `agent-yaml-fields.md` §1.4a |
| 报错文案对照 | `troubleshooting.md` |

## 未核实 / 边界说明

- **`pdf_to_markdown` 内置工具在普通用户制品里能否放行** —— 见 §3.3 的 ⚠️。
- **Rust Runtime（`backend: "nexau-rs"`）的会话历史语义**未逐行核实，本文全部结论基于 Python Runtime
  + NexAU 框架。用 Rust runtime 时请自行复核。
- **快照失败时的降级行为**（pause 存快照失败会不会丢文件）只核到「失败时保留 running 状态供下轮重试」
  （`idle.rs:560-572`），未做真机验证。

（框架侧核实于 NexAU SDK `0.5.0-11-g1cd84b61`。）
