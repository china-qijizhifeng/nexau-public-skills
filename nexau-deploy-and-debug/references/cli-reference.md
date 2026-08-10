# `nac` 命令行参考（部署与排障相关的全部动词）

> `nac --help` / `nac <cmd> --help` 永远是最权威的清单。本文补的是 `--help` 没说、
> 或者说错了的部分，以及每条命令**真实的输出形状**（你该看哪一行）。

## 0. 全局

```bash
nac [全局 flag] <command> [子命令] [参数]
```

| 全局 flag | 说明 |
|---|---|
| `--json` | 结构化输出。**排障时基本都要加**——很多命令的表格模式会漏字段（见 `status`） |
| `--compact` | 极简输出 |
| `--base-url <url>` | 覆盖平台地址（默认从当前目录 `nac.json` 或 `~/.nac/config.toml` 取） |
| `--project-id <id>` | 覆盖项目 id（默认从 `nac.json` 取） |
| `--token <t>` | 覆盖凭据。**同时接受 PAT（`nacp_…`）和 `ak:sk`** |
| `--insecure` | 接受自签证书。仅用于测试环境 |

**当前目录绑定**：`nac init` 会在当前目录生成 `nac.json`，之后这个目录下的命令自动解析
`--project-id` 和 `--base-url`，不用每次传。

**顶层命令（24 个）**：
`auth` `projects` `versions` `environments` `sessions` `keys` `vars` `llm` `tokens` `channels`
`api` `completions` `status` `clean` `dev` `smoke` `test` `deploy` `init` `logs` `traces` `trace`
`chat` `bench`

⚠️ **不存在的命令**（照直觉猜会出事）：
`nac promote`（回滚用 `nac deploy --promote`；**跨环境晋升这个能力不存在**，见 §deploy）、
`nac switch`、`nac rollback`、`nac remove`、
`nac chat status`（会被解析成「对一个叫 `status` 的环境发起对话」，**静默连到错的地方**）。

⚠️ **环境名是可选参数的五个命令 —— 省略时一律回落到字面字符串 `default`**：
`nac logs` / `nac smoke` / `nac test` / `nac bench` / `nac chat`。
那个环境多半不存在，于是你拿到一个跟真实环境毫无关系的 404。**永远显式写环境名。**

---

## 1. 认证

```bash
nac auth login                       # 交互粘贴 PAT
nac auth login --token nacp_xxx      # 非交互（CI）
nac auth whoami                      # 自检：当前身份 / 平台 / 项目
nac auth logout                      # 删掉本地凭据

nac tokens list
nac tokens create <name>             # 新建 PAT，值只显示一次
nac tokens delete <id>
```

`nac keys …` 管的是**项目 AK/SK**（对话面凭证），与 PAT 是两回事：

```bash
nac keys list / create / revoke / reset / secret
```

---

## 2. 部署

### `nac deploy <env>`

打包当前目录 → 建版本 → 上传 → 部署 → **等终态**。

| flag | 说明 |
|---|---|
| `--yes` | 跳过本地 y/N 提示（CI 友好）。⚠️ **它不是** 受保护环境要的那个 `confirm` |
| `--dry-run` | 预览。⚠️ **不会真打包**，所以看不到那行 `<N> bytes` |
| `--promote <tag>` | **不重新打包**，切到**本环境**的一个已有版本 tag（回滚用它）。⚠️ **不能跨环境** —— 要把预发的东西发到生产，只能把制品重新上传部署一次 |
| `--no-wait` | 提交完就返回，不等终态 |
| `--timeout <dur>` | 等待上限，默认 `10m`，接受 `20m` / `1h` 这类写法 |

**stderr 上的路标**（按顺序出现，用来判断卡在哪一步）：

```
Packing artifact...
  4823941 bytes                      ← 包大小，对照 100 MiB 上限用这个数
Creating version: v20260810-101530   ← tag 自动生成：v<UTC yyyymmdd>-<HHMMSS>
Uploading artifact...
Deploying v20260810-101530 to staging...
Waiting for version 3f2a…...
Deployment status: deploying         ← 状态每变一次打一行
Deployment status: success
```

- 每 5 秒轮询一次状态；每 15 秒穿插打印最近 30 秒的部署日志。
- 判成功的状态词：`success` / `succeeded` / `deployed` / `ready` / `active` / `completed` / `complete`。
  判失败：`failed` / `failure` / `error` / `timeout` / `timed_out` / `cancelled` / `canceled`。
  其余（`pending` / `deploying` / `building` / 空）算「还在跑」。
