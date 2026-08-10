# 九个证据面：怎么取、里面有什么、哪里会骗你

> 这一份是排障的地基。每一条都是**你自己就能拿到、自己就能看懂**的东西。
> 标「需 PAT」的走管理面，只有项目 AK/SK 的人用不了（见 SKILL.md §1）。

---

## 1. 响应头（成本最低的一手证据，`curl -i` 就有）

```bash
curl -i -X POST "$BASE/agent-api/chat" -u "$AK:$SK" \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"'"$SID"'","environment":"staging","stream":false,"messages":[{"role":"user","content":"ping"}]}' \
  2>&1 | grep -iE 'server-timing|x-nac-|retry-after'
```

| 响应头 | 什么时候出现 | 含义 |
|---|---|---|
| `server-timing: traceparent;desc="00-<32位>-<16位>-01"` | **几乎每个响应，成功的也有** | 中间那 32 位十六进制就是本次请求的 **trace id**，可直接 `nac trace <id>`；与 `/runs`、`/actions` 里的 `traceId` 是同一个值 |
| `x-nac-cold-start: true` | 只在慢路径上 | 这次请求**没命中已就绪的运行实例**，得先解析 / 拉起。「第一次特别慢」的直接证据，**不是故障，也不是你的 agent 慢** |
| `Retry-After: <秒>` | 伴随 429 | **按它的秒数退避**，别硬编码 |
| `x-nac-capacity-trace-id: <32位>` | 伴随 429 | 白送给你的 trace id，报障时贴这个 |

```bash
nac trace 4bf92f3577b34da6a3ce929d0e0e4736
```

---

## 2. 错误信封

**对话面**（`/agent-api/*`）的 HTTP 错误都是同一个形状：

```json
{"error":{"type":"authentication_error","code":"INVALID_CREDENTIALS",
          "message":"Invalid AK/SK credentials","request_id":"req_01K…",
          "param":"session_id"}}
```

- **`type`** 与 HTTP 状态码一一对应：400 `validation_error`、401 `authentication_error`、
  403 `permission_error`、404 `not_found_error`、409 `conflict_error`、
  413 `request_entity_too_large_error`、422 `unprocessable_error`、429 `too_many_requests_error`、
  502 `bad_gateway_error`、503 `service_unavailable_error`、504 `gateway_timeout_error`，其余 500 `internal_error`。
- **`param`** 只在参数类错误上出现，指出是哪个字段。
- **`request_id`** 只在错误响应里，`req_` + 26 位大写字母数字，**每次错误都是新的**。
  ⚠️ **你自己反查不了它** —— 唯一用途是报障时贴给平台方。
- ⚠️⚠️ **`code` 不可信**（详见 `error-codes.md`）：部分 4xx 的 `code` 恒填 `INTERNAL_SERVER_ERROR`；
  部分 403 的 `code` 恒填 `VERSION_NOT_ACTIVE`。**判错以 HTTP 状态码 + `message` 原文为准。**
- ⚠️ **管理面（`/api/*`）不保证这个信封**：鉴权失败经常只回一个裸状态码、响应体是空的。
  看到「401/403 但没有任何 message」时别怀疑自己漏读了，那就是全部信息。

---

## 3. `/runs` —— 排障第一站，一次请求回答一整串问题

```bash
curl -s "$BASE/agent-api/sessions/$SID/runs" -u "$AK:$SK" | jq '.runs[0]'
```

响应 `{"runs":[…]}`，**按开始时间倒序**，`runs[0]` 是最近一次。

| 字段 | 回答什么 |
|---|---|
| **`versionId`** | **哪个版本服务了这次请求** —— 部署是否生效的终极判据 |
| `status` | `submitted` / `working` / `input-required` / `completed` / `failed` / `canceled` |
| `error.message` | 失败原因摘要。**只在 `status == "failed"` 时可能出现，经常缺席** |
| `traceId` | 跳到 trace 的桥 |
| `agentName` | 实际跑的是哪个 agent / 子 agent |
| `source` | `playground` / `user` / `eval` / `im` / `dock` —— **判断这条流量是 API 打的还是界面点的** |
| `variables` | 这一轮实际生效的变量 —— 查「占位符没渲染」 |
| `distinctId` | 触发的终端用户 |
| `startedAt` / `finishedAt` | 耗时 |
| `rootRunId` / `parentRunId` | 串联父子 run |

