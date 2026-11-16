---
name: nexau-deploy-and-debug
description: >-
  North Agent Cloud（NAC）/ NexAU 平台的**部署上线与排障**技能 —— 与 `nexau-artifact-builder`
  平级互补：那个管「制品怎么写」，这个管「怎么发上去、出问题怎么查」。当用户要部署 / 发版 / 上线 /
  回滚 / 切环境 / 建临时环境 / 配环境变量 / 做 CI 冒烟与压测，或提到
  nac deploy / nac dev / nac promote / nac versions / nac environments / nac logs / nac traces /
  nac trace / nac smoke / nac test / nac bench / nac status / nac vars / nac api / nac auth 时使用。
  也覆盖全部排障场景：agent 没回复 / 回复是空的 / 部署完行为还是老的 / 改了代码不生效 /
  部署显示成功但报 ModuleNotFoundError / setup 失败 / 403 VERSION_NOT_ACTIVE /
  403 VERSION_NOT_ROUTABLE / 404 VERSION_TAG_NOT_FOUND / 404 session not found /
  会话建成功了但一发对话就 404 / 环境上没有激活版本 / 打包上传被拒 / 制品里少了文件 /
  401 凭据没问题却被拒 / AKSK_NOT_ALLOWED_ON_CONTROL_PLANE / 409 SESSION_BUSY / LOCK_CONFLICT /
  429 / Retry-After / 容量拒绝 / 冷启动 / 第一次调用特别慢 / 超时 / stream:false 返回 500 /
  SSE 断流 / 收不到事件 / RUN_STOPPED 界面卡在生成中 / 心跳行解析崩 / 指定的模型没生效 /
  shell 输出被截断 / Maximum iteration limit reached / 制品 100MB / 符号链接丢失 /
  沙箱文件下次就没了 / apt 装的包没了 / 连不上内网服务 / 出网白名单 / IPv6 不通 /
  临时环境到期突然全 403 / trace 显示 encrypted / Langfuse not configured /
  request_id 与 trace id 怎么拿 / 报障要带什么 /
  这个报错是哪一边的 / 是前置网关还是 NAC 的问题 / 模型服务报错 / 经网关调用报错
  （前置网关在前、NAC 在后、模型与沙箱在更后面时，判断报错归谁）。
  涵盖：两种凭据的边界与自检、部署与版本命令全表、发布与回滚节奏、受保护环境与不可逆操作、
  排障固定次序、九个证据面的取证方法与输出形状、症状速查、错误码与错误原文速查、
  平台限制与自测法、报障清单，以及一份「会骗你的判据」清单。
---

# NAC 部署上线与排障

> **写给谁**：在 NAC 平台上运行 agent 的**使用者**。你有平台账号、Web 控制台、`nac` 命令行和
> 公开 API；**没有源代码、没有集群权限**。本 skill 里的每条判据都能用这三样自己验证。
>
> **和另一个 skill 的分工**：制品怎么写（`agent.yaml` / 工具 / Skill / MCP / 依赖 / 对象存储）
> 一律去 `nexau-artifact-builder`。本 skill 从「制品已经写完了」开始接手。
>
> **概念不在这里**：版本 = 不可变快照、环境 = 指针、蓝绿切换、平台管什么你管什么 ——
> 这些看使用指南正文；本 skill 只讲**怎么做**和**判据是什么**。

## 0. 怎么用本 skill

| 我要做什么 | 去哪 |
|---|---|
| **第一次上手：装 nac、配地址、分清两把钥匙** | 本文 §0.5 |
| **先搞清楚我有没有权限做这件事** | 本文 §1（**必读，它决定后面一半内容你能不能用**） |
| 推荐的「改 → 部署 → 验证」循环、`nac dev` 的坑 | 本文 §2.6 |
| 部署 / 回滚 / 建环境 / 删环境 | 本文 §2 |
| 出问题了，不知道从哪下手 | 本文 §3 的六步次序 → §4 症状表 |
| **「我这把 PAT 能做什么 / 这件事是不是要管理员」** | `references/pat-permissions.md`（含全部 CLI 命令的权限档位表） |
| 查某个具体命令的参数和输出 | `references/cli-reference.md` |
| 想知道某份证据（日志 / trace / `/runs` / SSE）里到底有什么、怎么读 | `references/evidence-sources.md` |
| 「我遇到的现象是 X」 | `references/symptom-index.md`（按使用者会说的话索引，含 2026-11 新增 6 条） |
| 打包 / 上传制品被拒、包里少了东西 | `references/cli-reference.md` §2 + `references/platform-limits.md` §1 + `references/error-codes.md`「制品上传」 |
| 「我收到了 4xx/5xx，这个码什么意思」 | `references/error-codes.md`（含 message 原文速查） |
| **「这个报错是谁的：前置网关 / NAC / 模型服务 / 沙箱」**（经网关调用时尤其要先看这个） | 本文 §4 与「第 1.5 步」 |
| 「这个东西有没有上限 / 撞到会怎样 / 能不能调」 | `references/platform-limits.md` |
| 报障要准备什么 | 本文 §5 |
| 我怀疑某个「绿」是假的 | 本文 §6（会骗你的判据清单） |

---

## 0.5 部署前三件事（先做完再往下，0.4.x 实测）

**结论：装 nac → 先配平台地址（不配就是连正式环境）→ 分清两把钥匙。** 这三件没做对，后面的报错都会很难看懂。

### ① 装 nac：一定用 `| bash`，别用 `| sh`

```bash
# macOS / Linux（必须 bash）
curl -fsSL https://download.xiaobei.top/nac-cli/install.sh | bash
# Windows PowerShell（装到 %LOCALAPPDATA%\Programs\nac 并自动加 PATH，不需要管理员）
irm https://download.xiaobei.top/nac-cli/install.ps1 | iex

curl -fsSL https://download.xiaobei.top/nac-cli/install.sh | NAC_VERSION=0.4.4 bash          # 指定版本（变量放在 bash 前面）
curl -fsSL https://download.xiaobei.top/nac-cli/install.sh | NAC_INSTALL_DIR=$HOME/bin bash   # 指定安装目录
nac --version
```

- 脚本开头有 `set -o pipefail`，Ubuntu 上 `sh` 是 dash，会报 `Illegal option -o pipefail`，装不上。
  ⚠️ 脚本里自己的注释和装完后的提示写的是 `| sh`，**那是错的，照上面用 bash**。
- `download.xiaobei.top` 是公开下载地址；私有化部署的用户换成交付方给你的下载地址。
- 写本文时 latest 是 0.4.4。

### ② 先配平台地址：零配置默认连**官方正式环境（https://nac.xiaobei.top）**