- 失败或超时会**自动打印最近 10 分钟的部署日志**再退出：
  ```
  Deployment failed for version <vid>: status=failed, message=<...>
  Deployment timed out after 10m waiting for version <vid> (last status: deploying)
  ```

**打包时固定排除**（任意层级，目录和文件都算）：`.git` `node_modules` `__pycache__` `.env`
`target` `dist` `.nac`；再加 `nexau.json` 里 `"excluded": ["fixtures/", …]` 声明的前缀。

⚠️ **符号链接既不入包也不报错**；⚠️ 打的是**未压缩 tar**（没有 gzip 帮你省空间）；
⚠️ 制品里任何子目录下再出现一个 `nexau.json` 会**直接报错拒绝打包**：
`Found nested nexau.json at '<path>'. …remove this file or add its parent directory to nexau.json excluded…`

### `nac dev`

内环开发：建一个 **1 小时 TTL 的临时泳道**，打包部署，Ctrl+C 自动拆掉。
不碰持久环境、不进部署历史。

```bash
nac dev              # 起泳道
nac dev --watch      # 改文件自动重发
nac dev --chat       # 就绪后直接进 REPL
```

### `nac clean`

清掉超期或被崩溃的 `nac dev` 遗留下来的临时环境。

```bash
nac clean --dry-run          # 先看会删什么（当前项目）
nac clean
nac clean --all --dry-run    # 扫所有你有权限的项目
```

---

## 3. 版本

```bash
nac versions list [<pid>] --json          # pid 是可选位置参数，省略则取 nac.json 里的
#   表格列：id / tag / artifact(✓ 或 —) / created_at
#   --json 里才有 status：pending | deploying | active | failed | superseded
nac versions get <version_id>
nac versions create [<pid>] --tag v1.0 [--environment staging]
#   ⚠️ 不给 --environment 就是建「游离版本」，它即使 active 也不能被路由
#      （403 VERSION_NOT_ROUTABLE），而且部分平台会直接 400 拒绝这种建法
nac versions deploy <version_id> <env>          # 部署一个已存在的版本（不打包）
nac versions activate <version_id>
nac versions deactivate <version_id> [--confirm]   # 版本已绑到环境时必须加 --confirm
nac versions redeploy <version_id>              # 无损重启当前版本（不换版本、不重打包）
nac versions scaling <version_id>               # 查副本上下限
nac versions scaling <version_id> --min 1 --max 5
nac versions scale <version_id> <replicas>      # 直接拨到 N 个副本
nac versions logs <version_id>                  # 版本级启动日志
```

⚠️ `nac versions logs` **不接受任何参数** ⇒ 恒为「最后 200 行、当前活着的容器」。
想看**崩溃前一次**的日志只能走逃生舱：

```bash
nac api GET "/api/projects/$PID/versions/$VID/logs?previous=true"
```

⚠️ 删版本是**软删**，制品对象不清理（多个环境可能共享同一份）。

---

## 4. 环境

```bash
nac environments list [<pid>] --json      # --json 里看 expires_at 判断是不是临时环境
nac environments get <env-name>           # 用名字，不是 uuid
nac environments create [<pid>] --name lab [--ttl 1h] # 带 --ttl = 临时环境，范围 60s ~ 7d
nac environments releases <env-name>      # 这个环境的发布历史
nac environments extend <env-name> [--ttl 2h]         # 只对临时环境有效；不带 --ttl 用原 TTL
nac environments delete <env-name>
```

- **持久环境调 `extend` 会 409** `Only environments with TTL can be extended`。
- 不传 `--ttl` 且环境没存过原始 TTL → 400 `ttl_seconds required: environment has no stored ttl_seconds to fall back to`。
- 环境名的合法字符与 agent 名同一套规则：**中文、空格、`-`、`_`、`.` 都允许**；
  不允许 `/` `\` `%` `?` `#` 和控制字符。

### `nac status`

```
Environment   Type         Expires At            Created
staging       persistent   —                     2026-07-01T…
lab-9f2       ephemeral    2026-08-10T12:00:00Z  2026-08-10T11:00:00Z
```

⚠️ **表格模式看不到「这个环境现在指向哪个版本」**。必须 `nac status --json` 读 `current_release_id`。

---

## 5. 日志

```bash
nac logs <env>                                   # ⚠️ 环境名一定要写
nac logs <env> --json | jq -r '.response.logs'   # 展开成人类可读的多行
```

**返回体形状**（非 `--json` 时直接打印这段原始 JSON）：

```json
{"environment_name":"production","version_id":"3f2a…","container":"agent-runtime",
 "logs":"{\"timestamp\": …}\n{…}"}
```

