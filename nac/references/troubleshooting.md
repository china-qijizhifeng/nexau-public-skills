# Troubleshooting

## Authentication errors

### Gateway APIs (chat, smoke, bench) rejected
0.4.x with a PAT: 400 `Missing X-Project-Id header` (see next entry). `INVALID_CREDENTIALS` = AK:SK wrong or revoked.
`"Basic authorization with project credentials required"` only appears on older versions or when no credential is sent.
**Cause**: AK:SK wrong or revoked (`INVALID_CREDENTIALS`), or no credential sent. A PAT on chat/smoke gives 400 `Missing X-Project-Id header` in 0.4.x.
**Fix**: Pass `ak_xxx:sk_xxx` per command (`NAC_TOKEN="ak:sk" nac chat <env> -m "…" --json`); re-check with `nac keys list --json`, reveal SK with `nac keys secret <id>`.

### 400 `Missing X-Project-Id header` on chat / smoke (0.4.x 实测)
**Cause**: 对话命令用了访问令牌（nacp_）。
**Fix**: 改用 AK:SK，只写在这一条命令前：`NAC_TOKEN="ak_xxx:sk_xxx" nac chat dev -m "..." --json`。

### 401 on management APIs (projects, versions, deploy, dev ...)
```
"INVALID_CREDENTIALS"  /  401 "Unknown error"
```
**Cause**: Using AK:SK on management API (which needs PAT). 常见原因：shell 里 `NAC_TOKEN` 被设成了 AK:SK
（`nac dev` 会表现为 `Failed to create ephemeral lane: 401`）。
**Fix**: `unset NAC_TOKEN`，管理命令用登录的访问令牌（`nac auth login --pat nacp_...`）；AK:SK 只放单条对话命令前面。

### 不带地址的命令 401，或不确定打到了哪个环境
**Cause**: 零配置时 `nac` 默认连官方正式环境（https://nac.xiaobei.top）。`auth login` 和 `nac init` 都不记地址，`~/.nac/config.toml` 在 0.4.x 也不生效（源码不读它）。写进 shell 配置的 `NAC_BASE_URL` 会盖掉 `nac.json` 里的 `base_url`。
**Fix**: `export NAC_BASE_URL=https://nac-alpha.xiaobei.top`（换成你自己的部署地址，写进 shell 配置），
或每条命令加 `--base-url`，或在项目 `nac.json` 里手写 `base_url`。

### 装完 `nac` 找不到，或安装脚本报 `Illegal option -o pipefail`
**Cause**: 用了 `| sh`（Ubuntu/Debian 上 sh 是 dash）。
**Fix**: `curl -fsSL https://download.xiaobei.top/nac-cli/install.sh | bash`。Windows 用 `irm https://download.xiaobei.top/nac-cli/install.ps1 | iex`。

### `nac chat` panic（含中文工具结果时）
**Cause**: 0.4.x 交互模式（`nac chat <env>` 不带 `-m`）不论加不加 `--json` 都会按 80 字节截断打印工具结果，截在汉字中间就 panic。
**Fix**: 不用交互模式；单轮 `nac chat <env> -m "..." --json`（或 `--stdin --json`），读 `.content`；工具调用在 `.messages[].tool_calls`。工具返回太大导致 400 后同一会话会一直 400，新开会话。

### `nac logs --level error` / `--grep` 没过滤
**Fix**: 在 alpha 平台实测服务端没按这两个参数过滤（CLI 有传，别的平台版本没验证；只返回最近 200 行）；稳妥做法：`nac logs <env> --json | jq -r '.response.logs' | grep -v '"DEBUG"'`。

### `nac dev` 退出时 409，临时环境删不掉
```
409 RESOURCE_CONFLICT: Cannot delete environment while it has an active release
```
**Fix**: 先停掉版本再删环境（`nac clean` 同样 409）：
`nac versions list --json` 找出 active 的 `__dev__-` 版本 → `nac versions deactivate <id> --confirm` → `nac environments delete <环境名>`。
另外 0.4.x 里 `nac dev` 的 `--watch` / `--chat` 没有实现（参数被忽略），不会自动重新部署也不进对话窗口，改完文件直接 `nac deploy <环境> --yes`。

### No authentication found
**Cause**: No token resolved. Common agent trap: `export NAC_TOKEN=...` ran in a
*previous* tool call — most agent shells start each command fresh, so the export
is already gone.
**Fix**: Either log in once (persists to `~/.nac/credentials`, survives later
calls): `nac auth login --pat <token>` — then management commands need no flag.
Or pass it inline on the *same* command: `NAC_TOKEN=<token> nac <cmd>` / `--token <token>`.

## Gateway session errors (chat / smoke / test / bench)