`nac` 不告诉它连哪就连默认的正式环境。把下面这行写进 `~/.bashrc` / `~/.zshrc`（下文用 alpha 公开地址做示例，**换成你自己部署的地址**）：

```bash
export NAC_BASE_URL=https://nac-alpha.xiaobei.top
nac api GET /api/auth/me --json   # 自检：200 = 令牌属于这个平台；401 = 地址或令牌不对
# 注意 nac auth whoami 只显示本机存的令牌（打码），不连服务器、不显示地址，不能用来自检
```

0.4.x 实测，**哪些写法有效、哪些没用**：

| 写法 | 结果 |
|---|---|
| `--base-url <url>`（每条命令都带） | ✅ 有效 |
| 环境变量 `NAC_BASE_URL` | ✅ 有效，推荐（⚠️ 它和 `NORTH_ENV` 都会盖掉 `nac.json` 里的 `base_url`；写进 bashrc 后项目里的地址就不起作用了） |
| 环境变量 `NORTH_ENV=dev` | ✅ 有效（等于 alpha，仅官方环境） |
| 项目目录 `nac.json` 里**手写** `"base_url"` | ✅ 只在该目录及子目录生效 |
| `nac auth login --base-url …` | ❌ 不会记住地址（只存了令牌） |
| `nac init --base-url …` | ❌ 不会写进 `nac.json`，要手动加 |
| `~/.nac/config.toml`（试了五种写法） | ❌ 都不生效，别在这上面耗时间 |

### ③ 两把钥匙，各管各的（详见 §1）

| 钥匙 | 长相 | 用在哪 |
|---|---|---|
| 访问令牌（PAT） | `nacp_…`，代表你本人 | 管理命令：`deploy` / `versions` / `environments` / `logs` / `traces`。控制台个人菜单「访问令牌」自建，`nac auth login` 不带参数交互粘贴，或 `nac auth login --pat <令牌>`（Linux 存系统密钥环） |
| API 密钥 | `ak_xxx:sk_xxx`，代表**一个项目**（新项目自带 `default`） | 只用于对话：`nac chat` / `smoke` / `test` / `bench` |

拿 API 密钥：`nac keys list` 取 id 和 access_key；`nac keys secret <id>` **只返回 secret_key**，要自己拼成 `access_key:secret_key`。

**只写在单条对话命令前面，不要 export 成全局变量**：

```bash
NAC_TOKEN="ak_xxx:sk_xxx" nac chat dev -m "你好" --json
```

用错的报错（0.4.x 实测）：

| 做法 | 报错 |
|---|---|
| `chat` / `smoke` 用了访问令牌（PAT） | `400 Missing X-Project-Id header` |
| 管理命令（`deploy` / `versions` …）被全局的 `NAC_TOKEN=ak:sk` 顶掉 | `401 Unknown error`（不是 403，看不出原因） |

⇒ 管理命令用 PAT，对话命令才临时带 AK:SK；`NAC_TOKEN` 别长期留在 shell 里。

---

## 1. 先确认你有哪把钥匙（**从这里开始，不要跳**）

平台有两个面，**凭据不通用**。这条不先弄清楚，后面所有排障命令都会以看不懂的 401/403 收场。

| 凭据 | 请求头写法 | 能打哪个面 | 怎么拿 |
|---|---|---|---|
| 项目 **AK/SK** | `Authorization: Basic base64(ak:sk)` | **只有对话面** `/agent-api/*`：`chat` / `sessions` / `runs` / `actions` / `events` / `files`；CLI 的 `nac chat` / `smoke` / `test` / `bench` | SK 可随时用 `nac keys secret <id>` 取回（只返回 secret_key，要和 `nac keys list` 里的 access_key 拼成 ak:sk），也可以在控制台显示密钥 |
| 个人令牌 **PAT** | `Authorization: Bearer nacp_…`（打对话面时**还必须**带 `X-Project-Id: <项目 uuid>`） | **管理面** `/api/*` 全部：`deploy` / `versions` / `environments` / `logs` / `traces` / `vars` / `status` / `api`；也能读对话面 | `nac auth login --pat nacp_xxx`（或不带参数交互粘贴），在控制台个人菜单「访问令牌」自建，或 `nac tokens create <名字>` |

```bash
nac auth whoami          # 只显示本机存的令牌（打码），不验证平台；自检用 nac api GET /api/auth/me --json
nac auth login           # 交互粘贴 PAT
nac auth login --pat nacp_xxx        # 非交互（CI）；nacp_xxx 换成你自己的令牌（login 只认 --pat，全局 --token 会被忽略、退回等标准输入粘贴）
nac tokens list / create <name> / delete <id>
```

**三条硬边界**（每条都有专属报错，见 `references/error-codes.md`）：

1. **AK/SK 打管理面直接 403**，message 原文 `AK/SK credentials are valid only on the data plane (/agent-api/*)…`。
   ⇒ **只拿到 AK/SK、没有控制台账号的人，用不了 `nac deploy` / `logs` / `traces` / `versions`**，
   排障只能靠对话面证据（§3 里标了「AK/SK 可用」的那几项）+ §5 报障清单。
2. **PAT 打对话面忘带 `X-Project-Id` 是 400 不是 401**，message `Missing X-Project-Id header (required when using user credentials)`。
   别在 401 分支里找它。
3. **PAT 和 AK/SK 读同一个 session 的可见范围不一样**：AK/SK 只校验「session 属于本项目」，
   PAT 还额外校验「发起人是我」（比对建 session 时的 `distinct_id`）⇒ 同一个 session
   AK/SK 读得到、PAT 读 `404 session not found`。**这不是 session 丢了**，见 §4。

⚠️ 0.4.x 实测：如果 shell 里全局设了 `NAC_TOKEN=ak:sk`，管理命令返回的是 **`401 Unknown error`**（不是上面的 403）——同样是「拿 AK/SK 打了管理面」。

给 CLI 临时换凭据：`nac --token "ak_xxx:sk_xxx" smoke staging`（`--token` 同时接受 PAT 和 `ak:sk`）。

### 1.1 PAT 能做多少事 —— 三条先记住

1. **PAT 就是你本人，没有权限范围。** 创建时只能设名字和有效期（`7d`/`30d`/`90d`/`365d`/永不过期），
   **做不出「只读 PAT」或「只管一个项目的 PAT」**。⇒ **一把 PAT 泄露 = 整个账号泄露**：
   给 CI 的令牌设短有效期、一个用途一把、定期用 `nac tokens list` 清掉不用的。
2. **非管理员也能创建 PAT**，这是正常的 —— 它不是提权手段，跟管理员身份无关。
   反过来，**管理员身份挂在账号上不在令牌上**：同一把 PAT，账号被授予/取消管理员之后能做的事会立刻跟着变。