**两个陷阱**：

- ⚠️ **`variables` 里的敏感值被打码成字面量 `***REDACTED***`，键名保留**。
  打码按**键名子串**匹配（`password` / `secret` / `token` / `api_key` / `credential` / `phone` …），
  **会误伤** `tokens_per_minute`、`token_budget` 这类普通业务字段。
  ⇒ **看不到值 ≠ 没传成功；想确认传没传，看键在不在。**
- ⚠️ **`error` 字段缺席 ≠ 没出错。** 失败原因是**三级回落**：
  ① `/runs` 的 `error.message` → ② `/actions` 里 `run_end` 的 `extra.reason` →
  ③ trace 里 `level = ERROR` 那个 span 的 `statusMessage`。

---

## 4. `/actions` —— 逐动作回放，排障信息密度最高

```bash
curl -s "$BASE/agent-api/sessions/$SID/actions?limit=50" -u "$AK:$SK" | jq .
```

**归一化 envelope**：

```json
{"actionIds":["…"], "entities":{"actions":{"<id>":{…}}, "runs":{"<runId>":{…}}}}
```

`actionIds` 是**唯一权威的顺序**（按时间升序）；`entities` 的 key 就是 id，实体自身不带 id 字段。

**五种 `actionType`**：

| actionType | 独有字段 | `extra` |
|---|---|---|
| `append` | `appendMessages` | 通常没有 |
| `replace` | `replaceMessages` | `{reason}`：`compact_auto` / `compact_focused` / `user_clear` / `unknown` |
| `undo` | `undoBeforeRunId` | `{reason}` |
| `run_start` | — | `{trace_id}` |
| **`run_end`** | — | **`{status, finished_at_ns, reason, trace_id}`** ← **排障主抓手** |

**Query 参数**：`after` / `before`（纳秒时间戳的**十进制字符串**）、`limit`、`parent_run_id`。

**三个会咬人的地方**：

1. **`limit` 传超过 500 不报错、被静默截到 500** —— 别据此断定「只有 500 条」。默认 50。
2. **`after` 和 `before` 互斥**，同时传 → 400 `after and before are mutually exclusive`。
3. **默认只返回顶层 run**，子 agent 的动作要传 `parent_run_id` 才看得到，且**一次只能下钻一层**。
   不传就看不到，很容易误判成「子 agent 根本没跑」。

⚠️ **`/actions` 里 run 的 `status` 是另一套原始词表**（`in_progress` / `ok` / `succeeded` /
`failed` / `error` / `cancelled` / `stopped` …），和 `/runs` 的六值词表**不是一套**。
**判终态以 `/runs` 为准，两套别混着断言。**

⚠️ session 不属于该凭据的项目 → **`404 session not found`**（不是 403，有意不泄露 session 是否存在）。

---

## 5. SSE 事件流

两个入口，**同一套 envelope**：

| 入口 | 语义 |
|---|---|
| `POST /agent-api/chat`（`"stream": true`） | 触发一轮 run，并在响应体里内嵌事件流。**生产集成走这个** |
| `GET /agent-api/sessions/{sid}/events` | **只读旁路**，纯实时尾随 |

### 5.1 五个终态帧，少认一个客户端就会卡死

`RUN_FINISHED` / `RUN_ERROR` / **`RUN_STOPPED`** / `LOCK_CONFLICT` / `TRANSPORT_ERROR`

⚠️ **`RUN_STOPPED` 最容易被漏掉** —— 它是你调 `POST /agent-api/stop` 时在原流里发出的那一帧。
解析循环不认识它就不会退出，**界面会永远停在「生成中」**。

