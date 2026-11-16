# 错误速查：状态码 / `code` / message 原文

> **判错的正确顺序：HTTP 状态码 → `message` 原文 → 最后才是 `code`。**
> `code` 只适合做机读的粗分类，它在两处会骗你（见 §0）。

---

## 0. ⚠️ `code` 字段不可信的两处

1. **部分 4xx 的 `code` 恒填 `INTERNAL_SERVER_ERROR`** —— 包括**请求体校验失败**、
   **请求体超限**这类。HTTP 是 400 / 413 / 422，body 里的 `code` 却写着 `INTERNAL_SERVER_ERROR`。
2. **部分 403 的 `code` 恒填 `VERSION_NOT_ACTIVE`** —— **看到它不等于版本真的没激活**。
   真实原因可能是「这个 session 不属于你的项目」或「你这个账号对该项目没权限」。

⇒ 客户端可以在 `code` 上做粗分支（重试 / 不重试），但**人在判因时必须读 `message` 原文**。

> **经前置网关调用时，先判断这条报错到没到平台**：没有 `request_id` / `server-timing` 就是没到平台，本文件只管 NAC 自己的码。

---

## 1. 错误信封

```json
{"error":{
  "type":"too_many_requests_error",     // 与 HTTP 状态码一一对应
  "code":"TOO_MANY_REQUESTS",           // 机读码，见 §0 的两个例外
  "message":"runtime pod at capacity, please retry shortly",   // ⭐ 判因看这个
  "request_id":"req_01K…",              // 只在错误响应里，每次新生成，报障必带
  "param":"session_id"                  // 仅参数类错误才有
}}
```

**`type` ↔ 状态码**：400 `validation_error` · 401 `authentication_error` · 403 `permission_error` ·
404 `not_found_error` · 409 `conflict_error` · 413 `request_entity_too_large_error` ·
422 `unprocessable_error` · 429 `too_many_requests_error` · 502 `bad_gateway_error` ·
503 `service_unavailable_error` · 504 `gateway_timeout_error` · 其余 500 `internal_error`。

⚠️ **管理面（`/api/*`）不保证这个信封**：鉴权失败经常只回一个裸状态码、响应体是空的。
看到「401/403 但没有任何 message」时，那就是全部信息。

---

## 2. 按 `code` 速查

| HTTP | code | 含义与动作 |
|---|---|---|
| 400 | `FIELD_REQUIRED` | 缺必填字段，`param` 指出是哪个 |
| 400 | `FIELD_INVALID` / `INVALID_REQUEST` | 字段格式不对 |
| 401 | `MISSING_CREDENTIALS` | 没带 `Authorization`。**注意它不是 `INVALID_CREDENTIALS`** |
| 401 | `INVALID_CREDENTIALS` | 凭据错。⚠️ **项目不存在 / 被删也走这个码**，靠 `message` 区分 |
| 401 | `UNSUPPORTED_AUTH_SCHEME` | 用了不支持的认证前缀 |
| 403 | `VERSION_NOT_ACTIVE` | 目标版本未激活 —— ⚠️ **也可能是部署失败了**，也可能只是 §0 那个恒填 |
| 403 | `VERSION_NOT_IN_PROJECT` | 版本不属于该项目 |
| 403 | `VERSION_NOT_ROUTABLE` | **游离版本没绑到环境**，把它部署到一个环境即可 |
| 404 | `VERSION_TAG_NOT_FOUND` | 按 tag / 环境解析不到版本（常见自伤：把环境名当 `version_tag` 传） |
| 404 | `VERSION_NOT_FOUND` | 版本 id 不存在 |
| 404 | `RESOURCE_NOT_FOUND` | 通用未找到。⚠️ **session 跨项目 / 跨用户也返这个** |
| 409 | `SESSION_BUSY` | 同一 session 已有 run 在跑 |
| 413 | `PAYLOAD_TOO_LARGE` | 超大小上限（制品包 / 请求体 / 会话文件 / 单个 trace） |
| 429 | `TOO_MANY_REQUESTS` | 容量拒绝。读 `Retry-After` 退避 |
| 500 | `INTERNAL_SERVER_ERROR` | 平台内部错误 → **直接报障**。⚠️ 也可能是 §0 的恒填，先看状态码 |
| 502 | `RUNTIME_BAD_RESPONSE` | 运行实例起不来 / 返回异常 |
| 503 | `SERVICE_UNAVAILABLE` | 依赖不可用 → 报障 |
| 503 | `RUNTIME_UNAVAILABLE` | 运行实例当前不可达 |
| 504 | `RUNTIME_TIMEOUT` | 运行实例超时 |
| 504 | `RESOURCE_OPS_TIMEOUT` | 资源操作超时（会话文件的 PDF 转换是典型） |
| 400 | `path_invalid` / `bucket_invalid` / `prefix_invalid` / `type_invalid` | 对象存储挂载参数不合法（**这四个刻意是小写蛇形**） |