3. **常规开发部署一件管理员的事都不需要。** 24 个顶层命令没有一个要管理员权限。
   ⭐ **尤其是：你自己创建的项目，你就是 owner —— 读写治理全部直接放行**，
   用自己的 PAT 部署到自己项目的环境是完全正常的日常操作，不需要任何额外授权。
   「够不够权限」这个问题只在**别人的项目、你被拉进去协作**时才需要问。

**判据（够用了）**：**路径以 `/api/admin/` 开头 = 必须管理员，其余都不是。**
只有 `nac api` 这个逃生舱能打到它们，其余 23 个命令都碰不到。

完整的「命令 → 需要哪一档」对照表、以及三种 403 怎么区分，见 `references/pat-permissions.md`。

---

## 2. 部署与版本管理

### 2.1 命令动词（别照直觉猜，猜错的命令**不一定报错**）

**平台没有** `nac promote` / `nac switch` / `nac remove` / `nac rollback` / `nac chat status` 这些顶层命令。
⚠️ 而且**「把某个环境的版本直接发到另一个环境」这个能力本身就不存在** —— 别去找它的命令形式，见下表的注。
写错的后果可能是静默的：`nac chat status` 会被解析成「对一个叫 `status` 的环境发起对话」。
权威清单永远是 `nac --help`（当前 24 个顶层命令，逐条见 `references/cli-reference.md`）。

| 想做的事 | 命令 |
|---|---|
| 打包 + 建版本 + 上传 + 部署 + 等终态 | `nac deploy <env>` |
| **回滚**（切回**本环境**的一个老版本，不重新打包） | `nac deploy <env> --promote <version_tag>` |
| 直接部署一个已存在的版本 id | `nac versions deploy <version_id> <env>` |
| 本地内环开发（1 小时临时泳道） | `nac dev`（⚠️ 0.4.x 实测问题不少，**日常推荐 §2.6 的 `environments create` + `deploy` 循环**） |
| 清掉残留的临时环境 | `nac clean --dry-run` → `nac clean`（`--all` 扫所有项目） |
| 看版本列表 / 状态 | `nac versions list --json`（`status`：`pending`/`deploying`/`active`/`failed`/`superseded`） |
| 启用 / 停用版本 | `nac versions activate <vid>` / `deactivate <vid>`（已绑环境时要 `--confirm`） |
| **无损重启**当前版本（不换版本、不重新打包） | `nac versions redeploy <vid>`（⚠️ 对旧版本重新部署**不会换运行时镜像**，见 §4「修了运行时问题但老版本还在」） |
| 看 / 改某版本的副本上下限 | `nac versions scaling <vid>` / `nac versions scaling <vid> --min 1 --max 5` |
| 直接把副本数拨到 N | `nac versions scale <vid> <N>` |
| 看环境与当前指向 | `nac status --json` ⚠️、`nac environments list`、`nac environments releases <env>` |
| 建临时环境 / 续期 / 删 | `nac environments create --name lab --ttl 1h` / `extend <env> --ttl 2h` / `delete <env>` |
| 运行日志 / 版本启动日志 | `nac logs <env>` / `nac versions logs <version_id>` |
| trace | `nac traces --last 1h` / `nac trace <id>` / `nac trace <id> --export -o t.json` |
| 冒烟 / 用例套件 / 压测 | `nac smoke <env>` / `nac test <env>` / `nac bench <env>` |
| 打任何后台接口（逃生舱） | `nac api GET/PUT/POST/DELETE <path> --body '<json>'` |

⚠️⚠️ **上面这些「拿已有版本去部署」的写法都只在本环境内成立。**
平台**没有**跨环境通路：要把预发验过的东西发到生产，必须**把制品重新上传部署一次**
（`nac deploy production`），在生产环境下产生一条新的 Version。

⚠️ **`nac status` 的表格输出只有 Environment / Type / Expires At / Created 四列，看不到「指向哪个版本」** ——
要看部署必须 `--json` 读 `current_release_id`。

⚠️ **`nac logs` / `smoke` / `test` / `bench` / `chat` 省略环境名时，都会去打一个字面叫 `default`
的环境**（多半不存在，于是你拿到一个跟真实环境无关的 404）。**永远显式写环境名。**

### 2.2 标准循环：改 → 发 → **确认真的生效**

第三步不能省，它是全篇最硬的判据。

```bash
# ① 部署（stderr 会依次打印这些路标）
nac deploy staging
#   Packing artifact...
#     <N> bytes                     ← 这就是你的包大小，对照 100 MiB 上限用它
#   Creating version: v20260810-101530   ← tag = v<UTC yyyymmdd>-<HHMMSS>，自动生成
#   Uploading artifact...
#   Deploying <tag> to staging...
#   Waiting for version <id>...
#   Deployment status: <状态>       ← 每变一次打一行，中间穿插最近 30 秒的部署日志
# 默认最多等 10 分钟（--timeout 20m 可调；--no-wait 提交完就返回；--yes 跳过本地确认）

# ② 冒烟：真发一轮对话。退出码有区分度，可直接当 CI 卡口
nac --token "$AK:$SK" smoke staging --json
#   0 = 通过 / 1 = 失败 / 2 = 超时

# ③ ⭐ 确认这一轮跑的确实是新版本
curl -sS -u "$AK:$SK" "$BASE/agent-api/sessions/$SID/runs" | jq '.runs[0].versionId'
```

**`/runs` 里的 `versionId` 是「我改的代码到底上去没有」的终极判据**——它是这一轮实际执行的版本，
比界面上任何「部署成功」都可靠。和 `nac versions list` 里刚建的那个版本对一下即可。

`nac deploy` 的失败/超时会**自动打印最近 10 分钟的部署日志**再退出，退出信息形如：

```
Deployment failed for version <vid>: status=failed, message=<...>
Deployment timed out after 10m waiting for version <vid> (last status: deploying)
```

### 2.3 推荐的发布节奏

1. **内环**：建一个固定的开发环境，改完 `nac deploy dev --yes` → 用 `nac chat dev -m … --json` 验证，聊天窗口用控制台试验场（做法见 §2.6）。`nac dev` 在 0.4.x 上有几处坑（同节），不作为默认推荐。
2. **预发**：`nac deploy staging` → `nac smoke staging` →（有套件就）`nac test staging --bail` →
   看 `nac traces --last 1h` 的错误与延迟。
3. **上线**：把预发验过的那份制品**重新上传部署**到生产 —— `nac deploy production`。
   ⚠️ **没有跨环境晋升**，这一步是真的要再传一次。
   ⇒ 风险也随之变了：不再是「两次打包结果不一致」，而是**「传上去的不是你验过的那个包」**。
   **确认你部署的就是预发验过的那份制品**，别用工作区里改动过的代码重打。