三个错误帧的 payload 都只有 `message` 一个信息字段（`RUN_ERROR` 多一个 `run_id`）。

### 5.2 事件类型

按组（客户端 SDK 的类型枚举里有 20 个，装了 SDK 的人可以在自己的依赖里核对）：

| 组 | 事件 |
|---|---|
| 文本 | `TEXT_MESSAGE_START` / `_CONTENT` / `_END` |
| 思考 | `THINKING_TEXT_MESSAGE_START` / `_CONTENT` / `_END` |
| 工具 | `TOOL_CALL_START` / `TOOL_CALL_ARGS` / `TOOL_CALL_END` / `TOOL_CALL_RESULT` |
| 图片 | `IMAGE_MESSAGE_START` / `_CONTENT`(base64) / `_END` |
| 生命周期 | `RUN_STARTED` / `RUN_FINISHED` |
| 错误终态 | `RUN_ERROR` / `LOCK_CONFLICT` / `TRANSPORT_ERROR` |
| 通知 | `MODEL_FALLBACK` / `USER_MESSAGE_RECEIVED` |

⚠️ **实际流上还会出现枚举之外的 type**：`RUN_STOPPED`、`COMPACTION_STARTED`、
`COMPACTION_FINISHED`、`CONTENT_BLOCKED`。
⇒ **你的解析器必须对未知 `type` 宽容**（忽略而不是抛异常），同时**必须**识别那 5 个终态帧。

三条语义值得单独记：

- **`MODEL_FALLBACK`**：请求里指定的模型不可用时，平台**不报错**，回落到 agent 默认模型继续跑，
  只在 `RUN_STARTED` **之前**发一次 `{requested_model, effective_model, message}`。
  ⇒ **「我指定了模型但好像没生效」的唯一线索就是它。**
- **`TRANSPORT_ERROR` 是复用类型**：带 `reason: "sandbox_at_capacity"` + `retry_after`（整数秒，
  默认 5）时是**容量问题、按秒重试即可，不是你的代码错**；不带 `reason` 才是真的传输 / 执行异常。
- **`COMPACTION_STARTED` / `COMPACTION_FINISHED`**：上下文接近上限触发了自动压缩。看到它说明
  这一轮的历史被压过，「agent 忘了前面说过的话」有了解释。

### 5.3 四条会让你误判的规则

**① 以 `:` 开头的行是保活心跳，必须忽略。**
长时间没有新事件时（模型在思考、工具在跑），流里会周期性出现 `: heartbeat` / `: keep-alive`
这类注释行（`/chat` 流约 15 秒一条，`/events` 约 30 秒一条）。
用标准 SSE 客户端（浏览器 `EventSource`、`httpx-sse`、`aiohttp-sse-client`）不会有问题；
**只有自己 `split('\n')` 手搓解析器的人会踩**，表现为「聊到一半无缘无故断线重连」。

**② 结束标记是显式的 `data: [DONE]`，不是连接关闭。**
发出 `[DONE]` 之后服务端还要做收尾，这段时间连接仍开着。
等连接关闭才认为「回复结束」的客户端会**多等好几秒**，极端情况下一直停在「正在生成」。

**③ 流干净地关闭了，不等于跑完了。**
服务端在某些异常下会**直接关闭流而不发任何错误帧**。
⇒ **判断完成只能靠终态帧**；没收到终态帧就断了，**回查 `/runs` 看物化终态，不要直接重发 `/chat`**（会撞 409）。

**④ 一个 session 同时只允许跑一轮 run（但订阅不受限制）。**
- 上一轮没结束就再打 `POST /chat` → `409 SESSION_BUSY` 或流里 `LOCK_CONFLICT`。要抢占先 `POST /agent-api/stop`。
- ⚠️ **这把锁只管「跑」，不管「看」。** 只读订阅 `/events` 不抢锁：同一个会话**可以被任意多个客户端同时订阅**（复制页签、换台电脑打开同一个会话，两边都会正常流式）；一边读 `/chat` 的响应体、一边订阅 `/events` 也没问题 —— 前端本来就是这么做的。

