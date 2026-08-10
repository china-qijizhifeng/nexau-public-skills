# 症状速查（按「你会怎么描述这个问题」索引）

> 用法：`Ctrl+F` 搜你嘴里会说的那句话。每条固定四段：**取证命令 → 判据 → 修法 → 什么时候该报障**。
> 排查次序（先分类、先存锚点）在 `SKILL.md` §3；证据面细节在 `evidence-sources.md`。

---

## 部署相关

### 「部署完了，但行为还是老的」

**取证**
```bash
# 发一轮对话拿到 $SID 后
curl -s "$BASE/agent-api/sessions/$SID/runs" -u "$AK:$SK" | jq '.runs[0].versionId'
nac versions list --json | jq '.[] | {id, tag, status}'
```

**判据**：`versionId` 是不是你刚部署的那个。

- 不是 → 路由没切过去。三种可能：① 环境指针还指着老版本（`nac status --json` 看
  `current_release_id`）；② **请求体里残留了 `deployment_id` / `version_id`**，它们的优先级
  **高于** `environment`，会**静默压过**你以为的路由；③ 根本没传 `environment`，回落到了 `production`。
- 是 → 代码确实上去了，问题在别处（多半是下面「setup 静默失败」或「本地好好的」那条）。

**修法**：路由优先级从高到低是 `deployment_id` / `version_id` > `version_tag` > `environment` >
默认 `production`。**按环境路由就只传 `environment`，按版本路由就只传 `version_tag`，别同时传。**

⚠️ **别用界面上的「部署成功」当判据。** 部署是异步的，命令返回只代表任务已提交。

---

### 「部署显示成功，但第一次对话就报缺依赖 / `ModuleNotFoundError`」

**取证**
```bash
nac logs <env> --json | jq -r '.response.logs' | grep 'setup command failed'
```

**判据**：看到 `[runtime] … WARNING: setup command failed: <你的命令>` 就确诊。

**根因**：清单 `nexau.json` 的 `setup` 是 **best-effort** 的 —— 某条命令失败只写一行 WARNING，
**部署照常显示成功**。「部署绿了」和「依赖装好了」是解耦的两件事。

**修法**：先在本地用同样的命令验证能装上；私有源多半装不上（见「连不上我们自己的服务」那条）。

⚠️ **相邻形态**：`setup` 里装大包 / 下模型**耗时超过约两分钟**，实例会被判为启动失败并反复重启，
表现不是「慢一点」而是「起不来」。**重依赖请随包带 wheel，别在 `setup` 里现装。**

---

### 「本地好好的，传上去就报错 / 文件不见了」

**根因**：打包时被静默丢掉了东西。

- **符号链接不会进包**（既不打包也不报错）—— 靠软链组织的 skills / 共享提示词目录会凭空消失。
- **`.env` 在固定排除名单里**（还有 `.git`、`node_modules`、`__pycache__`、`target`、`dist`、`.nac`）——
  本地靠它调通的环境变量部署后一个都没有。

**取证 —— 分两种，别用错**：

| 找什么 | 怎么查 |
|---|---|
| **skills** | 它们会被上传进沙箱：在 Playground 里让 agent 跑 `ls -la /home/user/.skills/`，少了哪个一目了然 |
| **其它制品文件**（`agent.yaml` / `systemprompt.md` / `custom_tools/`） | 它们只存在于**运行实例**里，**沙箱的 shell 看不到**。判据走日志：`nac logs <env> --json \| jq -r '.response.logs'`，找 `Agent config not found` / `ModuleNotFoundError` 这类启动期报错 |

⚠️ **别在沙箱里 `ls` 找制品文件然后误判成「文件丢了」。**
⚠️ **别用本地手搓的 `tar -tf` 做对照** —— `nac deploy` 的打包规则跟你手敲的 `tar` 不一样，对不上不说明问题。

**修法**：把软链换成真实文件；密钥走 `nac vars set` / 控制台运行配置，不要放进包。

---

### 「返回 403，说版本没激活，可我明明激活了」

**反直觉但很常见：多半是部署失败了，不是你忘了激活。**

**取证**
```bash
nac versions list --json | jq '.[] | select(.id=="<vid>") | .status'
nac api GET "/api/projects/$PID/versions/$VID/logs?previous=true"
```

**判据**：
- 版本状态是 `failed` → 就别在激活开关上折腾了，是部署失败。
  **错误码描述的是结果，不是原因。**
