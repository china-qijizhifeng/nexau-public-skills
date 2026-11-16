# Common Workflows

## First-time setup

```bash
# 1. Install —— macOS/Linux 必须 | bash（| sh 在 Ubuntu 上会报 Illegal option -o pipefail）
curl -fsSL https://download.xiaobei.top/nac-cli/install.sh | bash
#    Windows PowerShell: irm https://download.xiaobei.top/nac-cli/install.ps1 | iex
#    （从源码装：cargo install --path crates/nac-cli）

# 2. 先配地址（零配置默认连官方正式环境 https://nac.xiaobei.top！换成你自己的部署地址），再登录
#    auth login / nac init 都不会记地址；~/.nac/config.toml 在 0.4.x 不生效（源码不读）
export NAC_BASE_URL=https://nac-alpha.xiaobei.top     # 建议写进 ~/.bashrc 或 ~/.zshrc
#    令牌：控制台个人菜单「访问令牌」自己建
nac auth login --pat <token>

# 3. See what's available
nac projects list --json
```

## Create and deploy a new agent

```bash
# 1. Create project
PROJECT_ID=$(nac projects create --name "my-agent" --json | jq -r '.id')

# 2. Initialize project directory + nac.json
mkdir my-agent && cd my-agent/
nac init --project-id $PROJECT_ID

# 3. Author the agent — required files: agent.yaml + system-prompt.md + nexau.json (VERSION optional, nac deploy ignores it)
#    See SKILL.md §Config files for the minimal agent.yaml template.
#    Do NOT write sandbox_config or llm_config.{base_url,api_key,api_type,stream} —
#    platform injects/derives them. `llm_config.model` IS yours to set (optional):
#    full key `provider/model_name`; omit it to follow the project default model.
cat > agent.yaml <<'YAML'
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
YAML
echo "# My Agent System Prompt" > system-prompt.md
echo '{"agents": {"my_agent": "agent.yaml"}, "excluded": [".nexau/", ".env"]}' > nexau.json
echo "0.1.0" > VERSION

# 4. (Optional) Configure project env vars BEFORE deploy
#    These appear in the agent's resolved_env at runtime and avoid per-call --var.
nac vars sync --project-id $PROJECT_ID .env.production --json

# 5. (Optional) Choose the model — set it in agent.yaml
nac llm list-available $PROJECT_ID --json   # browse usable models (provider/model full keys)
#    then write `llm_config.model: <provider/model_name>` in agent.yaml (omit = project default)

# 6. Pack + upload + deploy in one step (production environment)
nac deploy production --json
#    Internally: pack → POST /versions → PUT /artifact → PUT /deploy

# 7. Get AK:SK for chat
nac keys list $PROJECT_ID --json
# Or create a new key if needed:
nac keys create $PROJECT_ID --name "chat-key" --json
# secret_key can be retrieved any time: nac keys secret <key-id> (revoke + recreate if leaked)

# 8. Test
nac --token "ak_xxx:sk_xxx" --project-id $PROJECT_ID smoke production --json

# 9. Chat
nac --token "ak_xxx:sk_xxx" --project-id $PROJECT_ID chat production -m "hello" --json
```

## Debug a failing agent

```bash
# 1. Check project status
nac --project-id $PID status --json

# 2. Check recent traces for errors
nac --project-id $PID traces --json

# 3. Look at specific trace
nac trace <trace-id> --json

# 4. Check logs（alpha 实测 --last/--level/--grep 服务端未生效，只返回最近 200 行，其他平台未验证；自己过滤）
nac --project-id $PID logs <env> --json | jq -r '.response.logs' | grep -v '"DEBUG"'

# 5. Try a direct chat to reproduce
nac --token "ak:sk" --project-id $PID chat <env> -m "reproduce the issue" --json

# 6. Run test suite
nac --token "ak:sk" --project-id $PID test <env> --json
```

## 日常改了就测（比 nac dev 稳，0.4.x 实测）

```bash
nac environments create --name dev --json      # 只做一次
nac deploy dev --yes                           # 每次改完提示词 / 配置 / 工具都跑，十几秒到半分钟
NAC_TOKEN="ak_xxx:sk_xxx" nac chat dev -m "你好" --json | jq -r .content     # 用单轮 -m 并加 --json；交互模式 0.4.x 遇中文会崩
nac traces --last 10m --limit 5                # Session 列对 chat 返回的 session_id
nac trace <trace-id> --export --json -o t.json # 每次模型调用、工具入参与返回
```

0.4.x 里 `nac dev` 的 `--watch` / `--chat` 没有实现（参数被忽略），退出时清理还会 409，详见 SKILL.md「nac dev 实际行为」。

## Run smoke tests in CI

```bash
# In CI pipeline after deploy:
nac auth login --pat $NAC_TOKEN
nac --token "$AK:$SK" --project-id $PID smoke <env> --timeout 30 --json
# Exit code: 0=pass, 1=agent error, 2=timeout, 3=unreachable
```

## Pressure test before release

```bash
nac --token "ak:sk" --project-id $PID bench <env> \
  -c 20 -n 100 -m "typical user query" --json
# Output includes p50/p90/p95/p99 latency, throughput, error rate
```

## Async: fire and observe

For a turn that takes longer than you're willing to hold a connection open. See SKILL.md
§"Async / long-running work" for why `stream: true` is not optional here — with the default
`stream: false` the call blocks for the whole turn **and** `/events` stays empty.