### `503 "Session Manager unavailable"` or `404 "session_id not found ... Create session first"`
```
{"error":{"code":"SERVICE_UNAVAILABLE","message":"Session Manager unavailable"}}
{"error":{"code":"RESOURCE_NOT_FOUND","message":"session_id not found for this project. Create session first via POST /agent-api/sessions."}}
```
**Cause**: The gateway session contract — a session is created via
`POST /agent-api/sessions` and is **scoped to the `distinct_id` that created it**;
`/agent-api/chat` does NOT auto-create sessions, and chatting under a *different*
`distinct_id` than the session's creator returns 503. Old `nac` versions set
`distinct_id == session_id` and never created the session, so every chat failed
even though the web UI worked.
**Fix**: Update `nac` (the `chat`/`smoke`/`test`/`bench` commands now create the
session and use a stable `distinct_id` automatically). When **resuming** a session
created elsewhere (e.g. the web UI under a logged-in user), pass the matching
identity: `nac chat <env> --session <sid> --distinct-id <id>`. Override the
default identity anywhere with `--distinct-id` or `NAC_DISTINCT_ID`.

## TLS errors

### `invalid peer certificate: UnknownIssuer` while `curl` to the same URL works

Something between you and NAC re-signs TLS with its own CA — typically a NAC sandbox / DevBox
behind an egress firewall, or a corporate proxy. `curl` trusts it through `SSL_CERT_FILE`.
`nac` adds the certificates in `SSL_CERT_FILE` **on top of** its built-in public roots, so the
fix is to point that variable at the proxy's CA bundle (in a NAC sandbox it is already set to
`/shared/ca/nfw-ca.crt`). Older `nac` builds ignore `SSL_CERT_FILE`: upgrade. `--insecure` also
gets past it but turns off verification entirely — dev clusters only.

If `SSL_CERT_FILE` points at a missing or unusable file, `nac` prints a warning naming the
variable and the path, then carries on with its built-in roots only. Bundles must hold PEM
`CERTIFICATE` blocks; OpenSSL's `TRUSTED CERTIFICATE` blocks are skipped.

## Common errors

### "project_id required"
**Fix**: Either:
- Run from a directory with `nac.json` (create with `nac init`)
- Pass `--project-id <id>`
- Set `NAC_PROJECT_ID` env var

### VERSION_TAG_NOT_FOUND on chat/smoke
**Cause**: No version deployed to the specified environment.
**Fix**: Specify the correct environment: `nac chat <env-name> -m "hello"`

### "missing field distinct_id" on chat
**Cause**: Old CLI version missing required gateway fields.
**Fix**: Update to latest `nac` version.

### "ttl_seconds must be between 60 and 604800" (400)
**Cause**: TTL outside the allowed range `[60s, 7d]`.
**Fix**: Pick a value within range: `--ttl 60s` (min) up to `--ttl 7d` (max).

### "invalid --ttl value 'xxx': expected number at 0"
**Cause**: humantime can't parse the input. Happens **client-side** before any HTTP call.
**Fix**: Use a humantime literal: `60s`, `5m`, `1h`, `72h`, `7d` (no spaces, lowercase unit).

### "Only environments with TTL can be extended" (409)
**Cause**: `nac environments extend` only works on ephemeral envs. Persistent envs don't expire.
**Fix**: If you genuinely want a TTL, delete and recreate with `--ttl`. Or just don't `extend` it.

### "deploy_status became failed" with `status_message: kubernetes error: ... Pod=Pending`
**Cause**: K8s scheduler can't place the agent runtime pod. Common reasons:
- Cluster resource shortage (no node with enough CPU/memory)
- Image pull failure (registry timeout / missing tag)
- Node selector / taint mismatch
**Fix**: Platform-side issue — contact cluster ops. Check `kubectl describe pod` and
`kubectl get events --sort-by='.lastTimestamp'`. SDK / CLI / your agent code is fine.

### Smoke / chat times out 30~180s on a fresh deploy
**Cause**: System default `system_llm_config` endpoint is hung or has no channel.
**Fix**: Switch the agent to a working model — edit agent.yaml `llm_config.model`
(`provider/model_name` full key) and redeploy; see
[workflows.md](workflows.md#switch-the-model-per-agent--project-default).
Quick check: `nac llm show <pid> --json` — if the default model looks suspicious, run
`nac llm list-available <pid> --json` to see alternatives.

### `nac vars set` succeeded but agent doesn't see the new value
**Cause**: env vars take effect at **deploy time**. Existing deployment still has old `resolved_env`.
**Fix**: Redeploy: `nac deploy <env> --json`. Verify with `nac vars list <pid>`.

### (Legacy platforms only) `nac llm set --config-mode custom` returns 400 about missing env vars
**Applies to**: older platforms only. On current platforms the project-level LLM settings
API is **retired** — `nac llm set` gets **410 Gone**; pick the model in agent.yaml
`llm_config.model` instead (connection credentials are platform-managed, no custom endpoints).
**Cause (legacy)**: custom mode validation required `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`
in project env vars, and pinged `<LLM_BASE_URL>/v1/models` to confirm reachability + key validity.
**Fix (legacy)**:
```bash
nac vars set --project-id <pid> LLM_MODEL <model> --json
nac vars set --project-id <pid> LLM_BASE_URL <url> --json
nac vars set --project-id <pid> LLM_API_KEY <key> --secret --json
nac vars set --project-id <pid> LLM_API_TYPE openai_chat_completion --json   # or openai_responses / anthropic
# THEN: nac api PUT /api/projects/<pid>/llm-settings --body '{"llm_config_mode":"custom"}'
```

## Debugging

```bash
# Check what the CLI sends
nac api GET /api/projects --json

# Check version
nac --version

# Verbose error output
nac projects list --json 2>&1
```