- 崩溃日志里是**你自己代码的报错栈**（缺模块、导入失败、配置解析失败）→ 你能自己修。
- 崩溃日志**为空或全是启动脚本输出** → 不是你的问题，报障。

⚠️ 顺带：`VERSION_NOT_ACTIVE` 这个 `code` 还会顶在**其它 403** 上（比如「这个 session 不属于你的项目」
「你这个账号对该项目没权限」）。**别只看码，看 `message` 原文。**

---

### 「403 说这个版本不能被路由」

**message 原文自带解法**：
```
Version <id> is a standalone version (not bound to an environment) and cannot be routed.
Deploy it to an environment instead.
```

**根因**：直接创建但从没部署到任何环境的「游离版本」，即使它是 active 也不能被路由。

**修法**：`nac versions deploy <vid> <env>` 把它部署到一个环境；或请求里改用 `environment` 维度。

---

### 「`nac deploy` 报 400，说要 confirm，但命令行没有这个开关」

```
Operating on environment '<name>' requires explicit confirmation. Set "confirm": true in request body.
```

见 `SKILL.md` §2.4。要点三条：`--yes` 不是它；唯一绕法是
`nac api PUT "/api/projects/$PID/versions/$VID/deploy" --body '{"environment":"…","confirm":true}'`；
**保护跟环境名无关**，是不是受保护要查 `requires_confirmation`，别靠名字猜。

---

### 「CI 里两条流水线同时部署，第二条报 409」

```
environment <id> already has deploy operation <op-id> in progress
```

**修法**：串行化你的部署流水线，等前一个结束再发。
若前一个部署的执行方异常中断，该占用会在**约 15 分钟**后自动失效。
**卡住超过 15 分钟仍无法部署 → 报障。**

---

### 「第一次接入：会话建成功了，一发对话就 404 / 403」

**根因**：环境上还没有一个成功跑起来的版本。
⚠️ **创建会话这一步不校验版本、总会成功** —— 所以第一步给了你「一切正常」的错觉，
错误出现在下一步，看起来像「对话接口坏了」。

**取证（发对话之前先跑这两条）**
```bash
nac versions list --json | jq '.[] | {id, tag, status}'   # 有没有 status == "active" 的
nac status --json | jq '.[] | {name, current_release_id}' # 目标环境的指向是不是空
```

**判据**：
- 没有 `active` 版本 → 还没部署成功，去 `nac deploy <env>`。
- 有 `active` 版本但目标环境 `current_release_id` 为空 → 版本没绑到**这个**环境
  （典型：部到了 `staging`，却在打 `production`；或建了游离版本，见上面那条）。
- 对话侧的表现是 404 `VERSION_TAG_NOT_FOUND`（按 tag/环境解析不到）或
  403 `VERSION_NOT_ACTIVE`（解析到了但不可用）—— **两个码描述的都是结果，不是原因**。

⚠️ **`nac status` 的表格输出看不到指向**（只有 Environment / Type / Expires At / Created 四列），
必须 `--json` 读 `current_release_id`。这一条本身就骗过不少人。

---

### 「代码一个字没改，突然全部 403 / 404 了」

**第一嫌疑：临时环境到期被自动回收了。**

**取证**
```bash
nac environments list --json | jq '.[] | {name, expires_at}'
nac status              # Type 列是不是 ephemeral、Expires At 是不是已经过去
```

**根因**：临时环境到点自动停服务 + 下线 + 软删，**没有确认、没有宽限期**。

**修法**：到期前 `nac environments extend <env> --ttl 2h` 续期
（对持久环境调它会 409）。**生产用途不要用临时环境。**

---

## 运行时相关

### 「我的 agent 没有回复 / 回复是空的」

**取证顺序**
1. 先看 HTTP 状态码：4xx/5xx 直接对 `message` 原文（查 `error-codes.md`）。
2. 200 但没内容 → `GET .../runs` 看 `status` 和 `agentName`。
3. `nac logs <env> --json | jq -r '.response.logs' | grep 'Agent config not found'`

**判据**：日志里有 `Agent config not found` 的 WARNING = 清单里声明的 agent 配置**路径写错了**。
平台不会因此报错，只会跳过那个 agent，**然后在对话时才炸**。

---

### 「第一次调用特别慢，后面就快了」