```bash
BASE=https://nac.xiaobei.top
AK=ak_xxx; SK=sk_xxx; PID=<project-id>; ENV=production

# 1. Mint a session (you cannot invent a session id — see SKILL.md §Raw APIs)
SID=$(curl -sS -u "$AK:$SK" -X POST \
  "$BASE/agent-api/sessions?project_id=$PID&environment=$ENV" \
  -H 'Content-Type: application/json' -H "X-Project-Id: $PID" \
  -d '{"distinct_id":"batch-worker-1"}' | jq -r .session_id)

# 2. Kick the run, read ONLY until the first RUN_STARTED, then hang up.
#    disconnect != stop — the agent keeps running server-side.
RUN_ID=$(curl -sSN -u "$AK:$SK" -X POST "$BASE/agent-api/chat" \
  -H 'Content-Type: application/json' -H 'Accept: text/event-stream' \
  -d "{\"stream\":true,\"session_id\":\"$SID\",\"environment\":\"$ENV\",
       \"distinct_id\":\"batch-worker-1\",
       \"messages\":[{\"role\":\"user\",\"content\":\"<long task>\"}]}" \
  | grep -m1 '"RUN_STARTED"' | sed 's/^data: //' | jq -r .run_id)
echo "kicked $RUN_ID"          # typically < 0.3s

# 3a. Poll — the "background task" shape. Terminal states:
#     completed | failed | canceled  (in-flight: submitted | working | input-required)
until [ "$(NAC_TOKEN="$AK:$SK" nac api GET "/agent-api/sessions/$SID/runs" --json \
       | jq -r --arg r "$RUN_ID" '.body.runs[] | select(.id==$r) | .status')" \
       = completed ]; do sleep 2; done

# 3b. …or tail the live channel instead. Empty cursor = new events only, no backlog.
#     Reconnect with ?last_event_id=<the SSE `id:` you last saw> to resume without gaps.
curl -sSN -u "$AK:$SK" "$BASE/agent-api/sessions/$SID/events"

# 4. Read the result: every action carries runId, so filter this run's slice
NAC_TOKEN="$AK:$SK" nac api GET "/agent-api/sessions/$SID/actions" --json \
  | jq --arg r "$RUN_ID" '.body.entities.actions | map(select(.runId==$r))'

# 5. Cancel if needed — session-scoped, takes no run_id
curl -sS -u "$AK:$SK" -X POST "$BASE/agent-api/stop" \
  -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"$SID\",\"distinct_id\":\"batch-worker-1\"}"
```

⚠️ **There is no idempotency.** If step 2 dies and you retry, you get a *second* run — the
`409 SESSION_BUSY` lock only guards the window where the first run is still going. Persist
`$RUN_ID` before doing anything that could crash, and on restart resume from step 3 rather than
re-firing step 2.

## Ephemeral lane for short-lived testing

Use cases: PR previews, demo branches, CI per-build environments, short experiments.

```bash
# 1. Create a 1h ephemeral lane (server auto-cleans after TTL — no manual teardown needed)
nac environments create $PID --name "pr-${PR_NUMBER}" --ttl 1h --json

# 2. Deploy your build to it
nac deploy "pr-${PR_NUMBER}" --json

# 3. Use it (chat / smoke / share preview URL)
nac --token "ak:sk" chat "pr-${PR_NUMBER}" -m "test the new prompt" --json

# 4. (Optional) Need more time? Extend before TTL elapses:
nac environments extend "pr-${PR_NUMBER}" --ttl 24h --json     # override TTL
nac environments extend "pr-${PR_NUMBER}" --json               # fallback to original

# 5. (Optional) Done early? Force-clean now:
nac clean --json                                              # deletes only ephemeral lanes

# Don't worry about Ctrl+C / SSH drop / CI runner crash —
# the server's reconciler will delete the lane when expires_at passes.
```

TTL constraints: `[60s, 7d]`. Anything outside → server returns 400 `INVALID_REQUEST`.
Trying to `extend` a persistent (non-TTL) env → server returns 409 `RESOURCE_CONFLICT`.

## Switch the model (per agent / project default)

Model selection is per-agent in agent.yaml — there is no platform-side switch to flip:

```bash
nac llm list-available $PID --json    # browse usable models (provider/model full keys)
# edit agent.yaml → llm_config.model: <provider/model_name>
nac deploy production --json

# Project default model (used when agent.yaml omits `model`):
nac api PUT /api/projects/$PID --body '{"default_llm_model":"<provider/model_name>"}' --json
nac llm show $PID --json              # verify
```

A bare name / typo / unauthorized `model` does **not** fail the deploy — runtime silently falls
back to the project default (graceful fallback), so double-check the full key against
`nac llm list-available`.

> **Older platforms only**: the old project-level system/custom switch
> (`nac llm set`, `nac vars set LLM_BASE_URL/LLM_API_KEY/...` + `PUT /api/projects/<pid>/llm-settings`)
> is retired — current platforms return **410 Gone**. Custom LLM endpoints are no longer
> configurable at project level; connection credentials are platform-managed. For a
> request-scoped override, the chat API accepts a per-request `llm` field (see the platform
> API reference, "按请求切换模型").

**Important**: agent.yaml changes take effect on the next deploy (versions are immutable).
Run `nac deploy <env>` again to pick up the new config.

## Inspect / filter traces

```bash
# List recent (default 20)
nac --project-id $PID traces --json

# Larger window
nac --project-id $PID traces --limit 100 --json

# Filter by session_id (the `sess_...` id returned by chat / smoke responses)
nac --project-id $PID traces --session "sess_01ABC..." --json

# Drill into one trace (full span tree from Langfuse)
nac --project-id $PID trace <trace-id> --json
```

`trace <id>` requires a project context (nac.json or `--project-id`) — Langfuse
proxy is project-scoped.