上游模型供应商报错时，平台会把它重整成同一个信封转发，并**尽量保留上游原文**
（`context_length_exceeded` 这类通常能看到）。映射关系：
409→`SESSION_BUSY`、400/422→`INVALID_REQUEST`、401→`INVALID_CREDENTIALS`、403→权限类、
404→`RESOURCE_NOT_FOUND`、429→`TOO_MANY_REQUESTS`、503→`SERVICE_UNAVAILABLE`、504→`RUNTIME_TIMEOUT`。

---

## 3. 按 message 原文速查（最实用的一张）

### 凭据

| message 原文 | 状态码 | 意思 / 动作 |
|---|---|---|
| `Missing Authorization header (Basic AK/SK or Bearer nacp_*)` | 401 | 压根没带 |
| `Invalid AK/SK credentials` | 401 | AK/SK 错 |
| `project not found or deleted` | **401** | 项目 id 错或项目被删（**是 401 不是 404**） |
| `Missing X-Project-Id header (required when using user credentials)` | **400** | 用 PAT 打对话面但没带项目头（**是 400 不是 401**） |
| `X-Project-Id must be a valid UUID` | 400 | 项目头格式不对 |
| `PAT invalid or expired` | 401 | 令牌过期或写错 |
| `embed token expired` | 401 | 嵌入场景短期令牌过期 |
| `non-PAT Bearer not accepted; …` | 401 | 拿别的 Bearer 打了 |
| `cookie auth on /agent-api/* is not yet enabled in this release; …` | 401 | 拿浏览器 cookie 打了对话面 |
| `AK/SK credentials are valid only on the data plane (/agent-api/*)…` | **403** | AK/SK 打了管理面，**换 PAT** |

### 版本与路由

| message 原文 | 状态码 | 意思 / 动作 |
|---|---|---|
| `Version <id> is not active` | 403 | **先查版本状态是不是 `failed`**，多半是部署失败 |
| `Version <id> is a standalone version (not bound to an environment) and cannot be routed. Deploy it to an environment instead.` | 403 | 游离版本，部署到环境即可 |
| `Version with tag '<tag>' not found in project <pid>` | 404 | tag 写错，或**把环境名当 tag 传了** |
| `Multiple agents registered, 'agent' parameter required` | 400 | 制品声明了 ≥2 个 agent，每次请求都必须带 `agent` 字段 |
| `Operating on environment '<name>' requires explicit confirmation. Set "confirm": true in request body.` | 400 | 受保护环境，见 `SKILL.md` §2.4 |
| `environment <id> already has deploy operation <op-id> in progress` | 409 | 同一环境并发部署，串行化流水线；约 15 分钟后自动失效 |
| `Cannot delete active version <vid>. Deactivate it first with …` | 400 | 先停用 |
| `Cannot delete version <vid> with running instances. Stop them first …` | 409 | 先停实例 |
| `Cannot delete environment '<name>' while it has an active release. Deactivate the current deployment first.` | 409 | 先下线部署 |
| `Cannot delete project: N version(s) still active: [tag1, tag2]. Deactivate them first via …` | 409 | 消息直接告诉你要停哪几个 |
| `Only environments with TTL can be extended` | 409 | 对持久环境调了续期 |
| `ttl_seconds required: environment has no stored ttl_seconds to fall back to` | 400 | 续期时必须显式给 `--ttl` |

### 制品上传