**取证**：`curl -i` 看有没有 **`x-nac-cold-start: true`**。

**判据**：有这个头 = 这次请求把运行实例唤醒了，**慢的是冷启动，不是你的 agent**。

**修法**：把客户端首字节超时放宽到 **3 分钟以上**；对延迟敏感的场景别把最小副本设成 0
（控制台 负载均衡 tab，或 `nac versions scaling <vid> --min 1`）。

---

### 「超时了」

**先分清流式还是非流式，两者行为完全不同**：

| | 整体超时 | 超时后返回 |
|---|---|---|
| `"stream": true` | **没有** | — |
| `"stream": false` | **约 300 秒硬超时**（部署级默认，可能因部署而异） | **500，不是 504** |

⚠️ **这个 500 不代表你的 agent 崩了**，很可能只是非流式模式下超预算了。

**判据（30 秒可证伪）**：同一个请求改成 `"stream": true` 再打一次，能跑完 → 就是这条。

**修法**：长任务一律用流式。

---

### 「返回 429」

**取证**：`curl -i` 看响应头 `Retry-After`（按它退避）和 `x-nac-capacity-trace-id`（存下来报障用）。

message 原文 `runtime pod at capacity, please retry shortly`（这里的 "pod" = 一个运行实例）。

**判据**：**这是容量拒绝，不是你的 agent 出错**，这一轮没有被执行
（但会在会话记录里留下一条红色痕迹，控制台看得到，不是凭空消失）。

**修法**：
- 按 `Retry-After` 退避重试，**复用同一个 `session_id`**（上下文不会丢）。
- 想控制排队行为：请求头 **`X-Max-Queue-Wait: <秒>`**（`0` = 不等直接拿 429；超过上限会被夹到上限；
  写了非法值当没写）。429 之前平台默认会先排队约 30 秒、上限约 60 秒。
- 自己能调的是**你这个版本的副本上下限**（控制台 负载均衡 tab / `nac versions scaling`）。

**什么时候报障**：**并发并不高却持续 429** —— 平台总容量不是你能调的。

---

### 「偶尔失败，重试就好」

**先分清是哪一种**：

| 现象 | 含义 | 动作 |
|---|---|---|
| `409` / SSE `LOCK_CONFLICT` | 同一个 session 上已经有一轮在跑 | 见下条 |
| `429` | 容量拒绝，这一轮没被执行 | 见上条 |
| `TRANSPORT_ERROR` 带 `reason: "sandbox_at_capacity"` + `retry_after` | 沙箱容量，**按 `retry_after` 秒重试即可** | 频繁出现要报障 |
| `TRANSPORT_ERROR` 的 message 里裹着 HTML 或 `502 Bad Gateway` | **上游模型链路抖动，你改什么都没用** | **报障** |

**最重要的判据**：**偶发**基本是自己并发；**短时间内成片出现（几十上百次）几乎一定是上游故障** ——
这时要报障而不是继续重试。可以再坐实两下：换一个模型再试一轮（好了 = 特定模型的上游问题）；
隔几分钟重试（自行恢复 = 更加坐实）。

---

### 「`409 SESSION_BUSY` / 流里收到 `LOCK_CONFLICT`」

**根因（按可能性排序）**：
1. **自己并发了** —— 前端重复点、重试逻辑没等上一轮结束、多个页签共用一个 `session_id`。
3. **刚点过 stop 就立刻发下一条** —— 极少数情况下上一轮的锁需要最多约 30 秒自行释放。
4. **上游抖动导致上一轮迟迟不结束** —— 此时会是**成片**的 `LOCK_CONFLICT`。

**取证**：`GET /agent-api/sessions/{sid}/runs` 看有没有 run 还停在未完成状态。

**修法**：`POST /agent-api/stop` 显式终止（默认 `force: false`，**别传 `true`**）；
或换一个新 `session_id`（会丢上下文）。撞上第 3 种等约 30 秒即可。

⚠️ **`LOCK_CONFLICT` 只跟「同时跑两轮 run」有关，跟订阅无关。**
只读订阅 `/events` 不抢这把锁：同一个会话**可以被任意多个客户端同时订阅**
（复制一个页签、换台电脑打开同一个会话，两边都会正常流式），
也可以一边读 `/chat` 的响应体一边订阅 `/events` —— 前端本来就是这么做的。

---

### 「界面永远停在『生成中』/ 我的客户端不退出循环」