4. **回滚**：`nac deploy <env> --promote <上一个稳定 tag>` —— 切回**本环境**的老版本，
   几秒完成，不需要重新打包。
5. **别动线上不确定的东西**：只想让当前版本重启一遍用 `nac versions redeploy <vid>`（无损），
   不要用「删了再部一次」。

> **部署失败不伤线上**：新版本起不来时环境指针**不切换**，老版本继续服务，新版本标 `failed`。
> ⇒ 看到 403 `VERSION_NOT_ACTIVE` 时先分清是「新版本没起来」还是「线上真挂了」。

### 2.4 受保护环境：`nac deploy` 会 400，命令行没有开关能绕

```
Operating on environment '<name>' requires explicit confirmation. Set "confirm": true in request body.
```

- `nac deploy`（含 `--promote`）**不发** `confirm` 字段；`--yes` 也不是它（`--yes` 只省掉本地那句 y/N 提示）。
- **唯一绕法**是自己发一次带 `confirm` 的请求，语义完全等价（都是把环境指针切到已有版本）：

```bash
nac api PUT "/api/projects/$PID/versions/$VID/deploy" \
  --body '{"environment":"production","confirm":true}'
```

- ⚠️ **保护是每个环境自己的开关，跟名字无关**：叫 `production` 的不会因为这个名字就自动受保护，叫 `my-env` 的也可能被开了保护。**别靠名字猜，去查。**
  判据：控制台环境列表里那个琥珀色 `protected` 徽章，或
  `nac api GET "/api/projects/$PID/environments"` 里的 `requires_confirmation`。
- **把这条命令先在 staging 上跑通再写进发布脚本**，别等回滚时才发现它不通。

### 2.5 不可逆 / 有守卫的操作

| 操作 | 守卫 | 你会看到什么 |
|---|---|---|
| **临时环境到期** | ❌ **无任何守卫** | 到点自动停服务 + 下线 + 软删，**无确认无宽限**。症状是「代码没动过突然全部 403/404」。判据 `nac environments list --json` 有没有 `expires_at`，或 `nac status` 看 `Type`=`ephemeral`。**生产不要用临时环境** |
| **SK 泄露 / 丢失** | 可找回 | SK 可随时用 `nac keys secret <id>` 取回；泄露了就 revoke 再建一把 |
| **隐私域 passphrase 忘记** | ❌ 不可找回 | 平台**不存储**它。忘了之后 agent 照常运行、加密写入不受影响，但**永久失去「解锁查看 / 关闭隐私域 / 轮换口令」** |
| **`stop` 传 `force: true`** | ❌ 半截内容不落盘 | 已流出的思考、半截回复、半截工具参数全部找不回。默认 `false`（优雅停止），**不要改** |
| 删项目 | ✅ 要手打项目名；有 active 版本时 409 | 409 消息会直接告诉你先停用哪几个版本 |
| 删环境 | ✅ 有活跃部署时 409 | 先下线当前部署 |
| 删版本 | ✅ active 时 400、有运行实例时 409 | **是软删**，制品对象不清理（多个环境可能共享同一份）⇒「删了省空间」这个预期是错的 |
| 对受保护环境做写操作 | ✅ 必须 `confirm: true` | 见 §2.4 |
| 同一环境并发部署 | ✅ 409 | `environment <id> already has deploy operation <op-id> in progress`。串行化你的流水线；执行方异常中断时该占用约 15 分钟后自动失效 |

### 2.6 推荐的部署-验证循环，以及 `nac dev` 的坑（0.4.x 实测）

**结论：建一个固定的开发环境，之后反复 `nac deploy dev --yes`，每次十几秒到半分钟；别靠 `nac dev --watch`。**

```bash
# 一次性：建开发环境（持久环境，不会 1 小时后消失）
nac environments create --name dev

# 每次改完（提示词 / 配置 / 工具 / skill 都要重新部署才生效）
nac deploy dev --yes

# 冒烟：真发一轮对话（对话命令用项目 API 密钥，只写在这一条前面）
NAC_TOKEN="ak_xxx:sk_xxx" nac smoke dev --json

# 对话：一律加 --json，读 .content
NAC_TOKEN="ak_xxx:sk_xxx" nac chat dev -m "你好" --json | jq -r '.content'
# 工具调用在 .messages[].tool_calls（没有顶层 tool_calls，也没有 trace_id）
# 想查链路：拿返回里的 session_id，去 `nac traces` 输出的 Session 列里对

# 看 trace：每次模型调用、工具入参与返回都在里面
nac traces --last 1h
nac trace <trace_id> --export --json -o t.json

# 看运行日志：alpha 实测服务端没按 --level / --grep 过滤（CLI 有传；其他平台未验证），用 --json 后自己滤
nac logs dev --json | jq -r '.response.logs' | grep -v '"DEBUG"'
```

几条 0.4.x 实测的细节：

- **0.4.x 的交互模式（`nac chat <env>` 不带 `-m`）加不加 `--json` 都会崩，不要用**（工具结果按 80 字节截断，落在汉字中间就 panic）。对话一律 `nac chat <env> -m "…" --json`（或 `--stdin --json`），读 `.content`；要聊天窗口就用控制台试验场。
- 写进 bashrc 的 `NAC_BASE_URL` 会盖掉 `nac.json` 的 `base_url`。
- `nac deploy` 过程中出现 `warning: unable to fetch deploy logs (404)` 可以忽略。
- `nac deploy` 打的版本标签是时间戳，**不读项目里的 `VERSION` 文件**。
- 制品相关的小事：自定义工具要返回 `{"content": ...}`；声明了 skills 后 `LoadSkill` 自动注入；
  提示词里「skills 根目录位于 /home/user/.skills/」这句照抄（控制台构建检查按原句找，命令行部署不强制）；
  需要固定输出格式时在 skill 里写「模板前后不要加别的话」；不写 `llm_config.model` 就跟随项目默认模型。

**`nac dev` 的实际问题（0.4.3 / 0.4.4）**：

| 现象 | 说明 |
|---|---|
| 一直占着终端 | 前台常驻，要另开终端干别的 |
| `--watch` 不生效 | 0.4.x 里 `--watch` 和 `--chat` 没有实现（参数被忽略），在任何机器上都不会自动重新部署，也不会进对话窗口；改提示词 / 配置 / 工具都**不会**重新部署 |
| `--chat` 不进对话窗口 | 同上，没有实现；聊天用控制台试验场，或 `nac chat -m … --json` |
| Ctrl+C 清理临时环境失败（409） | 报「有 active release」；`nac clean` 同样 409 |