### 5.4 `/events` 的补充语义

- **纯实时尾随，默认不回放历史。连晚了那段永久丢失**，历史只能去 `/actions` 补。
- 支持断线续传：重连时带 `Last-Event-ID` 头（或 `?last_event_id=`），事件 id 形如 `{毫秒}-{序号}`。
- 事件记录有**约 6 小时的滑动 TTL**（每来一条事件刷新）：会话闲置超过 6 小时后，旧的
  `Last-Event-ID` 续不上了。**历史不受影响**（历史在 `/actions`）。
- ⚠️⚠️ **非流式请求（`"stream": false`）全程不产生任何事件**，`/events` 一条都收不到。
  「非流式触发 + 另一个进程订阅 events 看进度」这个直觉架构**跑不通**。
  要实时就必须 `stream: true`；只要事后回查，用 `/actions` 和 `/runs`。
- 它接受项目 AK/SK、PAT、以及嵌入场景的 scoped token（`/actions`、`/runs` 同）——
  但**换凭据类型会换掉可见范围**，见 `symptom-index.md` 里 `404 session not found` 那条。

### 5.5 断流之后的兜底流程

1. 没收到终态帧 → **不要重发 `/chat`**（会撞 `SESSION_BUSY`）。
2. `GET /agent-api/sessions/{sid}/runs` 看这个 run 的物化终态。
3. 还在 `working` → 带 `Last-Event-ID` 重连 `/events` 续上。
4. 已经 `failed` → 从 `error.message` + `traceId` 往下查（三级回落见 §3）。
5. 真要停：`POST /agent-api/stop`。**默认 `force: false`（优雅停止），不要改成 `true`** ——
   `force: true` 会让已流出的思考 / 半截回复 / 半截工具参数**全部不落盘**，重新加载 session 也找不回。
   返回 `{"status":"noop"}` **不是失败**，意思是当前没有正在跑的 run。
   （请求体里的 `version_id` / `deployment_id` / `version_tag` / `environment` 对 stop **无效**，
   只作兼容保留。）

---

## 6. 运行日志（需 PAT）

见 `cli-reference.md` §5：两个日志源的分岔、三个静默失效的 flag、服务端真正认的参数、日志行格式。

**排障时在日志里搜什么**（这些字符串就是判据）：

| 搜什么 | 说明什么 |
|---|---|
| `WARNING: setup command failed:` | 清单 `setup` 里某条命令失败了，**但部署照样显示成功** |
| `Agent config not found` | 清单里声明的 agent 配置**路径写错**。平台只跳过不报错，对话时才炸 |
| `ModuleNotFoundError` / `ImportError` | 依赖没装上（多半是上面那条 setup 失败的下游） |
| `starting agent runtime initialization...` → `running setup commands...` → `>>> <cmd>` → `setup complete` → `agent project contents:` → `nexau.json:` → `starting agent runtime...` | 正常启动的路标序列。**卡在哪一行就说明卡在哪一步** |

---

## 7. Trace（需 PAT）

命令见 `cli-reference.md` §6。界面上走 **Observe** 面板
（Playground 里每条回复上的「查看 Trace」按钮可以直接跳过去，并自动带上定位参数）。

**span 详情里排障最有用的字段**：

| 字段 | 说明 |
|---|---|
| `type` | `SPAN` / `GENERATION` / `EVENT` |
| `level` | `DEBUG` / `DEFAULT` / `WARNING` / `ERROR`（ERROR / WARNING 会染色高亮） |
| **`statusMessage`** | **仅 `level === 'ERROR'` 时显示，这就是错误详情原文** ⭐ 排障要找的就是它 |
| `model` / `modelParameters` | 这一步实际用的模型和采样参数 |
| `usage.{input,output,total}` | token 用量 |
| `latency` | 单步耗时 |
| 顶部聚合 | Latency / Tokens / Cost / Spans / **TTFT** |

**三个限制**：