**判据**：数一下你的解析器认几个终态帧。**一共 5 个**：
`RUN_FINISHED` / `RUN_ERROR` / **`RUN_STOPPED`** / `LOCK_CONFLICT` / `TRANSPORT_ERROR`。

**最常漏的是 `RUN_STOPPED`** —— 它是你调 `POST /agent-api/stop` 时在原流里发出来的那一帧。

**相邻形态**：等「连接关闭」当结束判据 —— 结束标记是显式的 `data: [DONE]`，发完之后服务端
还要收尾，连接会再开着几秒。

---

### 「聊到一半无缘无故断线重连」

**取证**：`curl -N` 直接打 `/agent-api/chat`，在模型思考期间肉眼看流里有没有
`: heartbeat` / `: keep-alive` 这类**以 `:` 开头、没有 `data:` 前缀**的行。

**判据**：这是标准 SSE 的保活注释行，**必须忽略**。
用标准 SSE 客户端（浏览器 `EventSource`、`httpx-sse`、`aiohttp-sse-client`）**不会**踩；
**只有自己 `split('\n')` 手搓解析器的人**会把它当成损坏的 JSON 而断开。

**修法**：改你的解析器（忽略 `:` 开头的行 + 对未知 `type` 宽容）。不用报障。

---

### 「我用非流式触发，另一个进程订阅 `/events` 看进度，一条都收不到」

**判据**：**`"stream": false` 时全程不产生任何事件。** 这是架构约束，不是 bug。

**修法**：要实时就必须 `"stream": true`；只要事后回查，用 `/actions` 和 `/runs`
（它们读的是持久化的会话记录，不依赖事件旁路）。

---

### 「我指定了模型，但好像没生效」

**取证**：在流里找 **`MODEL_FALLBACK`** 事件（在 `RUN_STARTED` **之前**，只发一次）。

```json
{"type":"MODEL_FALLBACK","requested_model":"…","effective_model":"…","message":"…"}
```

**判据**：指定的模型不可用时，平台**不报错**，回落到 agent 默认模型继续跑。
**这个事件是唯一的线索**，忽略它就静默拿到了默认模型。

**修法**：`nac llm list-available <pid> --json` 看这个项目到底能用哪些模型，
`full_name` 就是 `agent.yaml` 里 `llm_config.model` 要填的值。填了集合外的模型会 400
`model_id is not in the project's visible model set`。

---

## 沙箱与出网

### 「我的自定义工具报文件不存在 / 读到的是空的，可 agent 明明刚生成了它」

**根因**：**自定义工具和 agent 的 shell 命令跑在两个不同的服务里，文件系统不共享。**

- **自定义工具**跑在**运行实例**进程里
- **agent 用 shell 跑的命令**在**沙箱**里 —— 沙箱是独立的隔离执行环境，运行实例把命令执行、
  文件读写这类（尤其是有风险的）操作交给它去做

⇒ agent 在沙箱里生成的 `/home/user/out/report.csv`，工具用裸 `open()` 打不开。

⚠️ **最阴的一点：它未必报「文件不存在」。** 运行实例容器里**也有**一个同名的 `/home/user`，
裸 `open()` 读写的是**那一个** —— 于是你可能读到空目录、或者写进去之后 agent 在沙箱里怎么也找不到，
**两边都不报错**。

**判据**：让 agent 在沙箱里 `ls -la <路径>` 确认文件确实在，而工具那边读不到 —— 就是这个原因，
不是文件没写成功。

**修法**：工具要访问沙箱文件必须拿沙箱句柄，走 `sandbox.read_file()` / `write_file()` /
`execute_shell()`，不能用裸 `open()`。⚠️ 句柄靠**具名形参**注入，`**kwargs` 接不到**且毫无报错**。
写法见 skill `nexau-artifact-builder` 的 `references/custom-tools.md`。

---

### 「agent 说它执行了代码，但结果不对 / 说文件里没有这个内容」

**根因**：**shell 工具的输出被截断了。** stdout + stderr 合计超过约 **1 万字符**时，
每一路各自只保留**开头 5000 + 结尾 5000 字符**，中间挖掉。让 agent 直接 `cat` 一个大文件，
它就丢了中段。

**判据（截断是有标记的，不是静默的）**：在 trace 里看那次工具调用的返回值，会看到

```
... [12,345 characters omitted] ...
(Full output: <目录>/stdout.txt)
```