**手动清理 `nac dev` 留下的临时环境**（先 `nac clean --dry-run` 看看）：

```bash
nac versions list --json | jq -r '.[] | select(.status=="active") | [.id,.tag] | @tsv'   # 找名字带 __dev__- 的 active 版本
nac versions deactivate <version_id> --confirm
nac environments delete <临时环境名>
```

（`jq` 字段名以你本机 `nac versions list --json` 的实际输出为准；没有 jq 就肉眼找 `__dev__-` 开头、状态 active 的那条。）

---

## 3. 排障：固定次序（照走，别跳）

### 第 0 步：先把问题分成三类，分错类会在错误的证据面上耗掉几小时

| 类型 | 表现 | 先去哪 |
|---|---|---|
| **A. 根本没跑起来** | HTTP 4xx/5xx，一条事件都没有 | 状态码 + `message` → **日志** |
| **B. 跑起来了但结果不对** | 有回复，内容 / 行为不符预期 | **trace** → `/actions` |
| **C. 跑到一半断了** | 流中断、卡住、超时 | 先回查 **`/runs`** 的终态 |

### 第 1 步：把三个锚点存下来（**事后补不回来**）

```bash
curl -i -X POST "$BASE/agent-api/chat" -u "$AK:$SK" -d '...' 2>&1 | grep -iE 'server-timing|x-nac-|retry-after'
```

- **trace id** ← 响应头 `server-timing: traceparent;desc="00-<32位十六进制>-<16位>-01"` 中间那 32 位。
  **成功的响应也有**，可直接 `nac trace <id>`，与 `/runs`、`/actions` 里的 `traceId` 是同一个值。
- **`request_id`** ← 只在**错误响应体**里（`error.request_id`，`req_` 开头 26 位），每次错误都是新的。
  **你自己反查不了它**，它的唯一用途是报障（§5）。
- **`session_id`** ← 你发起对话时用的那个。

### 第 1.5 步：经前置网关调用时，先问「这个请求到没到 NAC」

看响应：有 `server-timing` 头或 `req_…` 或 NAC 信封 = 到了 NAC；没有 `request_id`、没有 `server-timing` = 请求没到平台，是前置网关自己拒绝的，先找网关方，不要在 NAC 里查。

### 第 2 步：看 HTTP 状态码 + `message` 原文，**不要看 `code`**

`code` 在两处会误导（详见 `references/error-codes.md`）：部分 4xx（含请求体校验失败、请求体超限）
的 `code` 恒填 `INTERNAL_SERVER_ERROR`；部分 403 的 `code` 恒填 `VERSION_NOT_ACTIVE`。
`code` 只适合做机读粗分类。

### 第 3 步：确认「到底哪个版本在服务这次请求」

```bash
curl -s "$BASE/agent-api/sessions/$SID/runs" -u "$AK:$SK" | jq '.runs[0]'
```

看 `versionId`。**一步排除掉「改了没生效」这一整类问题。**

### 第 4 步：看这一轮 run 的终态

同一个响应里的 `status`（`submitted`/`working`/`input-required`/`completed`/`failed`/`canceled`）
和 `error.message`。还停在 `working` 说明没跑完 —— **客户端断开不会停止 agent**，要停必须显式
`POST /agent-api/stop`。

### 第 5 步：按阶段取证

| 阶段 | 用什么 | 需要 PAT？ |
|---|---|---|
| 部署 / 启动失败 | `nac versions logs <vid>`；**崩溃前一次**只能 `nac api GET ".../versions/$VID/logs?previous=true"` | 是 |
| 运行期报错、你自己的 `print` | `nac logs <env> --json \| jq -r '.response.logs'` | 是 |
| agent 走了哪几步 | `GET /agent-api/sessions/{sid}/actions` | 否（AK/SK 可用） |
| 单步耗时、模型入参出参、错误详情 | `nac trace <trace_id>` 或控制台 Observe 面板 | 是 |
| 界面能跑 API 跑不通 | Playground 的 **`API`** 按钮导出 curl/Python/JS，逐字段对比 | 否 |

### 第 6 步：走完 §5.3 的三条排除，再决定要不要报障

### 证据面总表（每一项的详细读法在 `references/evidence-sources.md`）

| 证据 | 怎么拿 | 里面有什么 | AK/SK 够吗 |
|---|---|---|---|
| 响应头 | `curl -i` | trace id、是否冷启动、限流退避秒数 | ✅ |
| 错误信封 | 任何 4xx/5xx 响应体 | `type` / `code` / `message` / `request_id` | ✅ |
| `/runs` | `GET /agent-api/sessions/{sid}/runs` | `versionId` / `status` / `error.message` / `traceId` / `agentName` / `source` / `variables` | ✅ |
| `/actions` | `GET /agent-api/sessions/{sid}/actions` | 逐动作回放、工具调用、子 agent 展开、`run_end.extra` | ✅ |
| SSE 事件流 | `POST /agent-api/chat`（流式）或 `GET .../events` | 实时 token、工具事件、终态帧 | ✅ |
| 运行日志 | `nac logs <env>` | 你的 `print`、启动 WARNING | ❌ 需 PAT |
| 版本启动日志 | `nac versions logs <vid>`；崩溃前一次走 `?previous=true` | 容器启动过程、崩溃现场 | ❌ 需 PAT |
| trace | `nac traces` / `nac trace <id>` / Observe 面板 | span 树、模型入参出参、耗时、token、`statusMessage` | ❌ 需 PAT |
| `nac smoke` | `nac smoke <env>` | 端到端通不通 + 退出码 | ✅（用 `--token ak:sk`） |
| Playground `API` 按钮 | 控制台 Playground，回复旁边的代码图标 | 能跑通的 curl / Python / JS 原文 | ✅ |

> ⚠️ **`/runs`、`/actions`、`/events` 官方标注为 Experimental**：契约可能在小版本内调整。
> **排障用它们没问题（本 skill 推荐的正是这个用法）；不要写死进生产集成**——
> 生产对话流走 `POST /agent-api/chat` 的内嵌 SSE。

---

## 4. 症状速查（完整版 34 条见 `references/symptom-index.md`；表中从「503 熔断」起的 6 行为 2026-11 新增，已同步进完整版「2026-11 新增症状」一节）