- 导出上限 **5 万个 span**，超了 `summary.truncated` 为 `true`。
- 单个 trace 太大会被拒：`413` + `Observations in trace are too large`。
- 导出中途上游出错时返回 **502 但响应体仍带已拉到的部分**，命令行只在 stderr 提示
  `⚠ upstream error after <N> observations` —— **脚本里只看退出码会误判成成功**。

**两条长得像权限问题、其实不是的**：

- **`🔒 [encrypted]`** = 项目开启了隐私域加密，**不是故障**。需要在 Playground 输入 passphrase 解锁。
  ⚠️ 口令**不被平台存储、无法找回**；忘了之后 agent 照常运行、加密写入不受影响，
  但**永久失去「解锁查看 / 关闭隐私域 / 轮换口令」这些操作**。
- **`403 Langfuse not configured`** = 这个项目没有配置 trace 存储（Langfuse 是平台用来存 trace 的组件），
  此时 `nac traces` / `nac trace` 全都用不了。**找平台管理员开通**，不是你的权限问题。

---

## 8. Web 控制台上的证据

**Playground**：

- 每条 assistant 消息上的 **「查看 Trace」** 按钮（有 trace 时才出现），点它跳到 Observe 并自动定位。
- ⭐ **「复制 API 脚本」按钮**（回复旁边带代码图标、标着 `API` 的那个）：把当前这次调用导出成
  **curl / Python / JavaScript**，含 AK/SK、路由字段、`session_id`。
  **这是「界面能跑通、我自己调 API 就不行」的最佳自救手段** —— 和你自己的请求逐字段对比。
  ⚠️ 导出的脚本有一处**不全**：它**不含** `agent` 字段。制品里声明了两个及以上 agent 时，
  界面能跑（Playground 自己补上了），照抄脚本却会 400 `Multiple agents registered, 'agent' parameter required`。
  ⚠️ 另有一条内建约束：**`environment` 和 `versionTag` 只能给一个**，同时给会拿环境名去 match
  版本号 → `VERSION_TAG_NOT_FOUND`。
- 429 容量拒绝的红条也带「查看 Trace」（trace id 来自 `x-nac-capacity-trace-id`）。
- **会话沙箱文件树**抽屉：懒加载列目录，可以直接看 agent 到底往沙箱里写了什么文件。
- 出网自测、路径持久性自测都在这里跑（让 agent 执行 shell 命令），见 `platform-limits.md`。

**Observe**：三栏 = Sessions 列表 → Trace(run) 列表 → Trace Inspector。
右上角有下载按钮导出 `trace-<traceId>.json`，状态 `complete` / `truncated` / `partial`。

---

## 9. `nac smoke` / `nac test`

见 `cli-reference.md` §7。两条纪律：

- ⚠️ **不要用 `GET /agent-api/chat/health` 判断部署可用** —— 它是静态返回 `{"status":"ok"}` 的探针，
  不检查运行实例、也不检查部署。**它绿了什么都不能证明。**
- `nac smoke` 的退出码（0/1/2）是**唯一**适合当 CI 卡口的端到端判据。

---

## 附：你够不着的东西（别往这些方向浪费时间）

以下都在平台内部，使用者**没有任何入口**：

- 集群 / 容器编排的任何命令、节点、事件、describe。你能拿到的日志只有
  `nac logs` / `nac versions logs` 这两个**受限投影**（固定容器、默认 200 行、环境级还替你滤掉了探针噪音）。
- 日志接口 `container` 参数的合法取值 —— 平台没有任何端点能列出一个运行实例有哪些容器。**保持默认。**
- 平台自身的指标 / 监控系统。你的观测面**只有 trace（经平台代理）+ 上面那两个日志源**。
- `/agent-api/health`、`/agent-api/chat/health` 这类探针端点 —— 对诊断无价值。
- 数据库、平台管理员后台（网络策略审批、模型卡、平台级资源上限）。
- 沙箱隔离档位（容器级 / 内核级）—— **你在使用侧无法自证**。要拿它做「能否运行不可信代码」的
  风险决策，请直接向平台方书面确认。