看到这两行就确诊。

**修法**：① 让 agent 去 `read_file` 那个 `stdout.txt` 拿完整输出；
② 一开始就别 `cat`，改用 `grep` / `head` / 分段读。

⚠️ **相邻形态**：回复末尾出现 `[Note: Maximum iteration limit reached]` ——
撞到单轮步数上限被强制收尾了，**不是「想清楚了」**。这个上限（默认 100 轮）在 `agent.yaml` 里你自己能改。

---

### 「文件写进去了，下次对话就没了」

**根因**：沙箱闲置约 5 分钟自动暂停，恢复时**只有部分路径会被保留**。
常见的持久路径是 `/home/user`（也是默认工作目录）、`/tmp`、`/usr/local`、`/var/cache`、`/opt` ——
**具体清单取决于你所用的部署**。

⚠️ **系统包管理器的数据库不在持久清单里** ⇒ **在沙箱里 `apt-get install` 装的包恢复之后等于没装**；
而 `pip install --user` / `npm install -g` 落在持久路径里，**能活下来**。

**自查（一定要自己跑一遍）**：
```bash
echo hi > /home/user/x && echo hi > /var/log/x
# 让会话闲置 5 分钟以上，再回来
cat /home/user/x    # 应该还在
cat /var/log/x      # 多半没了
```

**修法**：需要跨轮存在的东西一律写 `/home/user`；系统级依赖随制品带，不要在沙箱里现装。

---

### 「调用外部 API 失败 / 连不上我们自己的服务」

**硬约束（不可关闭，无任何开关）**：沙箱与运行实例的出网**只允许公网单播 IPv4**。

- ❌ **所有私有网段一律不通**（`10.` / `172.16-31.` / `192.168.` / `127.` / `169.254.` 等）
- ❌ **IPv6 完全不支持**（IPv6 字面量、或只有 AAAA 记录的域名，都连不上）
- ❌ **DNS 重绑定防护**：域名解析结果里**只要有一个是禁止地址，整条连接直接拒**
  （不是「挑一个能用的」）⇒ 内网 DNS 把公网域名解析到内网 IP 的场景会整体失败

⇒ **连不上你自己的内网服务是设计如此，不是故障。**