⚠️ `logs` 是**一整个字符串、换行是转义的** ⇒ 不 `jq -r` 展开根本没法看。

**日志行本身**：每行一个 JSON，固定六个字段
`timestamp` / `logger` / `level` / `trace_id` / `span_id` / `message`（`level` 默认 `INFO`）。
⚠️ 没有活跃请求上下文的行，`trace_id` 是 **32 个 0** —— 正常，不是 bug。

### ⚠️⚠️ 三个静默失效的 flag

`--last` / `--level` / `--grep` **服务端不认识，被静默丢弃**，不报错不警告，
返回的仍是未过滤的最后 200 行。（`--help` 里那句 "Filters are combined server-side" 已过时。）

**自证**：`nac logs <env> --level error` 与 `nac logs <env>` 输出**逐字相同**。

**替代做法**：

```bash
# 展开后本地 grep
nac logs production --json | jq -r '.response.logs' | grep -i "your keyword"

# 服务端真正生效的参数，走逃生舱
nac api GET "/api/projects/$PID/environments/production/logs?tail=2000"
nac api GET "/api/projects/$PID/environments/production/logs?trace_id=$TID"
nac api GET "/api/projects/$PID/versions/$VID/logs?previous=true"
```

### 服务端真正认的 query 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `tail` | `200` | 返回最后 N 行 |
| `container` | `agent-runtime` | **保持默认**。平台没有任何端点能列出有哪些容器名，换值只能靠猜 |
| `previous` | `false` | 取**已崩溃**容器的上一次日志。排查反复重启唯一有效的开关 |
| `follow` | `false` | `true` → 改成 SSE 逐行流式（看部署过程用） |
| `trace_id` | — | 只返回包含该字符串的行；**给了它就不受 `tail` 限制**。⚠️ **只有环境级接口有** |

### 两个日志源的分岔（选错会看错东西）

| | `nac logs <env>` | `nac versions logs <vid>` |
|---|---|---|
| 怎么定位 | 环境 → 当前生效版本 | **直接按版本 id 精准定位** |
| 滚动发布期间 | 可能读到新旧混合 | 只读该版本 |
| 健康检查噪音 | **过滤掉** | **不过滤** |
| `trace_id` 过滤 | 支持 | 不支持 |
| 主用途 | **运行期排障** | **部署中 / 部署失败后看启动与崩溃** |
| 取不到时 | `503 Runtime not started yet for environment '<env>'` | `404 No running pods found for version <id>` |

⚠️ 还有一个长得像但根因完全不同的：环境级 `404 Environment '<env>' has no active release`
——**这个重试一万次也没用**，得去部署。而 503 那条是暂态，重试或先发一轮对话唤醒即可。

> 术语：这些文案里的 **pod** 就是「一个运行实例」。`No running pods found` = 没有活着的运行实例；
> `runtime pod at capacity` = 运行实例满了。

---

## 6. Trace

```bash
nac traces --last 1h [--session <sid>] [--limit 50]
#   表格 5 列：ID / Name / Session / Timestamp / Latency(s)
nac trace <trace_id>                       # 完整 span 树 JSON（原样返回）
nac trace <trace_id> --export -o t.json    # 聚合导出 {trace, observations, summary}
```

- `--last` 接受 `1h` / `30m` / `7d` / `"1h 30m"`；写错会**明确报错**
  `invalid --last value: "xxx" (try 1h, 30m, 7d)`（**这个 flag 是真生效的**，别和 `nac logs` 的混了）。
- `--export` 的 `summary` 三个字段：`totalObservations` / `truncated`（撞到 5 万 span 上限）/ `error`。
- stderr 三种提示：`Exported <N> observations` / `⚠ truncated at <N> observations (hit export limit)` /
  `⚠ upstream error after <N> observations: <err>`。
  ⚠️⚠️ **最后一种情况下退出码仍是成功** —— 脚本里只看退出码会把「拉了一半」当成「拉完了」。

**从哪拿 trace id**：响应头 `server-timing` 里 `00-` 后面那 32 位；或 `/runs` / `/actions` 里的
`traceId`；或 429 响应的 `x-nac-capacity-trace-id`。三者是同一个东西。

---

## 7. 验证与压测

### `nac smoke <env>` —— 唯一可信的「部署到底能不能用」

```bash
nac smoke staging
nac --token "$AK:$SK" smoke prod -m 'health-check' --timeout 10 --json
```

```
Smoke test: <project_id> (staging)
  Status: ✓ passed
  Latency: 3.4s
```