| 你会怎么说 | 第一手证据 | 一句判据 |
|---|---|---|
| 「第一次接入：会话建成功了，一发对话就 404/403」 | `nac versions list --json` 有没有 `active`；`nac status --json` 看 `current_release_id` | **建会话不校验版本、总会成功**，所以错误落在下一步。真因是环境上还没有跑起来的版本 |
| 「agent 没有回复 / 回复是空的」 | 状态码 → `/runs` 的 `status`+`agentName` → 日志 | 日志里有 `Agent config not found` = 清单里声明的 agent 配置**路径写错**，平台只跳过不报错 |
| 「部署完了，行为还是老的」 | `/runs` 的 `versionId` | 不是新版本 → 路由没切；是新版本 → 问题在别处。**别用界面的「部署成功」当判据** |
| 「部署显示成功，第一次对话就报缺依赖」 | `nac logs <env> --json \| jq -r '.response.logs' \| grep 'setup command failed'` | 清单 `setup` 失败**不会让部署失败**，只留一行 WARNING |
| 「本地好好的，传上去就报错 / 文件不见了」 | skills 看 `ls -la /home/user/.skills/`；其它文件看启动日志 | **符号链接不入包**（静默）；**`.env` 被固定排除**。⚠️ 别拿本地手搓 `tar -tf` 做对照 |
| 「403 说版本没激活，可我明明激活了」 | `nac versions list --json` 看是不是 `failed` → `?previous=true` 崩溃日志 | **多半是部署失败了**，错误码描述的是结果不是原因 |
| 「偶尔失败，重试就好」 | 看是 409/`LOCK_CONFLICT` 还是 429 还是 `TRANSPORT_ERROR` | **偶发 = 自己并发；短时间成片（几十上百次）几乎一定是上游故障 → 报障** |
| 「第一次调用特别慢」 | `curl -i` 看 `x-nac-cold-start: true` | 有这个头 = 冷启动，**不是你的 agent 慢**。首字节超时放宽到 3 分钟以上 |
| 「超时了」 | 先分清流式 / 非流式 | `stream:false` 有约 300 秒硬超时且**返回 500 不是 504**；`stream:true` 没有整体超时。改流式再打一次就能证伪 |
| 「报错不知道是前置网关、NAC 还是模型的」 | 先存原始响应；看有没有 `server-timing` / `req_`；`RUN_ERROR` 里 `Error code: <N>` 的 `<N>` | 没有 `request_id` / `server-timing` = 没到平台，是前置网关自己拒绝的；模型 4xx 是**我们**的请求问题；`Connection error.` / `UPSTREAM_REQUEST_FAILED` 不归属 |
| 「返回 429」 | 响应头 `Retry-After` + `x-nac-capacity-trace-id` | 容量拒绝，**这一轮没被执行**。按 `Retry-After` 退避并复用同一 `session_id`；想控制排队用请求头 `X-Max-Queue-Wait: <秒>` |
| 「401/403 但凭据我确认是对的」 | `message` 原文 | 见 §1 三条边界 + `references/error-codes.md` 的原文速查表 |
| 「`404 session not found`，可它明明存在」 | 换**项目 AK/SK** 再请求一次 | 读得到 = 凭据类型口径差异（PAT 多校验一层「发起人是我」）；仍读不到 = 用错项目的 AK/SK |
| 「agent 说执行了代码但结果不对 / 说文件里没这内容」 | trace 里看那次工具调用的返回值 | 出现 `... [N characters omitted] ...` + `(Full output: <目录>/stdout.txt)` 就确诊：shell 输出被截断（合计超约 1 万字符 → 各留头 5000 + 尾 5000） |
| 「连不上我们自己的服务」 | Playground 里跑三条 `curl` 自测 | **私网 IP 与 IPv6 一律不通，这是设计**；公网通不通取决于部署方有没有开出网白名单 |
| 「文件写进去了，下次对话就没了」 | `echo hi > /home/user/x && echo hi > /var/log/x` → 闲置 5 分钟 → 再 `cat` | 只有少数路径跨暂停恢复存活；**`apt-get install` 的包活不过来，`pip install --user` / `npm -g` 能** |
| 「代码一个字没改，突然全部 403/404」 | `nac environments list --json` 看 `expires_at` | 第一嫌疑：**临时环境到期被自动回收**，无确认无宽限 |
| 「界面里能跑，我自己调 API 就不行」 | Playground 的 `API` 按钮导出脚本逐字段对比 | 重点看路由字段：`version_tag` 优先级**高于** `environment`，两个都传时 `environment` 被**静默忽略**；导出脚本**不含** `agent` 字段（多 agent 制品照抄会 400） |
| 「界面永远停在『生成中』」 | 数一下你的解析器认几个终态帧 | 终态帧有 **5 个**：`RUN_FINISHED` / `RUN_ERROR` / **`RUN_STOPPED`** / `LOCK_CONFLICT` / `TRANSPORT_ERROR`。漏掉 `RUN_STOPPED` 就永远不退出循环 |
| 「聊到一半无缘无故断线重连」 | `curl -N` 肉眼看流里有没有 `: heartbeat` | 以 `:` 开头的是保活注释行，**必须忽略**。标准 SSE 客户端不会踩，手搓 `split('\n')` 的会 |
| 「我指定了模型，好像没生效」 | 先分清「谁指定的」：① chat 请求体里的 `override_llm_configs` 覆盖（旧字段名 `llm`，开了去别名开关的环境带旧名会被 400 拒绝） → 流里找 `MODEL_FALLBACK`；② `agent.yaml` 的 `model` 写错 → 流里**没有**该事件，看 runtime 日志与 `LLM_PROVIDER_UNROUTABLE` | 见 `references/symptom-index.md`「模型没生效」一节：①覆盖不可用 = 回落默认并发 `MODEL_FALLBACK`（解析环节失败则 422 `LLM_OVERRIDE_UNAVAILABLE`）；②制品 `model` 无对应卡片 = 不发事件，按运行时分：Rust 运行时有可见卡且已注入 `LLM_MODEL` 才回落（只换 model/api_type/连接，yaml 写了的采样参数保留）；默认的 Python 运行时部署期不回落，通常每次 chat 422 `LLM_PROVIDER_UNROUTABLE` |
| 「模型报 503 UPSTREAM_5XX_CIRCUIT_OPEN」 | 响应 body 里的 code；再翻熔断**之前**那几次请求的原文 | 同一模型**连续 5 次 5xx 后，平台暂停往它发请求 10 秒**，期间直接返回 503（`retry_after_secs` 是还要等几秒），10 秒后放行，模型还坏就再熔断（阈值固定、不能调）。**熔断只是结果，根因在模型服务**：去看前面那 5 次 5xx 的原文，找模型服务方；调用方按 `retry_after_secs` 等一下重试即可。|
| 「工具好像没生效 / 智能体说没有这个工具（MCP）」 | 运行时日志里搜连接超时（如 `connect_tcp` / `timeout`）：`nac logs <env> --json \| jq -r '.response.logs' \| grep -iE 'mcp\|connect_tcp\|timeout'` | MCP 由运行时直接连，**不受沙箱出网规则管**；连不上时**这个 MCP 的工具一个都不加载**，对话照常进行，表现是「没这个工具」而不是工具报错。内网 MCP 要请网络管理员放通「平台集群 → MCP 的 IP 和端口」，放通后新开对话就会重连。日志搜 `unavailable for this run` 和 `connect_tcp` |
| 「工具刚跑完，模型下一步就 400」 | trace 里看那次工具调用返回有多大；模型调用的错误原文 | 工具**一次返回太大**，塞进上下文后模型直接 400。让工具只返回摘要 / 分页，大内容落文件让智能体按需读。若用了平台的「长工具输出」中间件，豁免工具的参数名是 **`bypass_tool_names`**（写成 `bypass_tools` 会在加载时报 `unexpected keyword argument`，智能体起不来）；带参数不符合官方制品规范白名单（见 nexau-artifact-builder 的 artifact-spec-checklist §9.3），默认写 `params: {}`。另外：工具返回太大 400 之后，**同一会话每条都会 400，要新开会话** |
| 「经门户 / 网关上传制品或 Skill 失败，405 或一个拦截页」 | 响应是不是 HTML 拦截页、有没有 NAC 的 `request_id` / `server-timing` | **请求没到平台，被前面的安全设备拦了**（没有 NAC 的响应头 = 不是平台的错）。只有平台前面挂了第三方安全网关（WAF）时才会发生，直接用平台页面上传不受影响。「上传 Skill zip」是**浏览器先解压再逐个文件上传**，每个文件内容照样会被检查。做法：把整个智能体打成 zip 走「上传新版本」（整包压缩，网关看不到文字），或直接在平台页面上传；`node_modules` 别带；根治请网关运维加白名单，并把拦截页原文发给他们 |
| 「HTML 预览是空白 / 图表出不来」 | 浏览器开发者工具 Network 看外部脚本有没有加载失败 | HTML 预览里的资源是**用户自己的浏览器**去加载的；用户那边访问不了外部 CDN（内网 / 断网）就空白。要离线可用：把库**内联**进 HTML（库由生成脚本写进 HTML，不要让模型自己输出这 1MB），并且别让智能体把生成的大 HTML 再读回上下文（会撑爆，见上一条）。另：智能体用脚本在沙箱里生成的 HTML 不会自动出预览卡，要到沙箱文件里打开，那里默认是安全模式，点「允许脚本」图表才会渲染 |
| 「修了运行时的问题，但老版本还是老样子」 | `nac versions list --json` 看跑的是哪个版本 | 对**旧版本「重新部署」不会换运行时镜像**（版本创建时就冻结了运行时）。运行时侧的修复**要发一个新版本才生效**：重新 `nac deploy <env>` |
| 「trace 里是 `🔒 [encrypted]` / 查 trace 报 403」 | 看是哪一种 | `🔒 [encrypted]` = 项目开了隐私域，Playground 输口令解锁（**口令不可找回**）；`403 Langfuse not configured` = 这个项目没配 trace 存储，**不是权限问题**，找管理员开 |