| message 原文（都带前缀 `Artifact validation failed: `） | 意思 |
|---|---|
| `Agent Artifact exceeds the 100MB compressed archive size limit. Compressed archive size: <N> bytes; limit: 104857600 bytes.` | 包太大（413）。⚠️ 文案里的 "compressed" 是措辞遗留，`nac deploy` 打的是**未压缩** tar |
| `nexau.json missing or invalid 'agents' field (expected non-empty object)` | 清单写法不对 |
| `agent yaml files declared in nexau.json not found or empty in artifact: - '<path>' (declared as agent '<key>')` | **最常撞的一条**：路径写错 / 文件被 `excluded` 排掉 / 大小写不符 / 文件是空的 |
| `agent name contains a character that breaks A2A URL routing: '<c>'. Avoid '/', '\', '%', '?', '#' and control characters (letters, digits, spaces, Chinese, '-', '_', '.' are allowed)` | agent 名 / 环境名非法。**中文、空格、`-`/`_`/`.` 是允许的** |
| `absolute paths are not allowed` / `parent traversal is not allowed` / `backslash paths are not allowed` / `Windows drive prefixes are not allowed` | 归档内路径不合法 |
| `unsupported tar entry '<path>': only regular files and directories are allowed` | 包里有符号链接 / 设备 / fifo。⚠️ 用图形界面压缩最容易撞 |
| `Artifact already uploaded for version <vid>` | 409。同一个版本只能传一次制品（`nac deploy` 每次新建版本，正常不会撞；手写 API 会） |
| `Artifact body cannot be empty` | 400 |
| `Found nested nexau.json at '<path>'. …` | **这条不是校验失败，是 `nac deploy` 本地直接拒绝打包**：删掉那个文件，或把它父目录加进 `excluded` |

### 运行期

| message 原文 | 状态码 | 意思 / 动作 |
|---|---|---|
| `runtime pod at capacity, please retry shortly` | 429 | 容量拒绝，读 `Retry-After` |
| `Failed to start Agent Runtime` / `Agent Runtime failed to start` | 502 | ⚠️ **刻意压平、不含根因**。唯一有效的下一步是 `?previous=true` 崩溃日志 |
| `Runtime not started yet for environment '<env>'` | 503 | 暂态，先发一轮对话唤醒 |
| `No running pods found for version <vid>` | 404 | 该版本没有活着的实例 |
| `Environment '<env>' has no active release` | 404 | ⚠️ **重试无用，得去部署** |
| `after and before are mutually exclusive` | 400 | `/actions` 的两个游标不能同时传 |
| `Observations in trace are too large` | 413 | 单个 trace 太大打不开；导出会 `truncated` |
| `Langfuse not configured` | **403** | ⚠️ **不是权限问题**，是这个项目没配 trace 存储，找管理员开 |
| `sandbox_at_capacity (<reason>), retry later` | 503 | 开流前的沙箱容量拒绝，稍后重试 |
| `multipart upload exceeds <N> bytes` | 413 | 会话文件上传超限 |
| `Environment variable key can only contain letters, numbers, and underscores` | 400 | 变量 key 非法 |
| `'<KEY>' is managed by the platform (Langfuse sidecar credentials) and cannot be set via env_vars` | 400 | `LANGFUSE_*` 是保留前缀 |
| `model_id is not in the project's visible model set` | 400 | 模型不在本项目可见集合里，用 `nac llm list-available` 查 |

### SSE 流里的错误帧（不是 HTTP 错误）

| payload | 意思 / 动作 |
|---|---|
| `{"type":"LOCK_CONFLICT","message":"…"}` | 同一 session 上已有一轮 run 没结束，你又发起了新的一轮。⚠️ 与订阅 `/events` 无关，只读订阅不抢这把锁 |
| `{"type":"TRANSPORT_ERROR","reason":"sandbox_at_capacity","retry_after":5,"message":"sandbox capacity unavailable, retry later"}` | **容量问题，按 `retry_after` 秒重试即可，不是你的代码错** |
| `{"type":"TRANSPORT_ERROR","message":"Error in agent execution: <html>502 Bad Gateway … nginx"}` | **上游模型链路抖动，改代码没用 → 报障** |
| `{"type":"RUN_ERROR","run_id":"…","message":"…"}` | 模型层 / 执行层失败 |
| `{"type":"RUN_STOPPED", …}` | 你调了 `POST /agent-api/stop`。**这是终态帧，解析器必须认它** |
| `{"type":"CONTENT_BLOCKED", …}` | 内容安全中间件命中 |

### CLI 自己的报错

| 原文 | 意思 |
|---|---|
| `Deployment failed for version <vid>: status=failed, message=<…>` | 部署终态失败，紧随其后会自动打印最近 10 分钟的部署日志 |
| `Deployment timed out after 10m waiting for version <vid> (last status: deploying)` | 等待超时（`--timeout` 可调）；**超时 ≠ 失败**，去 `nac versions list --json` 看最终状态 |
| `invalid --last value: "xxx" (try 1h, 30m, 7d)` | `nac traces --last` 格式错（**这个 flag 是真生效的**） |
| `⚠ truncated at <N> observations (hit export limit)` | trace 导出撞到 5 万 span 上限 |
| `⚠ upstream error after <N> observations: <err>` | ⚠️ **拉了一半，但退出码仍是成功** —— 脚本里只看退出码会误判 |
