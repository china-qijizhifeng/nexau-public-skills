# 开发与调试循环、常见运行期坑（0.4.x 实测）

> 适用：已经按 SKILL.md 写好制品目录，想在自己的 NAC 环境里「改一下、部署、对话、看 trace」循环迭代。
> 命令细节以独立的 `nac` skill 为准；本文只写实测过的结论和能直接抄的命令。
> 下文示例地址 `https://nac-alpha.xiaobei.top` 只是示例，**换成你自己部署的 NAC 地址**。

## 1. 安装 nac 命令行（0.4.x 实测）

```bash
# macOS / Linux —— 必须用 bash，不能用 sh
curl -fsSL https://download.xiaobei.top/nac-cli/install.sh | bash
# Windows PowerShell（装到 %LOCALAPPDATA%\Programs\nac，自动加 PATH，免管理员）
irm https://download.xiaobei.top/nac-cli/install.ps1 | iex
```

- 脚本里和装完提示写的是 `| sh`，**那是错的**：Ubuntu 上 sh 是 dash，会报 `Illegal option`，装不上。
- 指定版本和安装目录：变量要写在管道后面、`bash` 前面，写在 curl 前面传不进安装脚本：
  `curl -fsSL https://download.xiaobei.top/nac-cli/install.sh | NAC_VERSION=0.4.4 NAC_INSTALL_DIR=$HOME/bin bash`

## 2. 先配地址（最容易漏的一步）

**零配置的 nac 默认连官方正式环境（https://nac.xiaobei.top），不是你的环境。** 所以不配地址就部署，等于在打别的环境。

0.4.x 实测：

| 写法 | 是否生效 |
|---|---|
| 每条命令带 `--base-url https://nac-alpha.xiaobei.top` | 生效 |
| `export NAC_BASE_URL=...` | 生效（推荐，写进 `~/.bashrc` / `~/.zshrc`） |
| `export NORTH_ENV=dev`（= alpha 示例环境） | 生效（优先级低于 `--base-url` / `NAC_BASE_URL`） |
| `nac.json` 里手写 `"base_url": "..."` | 生效，但只在该目录及子目录里生效；会被 `NAC_BASE_URL` / `NORTH_ENV` 盖掉（bashrc 里写了 `NAC_BASE_URL` 后，项目里的 `base_url` 就不起作用） |
| `nac auth login --base-url ...` | **不记地址**，只存令牌 |
| `nac init --base-url ...` | **不会**把地址写进 `nac.json`，要手动加 |
| `~/.nac/config.toml` | 不读（地址优先级：`--base-url`/`NAC_BASE_URL` > `NORTH_ENV` > `nac.json` > 默认正式环境） |

```bash
export NAC_BASE_URL=https://nac-alpha.xiaobei.top   # 换成你自己的地址
```

## 3. 两把钥匙，别混用

| 钥匙 | 长相 | 代表 | 用在哪 |
|---|---|---|---|
| 访问令牌 | `nacp_…` | 你本人 | 管理命令：projects / keys / deploy / versions / logs / traces |
| API 密钥 | `ak_xxx:sk_xxx` | 一个项目 | 只用于对话：chat / smoke / test |

- 访问令牌在控制台个人菜单「访问令牌」里自建，然后 `nac auth login --pat <令牌>`（Linux 存系统密钥环）。
- 新项目自带一把 `default` API 密钥。`nac keys list` 取 id 和 access_key；`nac keys secret <id>` **只返回 secret_key**，要自己拼成 `access_key:secret_key`。
- API 密钥**只写在单条对话命令前面**，不要 export 成全局变量：

```bash
NAC_TOKEN="<access_key>:<secret_key>" nac chat dev -m "你好" --json
```

用错的症状：

- chat / smoke 用了访问令牌 → `400 Missing X-Project-Id header`
- 管理命令被全局的 `NAC_TOKEN=ak:sk` 顶掉 → `401 Unknown error`

## 4. 推荐的开发循环（别用 `nac dev --watch`）

```bash
cd my-agent/                      # 有 nexau.json 的目录
nac environments create --name dev      # 只建一次
nac deploy dev --yes                    # 改完文件就再跑一次，十几秒到半分钟
NAC_TOKEN="<ak>:<sk>" nac chat dev -m "测试问题" --json | jq -r '.content'
```

- 想要一个聊天窗口：用控制台的「试验场」，比命令行舒服。
- 部署时出现 `warning: unable to fetch deploy logs (404)` 可以忽略。
- `nac deploy` 打的版本标签是时间戳，**不读 VERSION 文件**。

### `nac dev` 在 0.4.3 / 0.4.4 的实测问题

- 会一直占着终端。
- `--watch` 和 `--chat` 在 0.4.x 里没有实现（参数被忽略），在任何机器上都不会自动重新部署，也不会进对话窗口。
- Ctrl+C 退出时清理临时环境会 **409**（有 active release），`nac clean` 同样 409。手动清理：

```bash
nac versions list                          # 找 active 的、名字带 __dev__- 的版本
nac versions deactivate <版本id> --confirm
nac environments delete <环境名>
```

所以日常迭代直接用上面的 `environments create` + `deploy` 循环。

## 5. 对话与看日志的坑

