---
name: nac
version: 0.4.4
description: "North Agent Cloud CLI。管理 AI Agent 项目、部署版本、查看日志和 trace、运行测试、与 Agent 对话、配置环境变量和 LLM 模式、管理临时 lane。当用户提到 NAC、North Agent Cloud、agent 部署、agent 项目管理、nac 命令时使用。"
metadata:
  requires:
    bins: ["nac"]
  cliHelp: "nac --help"
---

# NAC CLI — North Agent Cloud

Platform operations CLI with three abstraction layers:
1. **Shortcuts** (`nac deploy`, `nac smoke`, `nac dev`) — multi-step workflows with best-practice defaults（`nac dev` 0.4.x 有坑，日常用 environments create + deploy，见「nac dev 实际行为」）
2. **Resource CRUD** (`nac projects list`) — one-to-one API mapping
3. **Raw API** (`nac api GET /api/...`) — escape hatch for any endpoint

## When to use

Trigger keywords: NAC, North Agent Cloud, agent 部署, agent 项目, nac 命令, 部署版本, 查看日志, trace, playground, 冒烟测试, 压测, 异步调用, 长任务, 后台任务, 轮询, run_id, events, 扳机 / trigger

- **项目管理**: 创建/部署/查看项目、版本、环境 → `nac projects`, `nac versions`, `nac environments`
- **临时 lane**: 带 TTL 自动清理的环境 → `nac environments create --ttl`, `nac environments extend`
- **环境变量**: 项目级 env vars 管理 → `nac vars list/set/delete/sync`
- **LLM 配置**: 模型选择写在 agent.yaml 的 `llm_config.model`（`provider/model_name` 全键，可选，缺省用项目默认模型）；`nac llm show/list-available` 查看项目默认模型与可用模型（`set` 是已退役的项目级切换，新平台返回 410）
- **排障**: 查看日志、trace、Agent 状态 → `nac logs`, `nac traces`, `nac status`
- **开发调试**: 改完重新部署、Agent 对话（含 runtime 变量注入）→ `nac environments create` + `nac deploy`（`nac dev` 0.4.x 有坑，见「nac dev 实际行为」）, `nac chat --var/--vars-file`
- **测试**: 冒烟测试、集成测试、压测 → `nac smoke`, `nac test`, `nac bench`
- **IM 通道**: 绑定/管理飞书 bot → `nac channels`
- **异步 / 长任务**: 不想挂住 HTTP、要把一次 run 当后台任务跟踪 → 见
  [Async / long-running](#async--long-running-work--chat-is-the-trigger-events-is-the-channel).
  **这是 NAC 支持、但默认参数会把你带进死路的一条路径**，动手前先读那一节。

## 先装、先配地址、再用（0.4.x 实测，按顺序做）

**1. 安装**（latest 当前 0.4.4）

```bash
# macOS / Linux —— 必须 | bash，不能 | sh
curl -fsSL https://download.xiaobei.top/nac-cli/install.sh | bash
# Windows (PowerShell)，装到 %LOCALAPPDATA%\Programs\nac 并自动加 PATH，不需要管理员
irm https://download.xiaobei.top/nac-cli/install.ps1 | iex
# 指定版本 / 目录（变量要写在管道后面、bash 前面，写在 curl 前面传不进安装脚本）：
curl -fsSL https://download.xiaobei.top/nac-cli/install.sh | NAC_VERSION=0.4.3 NAC_INSTALL_DIR=$HOME/bin bash
nac --version
```

> ⚠️ 脚本开头有 `set -o pipefail`，Ubuntu/Debian 的 `sh` 是 dash，会报 `Illegal option -o pipefail`、装不上。
> 脚本自己的注释和装完提示里写的是 `| sh`，那是错的，以这里为准。

**2. 先配地址（最容易踩）**：零配置时 `nac` 默认连**官方正式环境（https://nac.xiaobei.top）**。你的令牌如果是别的环境的，会 401；
如果恰好是正式环境的令牌，命令会**直接打到生产**。所以先决定连哪，再动手。下文 `nac-alpha.xiaobei.top` 只是示例，换成你自己的部署地址。

| 写法（0.4.x 实测） | 是否生效 |
|---|---|
| 每条命令加 `--base-url https://nac-alpha.xiaobei.top`（或 `--north-env dev`） | 生效 |
| `export NAC_BASE_URL=https://nac-alpha.xiaobei.top`（**推荐写进 `~/.bashrc` / `~/.zshrc`**） | 生效 |
| `NORTH_ENV=dev`（dev = alpha，`beta`、`prod` 同理） | 生效 |
| 在项目的 `nac.json` 里**手写** `"base_url": "..."` | 生效，但只在该目录及子目录里 |
| `nac auth login --pat ... --base-url ...` | **不记地址**，只存令牌，下一条命令不带地址照样连正式环境 |
| `nac init --base-url ...` | **不会**把地址写进 `nac.json`（只写 project_id），要自己编辑 |
| `~/.nac/config.toml`（试过 `base_url=`、`[default] base_url=`、`north_env=` 等 5 种写法） | **全都不生效**（源码里根本不读它），别花时间在上面 |

地址优先级（0.4.4 源码）：`--base-url` / `NAC_BASE_URL` > `NORTH_ENV` > 项目 `nac.json` 的 `base_url` > 默认正式环境。
注意：写进 `~/.bashrc` 的 `NAC_BASE_URL` 会**盖掉**项目 `nac.json` 里的 `base_url`，两处写的不一致时以环境变量为准。

**3. 两把钥匙**（用错的报错见下一节）：

| | 访问令牌 `nacp_...` | API 密钥 `ak_xxx:sk_xxx` |
|---|---|---|
| 代表 | 你本人 | 一个项目 |
| 用在 | 管理命令：projects / versions / environments / deploy / dev / keys / logs / traces / status | 对话命令：chat / smoke / test / bench |
| 怎么拿 | 控制台个人菜单「访问令牌」自己建，再 `nac auth login --pat <令牌>`（Linux 存系统密钥环，只需一次） | 新项目自带一把 `default`：`nac keys list --json` 取 `id` 和 `access_key`，`nac keys secret <id>` 取 `secret_key`（随时可取回，不是只显示一次），自己拼成 `ak:sk` |

> `nac keys secret <id>` **只返回 secret_key**，不含 access_key，要自己拼。
> AK:SK **只写在单条对话命令前面**：`NAC_TOKEN="ak_xxx:sk_xxx" nac chat dev -m "你好" --json`。
> 别 `export NAC_TOKEN=` 成 AK:SK，否则后面的 `nac deploy` / `nac dev` 全部 401。

## Decision tree

```
用户需要什么？
├── 快速操作 → Shortcuts（status, smoke, deploy；nac dev 有坑，见「nac dev 实际行为」）
├── 精细控制 → Resource CRUD（nac versions deploy ...）
└── SDK 未覆盖 → Raw API（nac api GET /api/...）

对话要等多久？
├── 短问答，等得起 → nac chat / POST /agent-api/chat（阻塞到跑完）
└── 长任务，不想挂住连接 → chat 当扳机（**必须 stream:true**）+ /events 或 /runs 观测
    └── ⚠️ stream 缺省是 false，那条路上 events 是空的 → 见 Async 一节

认证选哪个？
├── 管理操作 (projects/versions/keys...) → PAT token（--token nacp_xxx）
└── 对话操作 (chat/smoke/bench) → AK:SK（--token ak_xxx:sk_xxx）
```

## Output conventions

- **Always use `--json`** for structured, parseable output
- **Write operations**: use `--dry-run` to preview before executing
- **Errors in JSON mode**: `{"error": true, "message": "..."}` on stderr

## Authentication

Two modes — pick by the command, and an agent must use the right one:

| Mode | Token format | Use for | Get it from |
|------|-------------|---------|-------------|
| PAT | `nacp_xxx` | Management APIs (projects, versions, keys, deploy, logs...) | `nac auth login` |
| AK:SK | `ak_xxx:sk_xxx` | Agent Gateway (chat, smoke, test, bench) | `nac keys create <pid> --name <name> --json` |

`--token` / `--base-url` / `--project-id` are also read from `NAC_TOKEN` /
`NAC_BASE_URL` / `NAC_PROJECT_ID`. `--north-env` / `NORTH_ENV` (`dev|beta|prod`,
aligned with North Studio) picks a backend by name — `dev`→nac-alpha,
`beta`→nac-beta, `prod`→nac.xiaobei.top; an explicit `--base-url`/`NAC_BASE_URL`
overrides it.

### How an agent should supply the token (read this — it's the #1 login pitfall)

> ⚠️ **`export NAC_TOKEN=...` as its own step usually does NOT work for agents.**
> Most agent runtimes run every shell command in a fresh process, so an `export`
> in one tool call is gone by the next → `No authentication found`. Don't rely on
> `export` persisting across calls.

Use one of these instead:

- **Management ops — log in once; it persists to disk and survives every later
  call** (writes `~/.nac/credentials`, 0600, or the OS keyring):
  ```bash
  nac auth login --pat nacp_xxx        # non-interactive; do this first
  nac projects list --json             # now works with no --token
  ```
- **Gateway ops (chat / smoke / test / bench) — pass AK:SK inline, per command.**
  A stored login is a **PAT**, which the gateway does not accept (0.4.x: 400 `Missing X-Project-Id header`); the gateway needs AK:SK:
  ```bash
  AKSK=$(nac keys create <pid> --name ci-key --json | jq -r '.access_key + ":" + .secret_key')
  NAC_TOKEN="$AKSK" nac chat staging -m "..." --json     # or:  nac chat staging --token "$AKSK" ...
  ```
- **One-off / scripting — inline env (or `--token`) on the same line.** Self-contained,
  no cross-call state needed: `NAC_TOKEN=nacp_xxx nac versions list <pid> --json`.

Never mix the two modes: PAT on the gateway → 400 `Missing X-Project-Id header` (0.4.x); AK:SK on management → 401.

### 用错钥匙时的两种报错（0.4.x 实测）

| 现象 | 原因 | 处理 |
|---|---|---|
| `chat` / `smoke` 报 **400 `Missing X-Project-Id header`** | 对话命令用了访问令牌（nacp_） | 改用 AK:SK，写在这条命令前面 |
| `deploy` / `dev` / `projects` 等管理命令报 **401 `Unknown error`**（`nac dev` 表现为 `Failed to create ephemeral lane: 401`） | 环境变量 `NAC_TOKEN` 被设成了 AK:SK，顶掉了登录的令牌 | `unset NAC_TOKEN`，AK:SK 只放单条对话命令前 |
| 对话命令 401 `INVALID_CREDENTIALS` | AK:SK 写错、拼错，或这把密钥已吊销 | `nac keys list --json` 核对 |
| 不带地址的命令 401 | 令牌属于别的环境，而 CLI 默认连官方正式环境 | 见上面「先配地址」 |

On errors:
- Gateway cmd → 0.4.x with a PAT: 400 `Missing X-Project-Id header`; `INVALID_CREDENTIALS` means the AK:SK is wrong or revoked. (`Basic authorization with project credentials required` only shows up on older versions or when no credential is sent.) Get AK:SK from `nac keys create <pid> --name <name> --json` and pass it inline.
- Management cmd → 401: you used AK:SK; use a PAT (`nac auth login`, then no flag needed).

## Shortcuts

| Command | What it does | Auth |
|---------|-------------|------|
| `nac status` | Project overview (environments + deploy status) | PAT |
| `nac init` | Create nac.json in current directory | PAT |
| `nac deploy <env>` | Pack → upload → deploy to persistent environment | PAT |
| `nac dev` | Ephemeral lane development flow（实际行为和坑见下面「nac dev 实际行为」） | PAT |
| `nac smoke` | Quick health check (single chat request) | AK:SK |
| `nac chat <env> -m "..."` | Single-round chat with agent | AK:SK |
| `nac test <env>` | Run nac-tests.yaml test suite | AK:SK |
| `nac bench <env>` | Pressure test with concurrent requests | AK:SK |
| `nac logs` | Fetch recent logs | PAT |
| `nac traces` | List traces | PAT |
| `nac trace <id>` | View single trace | PAT |
| `nac clean` | Clean up ephemeral environments early (server's TTL reconciler does this automatically) | PAT |

## nac dev 实际行为与推荐开发循环（0.4.3 / 0.4.4 实测）

`nac dev` 会建一个带 1 小时 TTL 的临时环境（十几秒就绪），然后**一直占着终端**。实测几个和帮助文字不一样的地方：

- `--watch` 和 `--chat` 在 0.4.x 里**没有实现**（源码里参数被忽略），在任何机器上都一样：改提示词 / 配置 / 工具后不会自动重新部署，也不会进对话窗口（只停在 `Press Ctrl+C`）。要对话，另开一个终端用 `nac chat <临时环境名> -m "..." --json`。
- `Ctrl+C` 的自动清理会失败：**409 RESOURCE_CONFLICT「Cannot delete environment while it has an active release」**，`nac clean` 同样 409，临时环境和版本会留在那里。
- 用 `timeout` 之类强杀 `nac dev`，连清理都不会尝试。

**推荐循环（比 nac dev 稳）**：建一个持久的 dev 环境，改完直接重新部署。

```bash
nac environments create --name dev --json     # 只做一次
nac deploy dev --yes                          # 改完文件就跑，十几秒到半分钟
NAC_TOKEN="ak_xxx:sk_xxx" nac chat dev -m "你好" --json | jq -r '.content'
```

聊天窗口想要图形界面，就用控制台的「试验场」。
部署时出现 `warning: unable to fetch deploy logs (404 ... has no active release)` 可以忽略。
`nac deploy` 打的版本标签是时间戳，**不读 `VERSION` 文件**。

**手动清理 nac dev 留下的临时环境**（`dev-xxxx` 是 nac dev 输出的名字）：

```bash
nac versions list --json | jq -r '.[] | select(.status=="active") | [.id,.tag] | @tsv'   # 找 active 且标签带 __dev__ 的版本
nac versions deactivate <version-id> --confirm
nac environments delete dev-xxxx
```

> `versions list` 的字段名随版本可能不同，上面 jq 只是示意，以 `--json` 实际输出为准。

## chat、日志、trace 的取法（0.4.x 实测）

- **0.4.x 的交互模式（`nac chat <env>` 不带 `-m`）不要用**：不论加不加 `--json`，它都会打印工具结果并按 80 字节截断，遇到含中文的结果会 **panic**。
  对话一律单轮：`nac chat <env> -m "..." --json`（或 `--stdin --json`），回答在 `.content`：`nac chat dev -m "..." --json | jq -r .content`。要聊天窗口就用控制台试验场。
  工具返回太大导致 400 后，同一会话之后每条都会 400，要新开会话。
- 工具调用在 **`.messages[].tool_calls`**（没有顶层 `tool_calls`，也没有 `trace_id`）。想找对应 trace：拿返回里的 `session_id`，去 `nac traces` 列表的 Session 列对。
  ```bash
  nac chat dev -m "上海天气" --json | jq '.messages[] | select(.tool_calls) | .tool_calls'
  ```
- **`--last` / `--level` / `--grep`：alpha 实测服务端未生效，只返回最近 200 行，其他平台未验证**（CLI 会把它们交给服务端）。稳妥做法是 `--json` 后自己过滤：
  ```bash
  nac logs dev --json | jq -r '.response.logs' | grep -v '"DEBUG"'
  nac logs dev --json | jq -r '.response.logs' | grep mock_weather
  ```
- **看每次模型调用和工具的入参 / 返回**：
  ```bash
  nac traces --last 1h --limit 5
  nac trace <trace-id> --export --json -o t.json
  jq '.observations[] | {type, name}' t.json
  ```
- `nac smoke` 只验通路（默认发 ping），不验工具；文本模式不显示回复，要内容加 `--json`。验工具用 `nac chat`。

## CRUD commands

```bash
# Projects
nac projects list --json
nac projects get <project-id> --json
nac projects create --name "My Agent" --json

# Versions
nac versions list <project-id> --json
nac versions create <project-id> --tag v1.0 --json

# Environments — persistent + ephemeral
nac environments list <project-id> --json
nac environments create <project-id> --name staging --json                      # persistent
nac environments create <project-id> --name lab --ttl 1h --json                 # ephemeral, TTL = 1h
nac environments create <project-id> --name pr-preview --ttl 7d --json          # max TTL = 7d
nac environments extend <env-name> --ttl 2h --json                              # override TTL
nac environments extend <env-name> --json                                       # fallback to original TTL
# --ttl accepts humantime: 60s, 5m, 1h, 72h, 7d. Range: [60s, 7d].
# Ephemeral envs are auto-cleaned by the server-side reconciler when expires_at lapses.

# Project env vars — appear in deployed agent's resolved_env
nac vars list <project-id> --json
nac vars set --project-id <project-id> KEY VALUE --json                                      # upsert
nac vars set --project-id <project-id> SECRET_KEY "sk-..." --secret --json                   # mark secret
nac vars delete --project-id <project-id> KEY --json
nac vars sync --project-id <project-id> .env.production --json                               # batch replace from dotenv
nac vars sync --project-id <project-id> .env --merge --json                                  # merge (don't replace)
nac vars sync --project-id <project-id> .env --secret API_KEY --secret DB_PASS --json        # mark specific keys secret
nac vars sync --project-id <project-id> .env --dry-run --json                                # preview

# LLM — model selection lives in agent.yaml (`llm_config.model: provider/model_name`, optional)
nac llm show <project-id> --json                # project default model (legacy platforms: active config)
nac llm list-available <project-id> --json      # models this project may use (provider/model full keys)
# Per-agent model: edit agent.yaml `llm_config.model`, then `nac deploy`.
# Project default model: nac api PUT /api/projects/<pid> --body '{"default_llm_model":"<provider/model>"}'
# `nac llm set` is the RETIRED project-level switch — current platforms return 410 with guidance.
#
# ⚠️ On newer platforms the whole `nac llm` group is gone, not just `set`:
#   nac llm show          → 410 {"error":"Project-level LLM settings are deprecated..."}
#   nac llm list-available → 404 (empty body)
# To discover which model identifiers a project may actually use, read them off past traces —
# `observation.input.model` carries the FULL key incl. provider prefix, while `observation.model`
# is the resolved bare name:
#   nac trace <id> --export --json -o t.json
#   jq -r '.observations[] | select(.type=="GENERATION") | .input.model' t.json | sort -u
# This is also the ONLY reliable way to confirm which model an agent really ran on: an unknown
# `provider/model` in agent.yaml is silently graceful-fallback'd to the project default (a YAML
# saying `default/Nex-N2-Pro` can execute as `multimode/Nex-N2-Pro` without any warning).

# Sessions
nac sessions list <project-id> --json
# ⚠️ A session_id MUST be issued by the platform — you cannot invent one. Fabricating a
# well-formed `sess_<ULID>` and passing it to /agent-api/files or /agent-api/chat fails with a
# MISLEADING error: `SERVICE_UNAVAILABLE: Session Manager unavailable` (the service is fine; the
# session simply does not exist). Mint one first — see "Raw APIs the CLI does not cover" below.

# API Keys
nac keys list <project-id> --json
nac keys create <project-id> --name "ci-key" --json
nac keys revoke <key-id> --project-id <project-id> --json   # key-id is positional; project via --project-id/nac.json

# Channels
nac channels list <project-id> --json
nac channels create <project-id> --platform feishu --json

# Raw API (escape hatch)
nac api GET /api/projects --json
nac api POST /api/projects --body '{"name":"test"}' --json
nac api PUT /api/projects/<pid>/versions/<vid>/deploy --body '{"environment":"prod"}' --json
```

## Raw APIs the CLI does not cover

Three common operations have **no CLI command** and must be driven with `curl`. All three are
required for the single most common end-to-end task — *upload an artifact, then ask the agent to
process an attached file* — so they are documented here rather than left to source-diving.

### 1. Upload an artifact (PAT) — the route is **project-scoped**

```bash
curl -X PUT "$BASE/api/projects/$PID/versions/$VID/artifact" \
  -H "Authorization: Bearer $PAT" -H "Content-Type: application/x-tar" \
  --data-binary @artifact.tar
```

⚠️ **`PUT /api/versions/{id}/artifact` (no project segment) is stale and 404s** — the versions/artifact routes moved under `/projects/{id}`. Some older docs still show the short form.
A tar with one top-level directory is fine: the backend picks `nexau.json` by shallowest depth,
and the runtime flattens a lone top-level dir on extract (directory names with spaces included).

### 2. Create a session (AK:SK) — must precede file upload / chat

```bash
SID=$(curl -sS -u "$AK:$SK" -X POST \
  "$BASE/agent-api/sessions?project_id=$PID&environment=$ENV" \
  -H 'Content-Type: application/json' -H "X-Project-Id: $PID" \
  -d '{"distinct_id":"my-caller"}' | jq -r .session_id)
```

Only `distinct_id` is required. See the warning in the Sessions block above — a self-invented
session id surfaces as `Session Manager unavailable`, which sends you debugging the wrong service.

### 3. Attach a file to a session (AK:SK) — `nac chat` cannot do this

```bash
curl -sS -u "$AK:$SK" -X POST \
  "$BASE/agent-api/files?project_id=$PID&environment=$ENV&distinct_id=my-caller" \
  -H "X-Nexau-Session-Id: $SID" \
  -F "session_id=$SID" -F "file=@scan.pdf;type=application/pdf"
```

Multipart field names are exactly `session_id` and `file`; anything else is ignored and the
request fails with `file field is required`. Limit is 100 MiB. The response echoes the sandbox
path the agent will see (`/home/user/uploads/<name>`). Then run the chat turn on the **same**
`session_id` and the agent can read the file.

### ⚠️ `nac chat` and raw `POST /agent-api/chat` return **different shapes**

Reading the wrong key makes a successful run look empty — budget a minute for this trap:

| | `nac chat --json` | raw `POST /agent-api/chat` |
|---|---|---|
| answer text | `.content` | **`.response`** |
| status value | `"completed"` | **`"success"`** |
| also present | `.messages[]` (with `tool_calls`), `.error` | `.model_fallback` |

Both carry `.session_id`. When scripting against the raw endpoint, read
`.response // .content` and treat `"success"` and `"completed"` as equivalent.

⚠️ That raw column describes the **non-streaming** shape, which is what you get when the request
body omits `stream`. That default has consequences well beyond the response shape — read the next
section before using it for anything long-running.

## Async / long-running work — chat is the trigger, `/events` is the channel

**NAC can be driven asynchronously.** You don't have to hold an HTTP connection open for the whole
turn. But the async path exists **only on the streaming branch**, and `stream` defaults to
`false` — so the obvious-looking "fire a normal chat, then poll for progress" lands on a path
where the agent blocks the call *and* publishes no events at all.

> ⚠️ **Two different things get called "async" here — don't stop at the first one.**
> The platform's [Python 异步 Session 调用教程](https://nac.xiaobei.top/docs/async-session-python)
> is `asyncio`-async: correct `stream: true`, `httpx.AsyncClient`, `async def` — but it drains the
> SSE stream to completion *before* it polls, so the connection still stays up for the whole turn
> and the poll only ever observes an already-terminal run. That is **not** the "don't hold the
> connection" async described below. If your goal is to hand off a long turn and walk away, follow
> this section, not that tutorial's main flow.

| | `"stream": false` (the default) | `"stream": true` |
|---|---|---|
| HTTP call returns | only after the whole turn finishes; gateway caps it at 300s | at the first SSE frame |
| `run_id` obtainable | **no** — the response body has no run id | yes, off the first `RUN_STARTED` |
| `GET /sessions/{sid}/events` carries | **only one synthetic `USER_MESSAGE_RECEIVED`**, which has no `run_id` | full run lifecycle + token events |

This isn't a slow path, it's a dead one: on the platform side the event-bus tap is wired only
into the streaming branch of the gateway proxy, and the runtime tracks `RUN_STARTED` only in its
stream handler — the non-streaming branch publishes nothing. Measured on one prompt (2026-08-03,
real cluster): non-streaming produced **1** event, streaming produced **62**; and a task that
needed **0.11s** to hand back a `run_id` held the non-streaming HTTP call open for **34.85s**.

### The async pattern that works today (no platform change required)

1. `POST /agent-api/chat` with **`"stream": true`** and `Accept: text/event-stream`.
2. Read frames only until the first `RUN_STARTED` — that frame carries `run_id`.
3. **Drop the connection.** `disconnect ≠ stop`: the gateway's drainer owns the upstream stream
   and keeps consuming it, so the agent runs to completion. The *only* way
   to actually cancel is `POST /agent-api/stop` — and that is **session-scoped**, it takes no
   `run_id`.
4. Track the run on either channel, by `run_id`:
   - **Live (push)** — `GET /agent-api/sessions/{sid}/events`, SSE. Resume after a drop with
     `?last_event_id=<id>` (or the `Last-Event-ID` header); an empty cursor means "new events
     only, no backlog replay". ⚠️ Only lifecycle events carry `run_id` — content deltas don't,
     so you cannot filter reply text by run.
   - **Polling (pull)** — `GET /agent-api/sessions/{sid}/runs` →
     `{"runs":[{"id":"run_…","status":"submitted|working|input-required|completed|failed|canceled",
     "startedAt":…,"finishedAt":…,"traceId":…}]}`. This is the "treat a run as a background task"
     shape. `…/actions` gives the per-run action stream, and **every action carries `runId`**.
     ⚠️ **The two readers use different status vocabularies.** `/runs` returns the materialised
     A2A words above; `/actions` still returns raw nexau words
     (`ok` / `succeeded` / `error` / `stopped` / …) on its `entities.runs` map. Don't test for
     `"completed"` against `/actions` — it won't match. Also note `entities.runs` is keyed **by**
     run id and its values carry no `id` field, whereas `/runs` items do.

Both readers take the same AK:SK as chat, and both 404 for a session the credential doesn't own.

This is exactly what the TS SDK already ships as `session.chat.trigger()` — it POSTs with
`stream: true` and cancels the response body without reading it
. Runnable shell recipe:
[Workflows → Async: fire and observe](references/workflows.md#async-fire-and-observe).

### What is NOT available yet — do not design around it

- **No idempotency.** Two byte-identical chat POSTs sent serially (the first already finished)
  produce **two runs**, silently. The `409 SESSION_BUSY` you may have hit is a *session* lock that
  only fires while a previous run is still going — it does **not** cover the crash-then-retry
  window, which is precisely when you'd want idempotency.
- **The kick response does not return a `run_id`.** Step 2 above is the only way to get one.
- A dedicated async endpoint (`POST /agent-api/runs` → `202` + `run_id` + idempotency key) is
  **proposed, not shipped** (under review). Build against the pattern above; treat that
  endpoint as nonexistent until it appears in the gateway's route table.

### CLI coverage (thin — expect to use `nac api` / `curl`)

`nac chat` does POST with `stream: true`, so its events *are* tapped — but it drains the stream to
completion and its `--json` output does not surface the `run_id`. There is no `nac events` /
`nac runs` command. Use the escape hatch for the polling half:

```bash
NAC_TOKEN="$AK:$SK" nac api GET /agent-api/sessions/$SID/runs --json
NAC_TOKEN="$AK:$SK" nac api GET /agent-api/sessions/$SID/actions --json
```

The two SSE halves (the `stream: true` kick, and tailing `/events`) have no CLI surface — use
`curl`, as shown in the workflows recipe.

## Variables on chat / smoke

`nac chat` and `nac smoke` support per-call variable injection — useful when the agent reads `agent_state.get_variable()` at runtime:

```bash
# Single variable
nac --token "ak:sk" chat staging --var TENANT_ID=acme -m "list my projects"

# From dotenv file
nac --token "ak:sk" chat staging --vars-file .env.demo -m "..."

# Sandbox env (for code interpreter / shell tools)
nac --token "ak:sk" chat staging --sbx-env DATABASE_URL="postgres://..." -m "..."

# Jinja template variables (substituted in system_prompt)
nac --token "ak:sk" chat staging --tmpl-var role=admin -m "..."
```

For values that should persist across all chat calls, use `nac vars set` instead — they go into `resolved_env` at deploy time.

## Config files

### nac.json (created by `nac init`)
```json
{"project_id": "xxx", "base_url": "https://nac.xiaobei.top"}
```
When present, `--project-id` and `--base-url` are auto-resolved (只在该目录及子目录生效).
0.4.x 实测：`nac init` 只会写 `project_id`，**不会**写 `base_url`，连非正式环境时要自己手写这一行（见上面「先配地址」）。

### nac-tests.yaml (for `nac test`)
```yaml
tests:
  - name: "basic"
    message: "hello"
    assert:
      status: completed
      latency_ms: "< 5000"
      content_contains: "keyword"
```

### agent.yaml — minimal template

The agent project directory must contain `agent.yaml` + `system-prompt.md` + `nexau.json` (`VERSION` is optional; `nac deploy` does not read it). The **minimal** `agent.yaml`:

```yaml
type: agent
name: my_agent
max_context_tokens: 200000
system_prompt: ./system-prompt.md
system_prompt_type: jinja
tool_call_mode: structured
max_iterations: 50
llm_config:
  max_tokens: 8000
  temperature: 0.7
tools: []
skills: []
stop_tools:
  - complete_task
```

**Do NOT write these fields — platform injects / derives them**:

| Field | Why omit | Platform behavior |
|---|---|---|
| `sandbox_config` (entire block) | Platform allocates sandbox per customer/env | Writing it gets overridden |
| `llm_config.base_url` | Platform injects per the matched model card | Writing it gets overridden |
| `llm_config.api_key` | **Never** write API keys in YAML | Platform injects secret-managed key |
| `llm_config.api_type` | Derived from the matched model card | — |
| `llm_config.stream` | Platform decides based on caller (SSE vs JSON) | — |

**DO write `llm_config.model` when you want a specific model** — it is the one connection-adjacent
field that is yours: full key `provider/model_name`（须是项目已授权模型，用 `nac llm list-available`
查看）。不写 `model`（或整段省略 `llm_config`）就跟随项目默认模型。裸名 / 拼错 / 未授权**不会**让
部署失败——runtime 静默优雅回落项目默认，且该段采样参数一并弃用（graceful fallback）。

Keep **per-agent business parameters** in `llm_config`: `max_tokens` + `temperature` + (optionally) `top_p` / `frequency_penalty`.

### nexau.json — agent manifest

```json
{
  "agents": { "my_agent": "agent.yaml" },
  "excluded": [".nexau/", ".env", "__pycache__/"]
}
```

`agents` maps agent name → yaml path. Multi-agent projects list each agent with its own yaml.

### VERSION

Single-line file containing semver string, e.g. `0.1.0`. 0.4.x 实测：`nac deploy` 打的版本标签是时间戳，**不读这个文件**；它只是你自己记版本用。

## 写智能体制品时已验证的几点（alpha 实测）

- 自定义工具返回 `{"content": ...}`。
- 在 `agent.yaml` 里声明 `skills` 后，`LoadSkill` 会自动注入，**不要手写**。
- 系统提示词里要有这句原话：`skills 根目录位于 /home/user/.skills/`（控制台构建检查按原句找；命令行 `nac deploy` 不强制，但照抄最稳）。
- 想要固定输出格式，在 skill 里明确写「模板前后不要加别的话」；只写「第一行必须是……」，模型仍可能先写一句「结论：」（单个样本，不是保证）。
- 不写 `llm_config.model` 就跟随项目默认模型。

## References

- [Workflows](references/workflows.md) — Step-by-step recipes for common tasks
- [Error Recovery](references/error-recovery.md) — Error → fix mapping table
- [Troubleshooting](references/troubleshooting.md) — Common errors and debugging