**能不能上公网另说** —— 取决于部署方是否启用了出网白名单。**先自测再下结论**
（在 Playground 里让 agent 跑，正常结果是「第一条通、后两条失败」）：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://example.com   # 公网，应当通
curl -sS --max-time 5 http://10.0.0.5:8080                      # 私网，应当失败
curl -6 --max-time 5 https://ipv6.google.com                    # IPv6，应当失败
```

**启用了白名单时你能自助做什么**：项目设置 → **网络策略** tab
- 「当前生效策略」列出已批准的域名 + 端口；空时显示 `暂无生效策略`
- 「申请新策略」：域名/CIDR（一行一个）、端口（逗号分隔，**默认 443**）、申请理由（至少 10 个字）
- 状态流转：`待审批` / `已批准` / `已拒绝` / `已撤销` / `已归档`
- **必须由平台管理员审批，不能自助批准**
- 「撤销」已批准的策略会**立刻**断掉该权限
- ⚠️ **这一页只有项目 owner 能看**：不是 owner 会看到「仅项目 owner 可查看和管理网络策略。」——
  **那不是故障**，找 owner 代提或让 owner 把你加成 owner
- 平台侧没配 / 已停用防火墙时，这一页会明确显示对应提示（接口返回 503）
- ⚠️ 管理员改了平台默认策略可能覆盖你的白名单，界面会弹
  `您的网络白名单已被新的默认策略覆盖，如需细化请重新申请。`

**相邻形态**：`pip install` 拉**私有 PyPI**（通常在内网 IP）必然失败 ——
这就是为什么依赖推荐「wheel 随包走 + `--no-index --find-links`」。

---

## 凭据与可见性

### 「返回 401 / 403，但凭据我确认是对的」

先排掉 base64 编码问题：`ak:sk` 中间是**英文冒号**，`echo` 必须带 `-n`。
然后注意**两种凭据不通用**（见 `SKILL.md` §1），剩下的靠 `message` 原文区分：

| message 原文 | 状态码 | 意思 |
|---|---|---|
| `Missing Authorization header (Basic AK/SK or Bearer nacp_*)` | 401 | 压根没带 |
| `project not found or deleted` | **401** | 项目 id 错或项目被删（**注意是 401，不是 404**） |
| `Missing X-Project-Id header (required when using user credentials)` | **400** | 用 PAT 但没带项目头（**是 400 不是 401**，别在 401 分支里找它） |
| `X-Project-Id must be a valid UUID` | 400 | 项目头格式不对 |
| `PAT invalid or expired` | 401 | 令牌本身过期或写错 |
| `embed token expired` | 401 | 嵌入场景的短期令牌过期，重新换一个 |
| `non-PAT Bearer not accepted; use PAT (Authorization: Bearer nacp_*) or AK/SK (Basic) on /agent-api/*` | 401 | 拿别的 Bearer（比如自家 OIDC token）来打了 |
| `cookie auth on /agent-api/* is not yet enabled in this release; …` | 401 | 拿浏览器 cookie 打了对话面 |
| `AK/SK credentials are valid only on the data plane (/agent-api/*)…` | **403** | 拿 AK/SK 去打了管理面 `/api/*`，**换 PAT** |

---

### 「`404 session not found`，可这个 session 明明存在」

**两种成因，都不是「session 丢了」**：

1. **用错了项目的 AK/SK** —— 跨项目访问统一返回 404（有意不泄露 session 是否存在）。
2. **换了凭据类型** —— 项目 AK/SK 只校验「session 属于本项目」；
   **PAT 还会额外校验「发起人是我」**，比对的是建 session 时那次对话传的 `distinct_id`，
   而 PAT 持有者的身份通常和它不是一个值。

**判据（30 秒可证伪）**：同一个 `session_id` **换用项目 AK/SK** 再请求一次。
读得到 = 第 2 种；仍读不到 = 第 1 种。

---

### 「Trace 里的内容是 `🔒 [encrypted]` / 查 trace 报 403」

两条长得像权限问题、其实都不是的错误：

- **`🔒 [encrypted]`** = 项目开启了隐私域加密，**不是故障**。需要在 Playground 输入 passphrase 解锁。
  ⚠️ 口令**不被平台存储、也无法找回**。忘了之后 agent 照常运行、加密写入不受影响，
  但**永久失去「解锁查看 / 关闭隐私域 / 轮换口令」这些高敏操作**。
- **`403 Langfuse not configured`** = 这个项目没有配置 trace 存储（Langfuse 是平台用来存 trace 的组件），
  此时 `nac traces` / `nac trace` 全都用不了。**找平台管理员开通。**

---

### 「界面里能跑通，我自己调 API 就不行」

**取证**：用 Playground 里那个带代码图标、标着 **`API`** 的小按钮（下拉里有 cURL / Python / JavaScript），
把当前这次调用原样导出来 —— 里面含 AK/SK、路由字段和 `session_id`，**和你自己的请求逐字段对比**。

**对比时重点看三处**：

1. **路由字段**：`version_tag` 的优先级**高于** `environment`。两个都传不会报错，
   `environment` 会被**静默忽略** —— 于是你以为在打 staging，实际打的是那个 tag。
2. **把环境名当版本标签传**（`"version_tag": "production"`）→ 404 `VERSION_TAG_NOT_FOUND`。
3. ⚠️ **导出的脚本不含 `agent` 字段**。制品里声明了两个及以上 agent 时，界面能跑
   （Playground 自己补上了），照抄脚本会 400 `Multiple agents registered, 'agent' parameter required`
   —— 自己补一个 `"agent": "<你的 agent key>"` 就好。

---

### 「`nac logs` 返回 503 / `nac versions logs` 返回 404，服务是不是挂了」

| 报错 | 含义 | 动作 |
|---|---|---|
| `503 Runtime not started yet for environment '<env>'` | 当前没有活着的运行实例（缩到 0 了、或正在冷启动） | **暂态**。先发一轮对话把它唤醒再看日志 |
| `404 No running pods found for version <vid>` | 该版本当前没有活着的实例（已被取代 / 从没起来 / 已缩到 0） | 结合版本状态判断：`failed` → 查崩溃日志；`superseded` → 正常 |
| `404 Environment '<env>' has no active release` | **环境上根本没有激活的版本** | ⚠️ 和上面两条长得像但**根因完全不同**：**重试一万次也没用，得去部署** |

**这三个都不代表服务坏了。** 开了缩零后闲置回收属于正常行为。