`--json`：`{"status":"passed|failed|timeout|error","http_status":200,"latency_ms":3421,"session_id":"…","response":{…}}`

**退出码有区分度，可直接进 CI**：`0` 通过 / `1` 失败（含建 session 失败）/ **`2` 超时**。

其它 flag：`-m/--message`（默认 `ping`）、`--agent <name>`（多 agent 制品必须给）、`--timeout <秒>`、
`--var KEY=VALUE`（可重复）、`--sandbox-env KEY=VALUE`、`--template KEY=VALUE`、`--env-file <path>`。

⚠️ **环境名一定要写**（省略回落到字面 `default`，见 §0）。

### `nac test <env>` —— YAML 驱动的用例套件

读当前目录的 `nac-tests.yaml`：

```yaml
tests:
  - name: 'basic-response'
    message: 'hello'
    assert:
      status: completed          # completed | error
      latency_ms: '< 5000'       # <, <=, >, >=，或裸 N（等价于 <= N）
      content_contains: 'hi'
```

```bash
nac test staging
nac test staging --filter smoke --parallel 4
nac test staging --bail --json     # 首个失败即停，CI 快速卡口
```

任一用例失败退出码非零（即使 `--bail` 跳过了剩下的）。

### `nac bench <env>` —— 并发压测

`--concurrency` / `--duration <秒>` / `--requests <N>` / `-m <消息>` / `--agent <name>`。
⚠️ 同样**别省环境名**。压测时对比带不带请求头 `X-Max-Queue-Wait: 0`，可以直观看到排队与 429 的关系。

---

## 8. 变量与模型

```bash
nac vars list <pid> --json
nac vars set KEY=VALUE
nac vars delete KEY
nac vars sync --from .env          # 从本地 .env 灌进项目（因为 .env 本身不会被打包）

nac llm show
nac llm list-available <pid> --json    # 有哪些模型可用；full_name 就是 agent.yaml 里要填的值
```

- 变量有 **`runtime` / `sandbox` 两个作用域**，**显式传作用域**（不传按 runtime 处理且已标记废弃，
  响应会带 Deprecation 头）。
- key 只能字母/数字/下划线、≤255 字符；`LANGFUSE_*` 是平台保留前缀，写入被拒并给出明确提示。
- ⚠️ `nac llm set` 已退役，调用返回 **410** 并给出替代指引。

`nac llm list-available` 返回里对你有用的字段：

```json
{"models":[{"full_name":"provider/model","supports_multimodal":true,"origin":"platform|custom"}],
 "default":{"provider_name":"…","model_name":"…"}}
```

- `full_name` = `agent.yaml` 里 `llm_config.model` 要填的值。
- `default` 是**平台默认**，不等于「实际生效模型」——项目自己设了默认时会分叉。
- 填了不在这个集合里的模型 → 400 `model_id is not in the project's visible model set`。

---

## 9. `nac api` —— 逃生舱

```bash
nac api GET  "/api/projects/$PID/environments"
nac api PUT  "/api/projects/$PID/versions/$VID/deploy" --body '{"environment":"production","confirm":true}'
nac api GET  "/api/projects/$PID/versions/$VID/logs?previous=true"
nac api GET  "/api/projects/$PID/environments/prod/logs?tail=2000&trace_id=$TID"
```

⚠️ 它直接打管理面 `/api/*`，而管理面是 Web 控制台在用的后台接口，**不对第三方保持稳定、
不属于对外契约**。**排障时手敲没问题；不要把它写进生产脚本或长期自动化。**
能用 `nac logs` / `nac versions logs` 顶掉的场景，优先用后者。

已知**必须**走逃生舱的三件事：
1. 受保护环境的部署（`confirm: true`）。
2. 崩溃前一次的日志（`?previous=true`）。
3. 按 trace 过滤日志 / 拉超过 200 行（`?trace_id=` / `?tail=`）。

---

## 10. 会话与对话

```bash
nac sessions list                 # 列项目的会话
nac chat <env>                    # 交互 REPL
nac chat <env> -m "一句话"        # 单轮
nac chat <env> --session <sid>    # 续上已有会话
nac chat <env> --distinct-id <id> # 续别处（如 Web UI）建的 session 时，必须给建它时用的那个 id
nac chat <env> --agent <name>     # 多 agent 制品必须给
nac chat <env> --var K=V --sandbox-env K=V --template K=V --env-file .env.local
```

三种变量通道的区别（`--var` 运行时变量 / `--sandbox-env` 注入沙箱环境变量 / `--template`
系统提示词的模板值）属于制品侧语义，细节见 `nexau-artifact-builder`。