---

## 5. 报障

### 5.1 这些你自己解决不了，别耗时间

- **`500` / `503`** —— 见到就报，没有自查空间。
- **持续 `429` 而你的并发并不高** —— 平台总容量不是你能调的（你能调的只有自己版本的副本上下限）。
- **`TRANSPORT_ERROR` 的 message 里裹着 HTML 或 `502 Bad Gateway`**，或**短时间内成片的
  `LOCK_CONFLICT`（几十上百次）** —— 上游模型链路抖动，改代码没用。
- **部署起不来，而 `?previous=true` 的崩溃日志里没有你自己的报错**（日志为空或只有启动脚本输出）；
  或**部署进度卡住十几分钟不动**。
- **需要开通出网白名单 / trace 存储 / 提高平台侧容量** —— 都要管理员审批或后台配置。

### 5.2 报障时提供（按价值排序，前三条能省掉大量来回）

| # | 提供什么 | 怎么拿 |
|---|---|---|
| 1 | **`request_id`** | 出问题那次**错误响应**体里的 `error.request_id`（`req_` + 26 位）。⚠️ 只有错误响应才有、每次都是新的 —— 要贴**出问题那一次的** |
| 2 | **trace id** | 三选一：响应头 `server-timing` 里 `00-` 后面那 32 位；`/runs` 里对应 run 的 `traceId`；429 时的 `x-nac-capacity-trace-id` |
| 3 | **`session_id` + 出问题的大致时间（含时区）** | 你发起对话时用的那个 session id |
| 4 | **项目 id + 环境名 + `versionId`** | 前两个 `nac status`；`versionId` 从 `/runs` 拿，比「我部署的那个版本」可靠得多 |
| 5 | **完整错误响应体原文** | 别只说「报 500 了」，`type`/`code`/`message` 都要。SSE 场景贴**最后几条事件原文**，尤其终态那条 |
| 6 | **能否稳定复现 + 复现步骤 + 什么时候开始的** | 偶发就给频率（「20 次里 3 次」远比「偶尔」有用）；顺带说最近改过什么（换模型、加依赖、调并发、改路由） |

### 5.3 报障前先自己排除这三条

1. 换一个**新 `session_id`** 重试 —— 还错说明与会话状态无关。
2. 换**项目 AK/SK**（而不是 PAT）重试一次 —— 排除 §4 那个 `404 session not found` 陷阱。
3. 拉一次 **`?previous=true` 的崩溃日志** —— 是不是自己代码报的错，一眼可辨。

> **错误信息是被刻意压平过的。** 像 `Failed to start Agent Runtime` 这类文案不含根因。
> 根因在三个地方之一：`?previous=true` 的崩溃日志、trace 里 `level = ERROR` 那个 span 的
> `statusMessage`、`/actions` 里 `run_end` 的 `extra.reason`。

---

## 6. ⚠️ 会骗你的判据（每条都「不报错、结果看着正常」）

按踩到的频率排。**这一节的价值在于：它们全都不会以报错的形式提醒你。**

1. **`GET /agent-api/chat/health` 是静态返回** `{"status":"ok"}`，不检查运行实例、不检查部署。
   **它绿了什么都不能证明。** 验证部署可用只有 `nac smoke`。
2. **界面 / CLI 的「部署成功」不等于生效** —— 部署是异步的，命令返回只代表任务已提交。
   判据永远是 `/runs` 的 `versionId`。