- 0.4.x 的交互模式（`nac chat <环境>` 不带 `-m`）加不加 `--json` 都会按 80 字节截断打印工具结果，遇到中文会 panic，**不要用**；对话一律 `nac chat <环境> -m "…" --json`（或 `--stdin --json`），读 `.content`。要聊天窗口就用控制台试验场。
- 工具调用在 `.messages[].tool_calls` 里（没有顶层 `tool_calls`，也没有 `trace_id`）。要查 trace，用返回里的 `session_id` 去 `nac traces` 的 Session 列找。
- 在 alpha 平台实测，服务端没按 `--level` / `--grep` 过滤（CLI 有传；别的平台版本没验证）。稳妥做法是自己过滤：

```bash
nac logs <环境名> --json | jq -r '.response.logs' | grep -v '"DEBUG"'
```

- 看每次模型调用、工具入参和返回：

```bash
nac trace <trace_id> --export --json -o t.json
```

## 6. 制品里的几个确认过的写法

- 自定义工具返回 `{"content": ...}`。
- 声明了 `skills` 后，`LoadSkill` 会自动注入，不要手写。
- systemprompt 里「skills 根目录位于 `/home/user/.skills/`」这句**照抄**。它的真实作用：控制台构建检查按这句原文去找，缺了或改写会判不合规；命令行 `nac deploy` 不强制，所以「命令行能部署、控制台构建报错」多半是这句。
- 想让输出严格按模板：在 skill 里明确写「模板前后不要加别的话」。只写「第一行必须是 X」，模型仍可能先加一句开场白（单样本观察，不是保证）。
- 不写 `llm_config.model` 就跟随项目默认模型。

## 7. 工具一次返回太大 → 模型 400

症状：工具调用成功，下一轮模型调用 400（请求体或上下文超限）。原因：工具把几十万字符的结果整个塞回了对话。⚠️ 一旦发生，同一会话之后每条都会 400，要新开会话。

对策，按优先级：

1. **工具自己限量**：返回「截断后的视图」（前 N 行 / 摘要 / 命中片段），**全量放到证据里**（写进沙箱文件，返回路径），模型需要时再读文件的某一段。
2. **分页**：工具加 `offset` / `limit` 参数，systemprompt 写明「一次最多取 N 条，不够再翻页」。
3. **写文件**：大结果写到沙箱文件，只返回文件路径和行数。
4. **交给子智能体**：让子智能体读大内容，只把结论返回主智能体（见 `mcp-and-subagents.md`）。
5. **中间件兜底**：`LongToolOutputMiddleware` 会截断超长工具输出、全文落盘。它的「豁免工具」参数名是 **`bypass_tool_names`**（某些工具不要截断时填工具名列表），**不是 `bypass_tools`**（写错会在加载时报 `unexpected keyword argument`，智能体起不来）。
   ⚠️ 官方制品规范白名单对它「一个参数都不允许」（见 `artifact-spec-checklist.md` §9.3），所以默认写 `params: {}`；带参数属于有意偏离规范，要自己承担。

## 8. skill 目录不要带 node_modules 或大量第三方源码

- 部署时每个会话都会把 skill 目录拷一份到沙箱，目录越大，起会话越慢、占盘越多。
- 如果你的平台前面有安全网关（WAF），经它上传的文件内容可能被关键词拦截（返回 405 或拦截页，请求没到平台）。第三方源码、压缩过的 js 很容易命中。
- 「上传 Skill zip」是浏览器解压后逐个文件上传，照样被检查；可以把整个智能体打成 zip 走「上传新版本」，或直接在平台页面上传，根治要请网关运维加白名单。
- 做法：skill 里只放你自己写的 SKILL.md、脚本和 references；依赖在 `setup` 里安装，或用沙箱里已有的库；不要提交 `node_modules/`、`venv/`、`.git/`。

## 9. 让智能体生成「离线可打开」的 HTML

- 图表库（如 ECharts）**内联进 HTML**，不要写 `<script src="https://cdn...">`。HTML 预览里的外部资源是**用户浏览器**去加载的，用户网络访问不到就是白屏。
- **别让智能体把生成好的大 HTML 读回来**：一读回就是几十万字符，撑爆上下文（参见第 7 节）。生成后只检查文件存在和大小。
- 智能体用脚本在沙箱里生成的 HTML 不会自动出预览卡，要到沙箱文件里打开；那里默认是安全模式，点「允许脚本」图表才会渲染。把这句写进给用户的使用说明里。
- 图表库应由生成脚本写进 HTML，不要让模型自己输出这 1MB 左右的库。

## 10. MCP 连不上：该 MCP 的工具一个都不加载，智能体只会说「工具不可用」

- 现象：部署成功、对话也正常，但智能体说「没有这个工具」或编一个兜底答案。
- MCP 由运行时直连；连不上时该 MCP 的工具一个都不加载，对话照常，不会让部署失败。
- 内网 MCP 要请网络管理员放通平台集群到 MCP 的 IP 和端口；放通后不用改智能体，新开对话会重新连接。
- 查法：日志搜 `unavailable for this run` 和 `connect_tcp`（超时 / 拒绝连接）。
- 更多细节见 `mcp-and-subagents.md` 第三节。

## 11. 模型连续报错 → 平台熔断，返回 503

同一模型连续 5 次 5xx 后，平台暂停往它发请求 10 秒，期间直接返回 `503`（`retry_after_secs` 是还要等几秒），10 秒后再放行，模型还坏就再熔断。这个阈值固定、不能调。根因在模型服务，把出错时段和模型原始报错发给模型服务方；调用方按 `retry_after_secs` 等一下再重试即可，需要时临时换到另一个可用模型。