3. **`nac logs` 的 `--last` / `--level` / `--grep` 在 alpha 平台实测服务端没过滤**（CLI 会把 last/level/grep 都传给服务端，别的平台版本没验证）。
   自证：`nac logs <env> --level error` 与 `nac logs <env>` 输出**逐字相同**。
   替代：`nac logs <env> --json | jq -r '.response.logs' | grep …`，或 `nac api` 加 `?trace_id=` / `?tail=2000`。
4. **`nexau.json` 的 `setup` 失败不会让部署失败** —— 只写一行 `WARNING: setup command failed:` 就继续。
   「部署绿了」和「依赖装好了」是解耦的。
5. **错误信封的 `code` 字段不可信**（见 §3 第 2 步）。
6. **SSE 流干净地关闭 ≠ 跑完了** —— 服务端在某些异常下直接关流、不发任何错误帧。
   判完成只能靠 5 个终态帧；没收到就回查 `/runs`，**不要直接重发 `/chat`**（会撞 409）。
7. **`/actions` 的 `limit` 传超过 500 不报错、静默截到 500** —— 别据此断定「只有 500 条」。
8. **`/actions` 默认只返回顶层 run**，子 agent 的动作要传 `parent_run_id` 才看得到（一次下钻一层）。
   不传就看不到，很容易误判成「子 agent 根本没跑」。
9. **`/runs` 的 `variables` 里敏感值被打码成 `***REDACTED***`，且是按键名子串匹配**，会误伤
   `tokens_per_minute` 这类普通业务字段。⇒ **看不到值 ≠ 没传成功；想确认传没传，看键在不在。**
10. **`/runs` 的 `error` 字段缺席 ≠ 没出错** —— 失败原因是三级回落：
    `/runs.error.message` → `/actions` 里 `run_end.extra.reason` → trace 里 `ERROR` span 的 `statusMessage`。
11. **`nac trace --export` 上游中途出错时返回 502 但响应体仍带已拉到的部分**，CLI 按成功处理、
    只在 stderr 提示 `⚠ upstream error after <N> observations` —— **脚本里只看退出码会误判成成功**。
12. **`/actions` 与 `/runs` 的 `status` 是两套词表**（前者 `in_progress`/`ok`/`succeeded`/`failed`/
    `error`/`cancelled`…，后者六值 A2A 词表）。判终态以 `/runs` 为准，别混着断言。
13. **`nac deploy --dry-run` 不会真打包**，所以看不到那行 `<N> bytes`。想知道包多大只能真跑一次。
14. **缩到 0 或还没起来时 `nac logs` 返回 503 / `nac versions logs` 返回 404** ——
    **那不代表服务坏了**，先发一次对话把它唤醒再看。
15. **`POST /agent-api/stop` 返回 `{"status":"noop"}` 不是失败** —— 意思是当前没有正在跑的 run，
    没什么可停，这是成功语义。
16. **0.4.x 交互模式的 `nac chat`（不带 `-m`）加不加 `--json` 都会 panic**（工具结果按字节截断）：崩的不是你的 agent，是 CLI 自己的输出截断。对话一律 `-m "…" --json`（或 `--stdin --json`）。
17. **`nac dev` 看似在运行 ≠ 在监听**：0.4.x 里 `--watch` / `--chat` 没有实现（参数被忽略），改了东西不会重新部署，别拿它的「运行中」当「已更新」。
18. **`nac logs` 过滤参数无效的补充**：想去掉 DEBUG 噪音用 `nac logs <env> --json | jq -r '.response.logs' | grep -v '"DEBUG"'`。

---

## 7. 平台限制：一页速查（数值与自测法见 `references/platform-limits.md`）

> ⚠️ 带「约」字的都是**部署级默认值**，私有化部署可能不同。**当量级用，别写死进代码**，
> 每条在 references 里都给了你自己能跑的判据。

| 域 | 关键上限 | 撞到时 |
|---|---|---|
| 制品包 | **100 MiB**（不可调，且 `nac deploy` 打的是**未压缩** tar） | 413 + `Agent Artifact exceeds the 100MB compressed archive size limit…` |
| `/agent-api/chat` 请求体 | 100 MiB | 413（多张 base64 图片最容易撞） |
| 非流式 `stream:false` | 约 300 秒硬超时 | **500，不是 504** |
| 流式 `stream:true` | 无整体超时 | — |
| 同一 session 并发 | 只允许一个 run | 409 `SESSION_BUSY` / SSE `LOCK_CONFLICT`（只读订阅 `/events` **不占**这个名额） |
| 容量 | 429 + `Retry-After` + `x-nac-capacity-trace-id` | 429 之前有一层排队（默认约 30 秒、上限约 60 秒），请求头 `X-Max-Queue-Wait: <秒>` 可覆盖 |
| 沙箱闲置 | 约 5 分钟自动暂停 | 下次对话第一个工具调用明显变慢（数秒） |
| 沙箱持久路径 | 只有少数目录跨暂停恢复存活（默认 `/home/user`、`/tmp`、`/usr/local`、`/var/cache`、`/opt`） | `apt` 装的包等于没装 |
| 出网 | 只允许公网单播 IPv4；私网段与 IPv6 不通；有 DNS 重绑定防护 | 连内网服务被拒（**设计如此**）；公网是否放行取决于部署方 |
| shell 输出 | 合计超约 1 万字符 → 每路各留头 5000 + 尾 5000 | 有明确标记 `... [N characters omitted] ...`，完整输出落在沙箱文件里 |
| `run_shell_command` | 默认超时 30 分钟（agent 可传更短） | `Timeout: command timed out after 30.0 minutes.` |
| 单次运行 | 默认最多 100 轮、上下文 128k tokens（**这两个你自己能改**） | 回复末尾追加 `[Error: Maximum iteration limit reached.]`（少数收尾路径是 `[Note: Maximum iteration limit reached]`；前面带的是字面 `\n\n` 四个字符，不是换行），run 状态仍是成功 |
| 会话文件上传 | 单文件 100 MiB | 413 `multipart upload exceeds <N> bytes` |
| 环境变量 | key 只能字母/数字/下划线且 ≤255；`LANGFUSE_*` 是保留前缀 | 写入被拒并给出明确提示 |

**你自己能改的**（控制台 项目设置）：Runtime CPU/内存上限、三维拒流阈值（资源上限 tab）；
最小/最大副本、扩缩容阈值、缩零闲置小时（负载均衡 tab，也可 `nac versions scaling`）；
环境变量与模型（运行配置 tab，也可 `nac vars`）；出网白名单**申请**（网络策略 tab，**仅项目 owner 可见**，需管理员审批）。
**你改不了的**：沙箱 CPU/内存/磁盘、沙箱闲置暂停时长、持久路径清单、非流式超时、制品与请求体上限、隔离档位。
