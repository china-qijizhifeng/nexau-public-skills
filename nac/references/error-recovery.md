# Error Recovery Guide

When a `nac` command fails, use this table to determine the next action.

## Error → Fix mapping

| Error message | Cause | Fix command |
|--------------|-------|-------------|
| `No authentication found` | No token stored | `! nac auth login --pat <token>`, or set `NAC_TOKEN` (PAT/AK:SK) / `NORTH_AUTH_TOKEN` (north-auth-token session cookie) |
| `INVALID_CREDENTIALS` on gateway | AK:SK wrong or revoked (a PAT on chat/smoke gives 400 `Missing X-Project-Id header` instead) | Re-check with `nac keys list <pid> --json`; reveal SK with `nac keys secret <id>` |
| `Basic authorization with project credentials required` | Older versions, or no credential sent to /agent-api/chat (0.4.x with a PAT gives 400 `Missing X-Project-Id header`) | Need project AK:SK |
| `API error (401)` on management | Bad or expired PAT | `! nac auth login --pat <new-token>` |
| `project_id required` | No nac.json and no --project-id | `nac init --project-id <pid>` or pass `--project-id` |
| `nac.json not found` | Not in a project directory | `cd` to project dir or pass `--project-id` |
| `VERSION_TAG_NOT_FOUND` | No deployment in specified env | Check env name: `nac environments list <pid> --json` |
| `API error (404)` | Wrong API path or resource deleted | Verify resource exists: `nac projects get <pid> --json` |
| `API error (422)` | Missing required field | Check command args with `nac <command> --help` |
| `HTTP request failed` | Network error or server down | Check: `nac api GET /api/projects --json` |
| `error decoding response body` | SDK struct doesn't match API response | Try `nac api GET <path> --json` to see raw response |
| `smoke` exit code 1 | Agent returned error | Check trace: `nac --project-id <pid> traces --json` |
| `smoke` exit code 2 | Timeout | Increase: `nac smoke --timeout 60` |
| `smoke` exit code 3 | Environment not deployed | Deploy first or check env name |
| `invalid --ttl value '<x>'` | humantime parse error before HTTP call | Use `60s`, `5m`, `1h`, `72h`, `7d` |
| `ttl_seconds must be between 60 and 604800` | Server-side range check | TTL must be in `[60s, 7d]` |
| `Only environments with TTL can be extended` (409) | Tried `nac env extend` on a persistent env | Persistent envs don't auto-expire; just keep using it |
| `Environment '<x>' not found` (404) | Wrong env name on `extend` / `delete` | Check: `nac environments list <pid> --json` |
| `Coverage Report: no merge base` | CI's diff-cover bug after rebase | Re-run job (CI infra issue, not your code) |
| `LangfuseNotFoundError` (404) | Wrong trace_id, or trace expired from Langfuse retention | Check session: `nac traces --session <session-id>` |
| `model_not_found` (503) | LLM endpoint has no channel for the configured model | Edit agent.yaml `llm_config.model` (`provider/model_name`, browse with `nac llm list-available`) and redeploy |
| `has_complete_custom_llm_env_vars: false` | (Legacy platforms) old custom-mode switch without all 3 LLM_ vars | Legacy only — retired on current platforms (410); pick the model in agent.yaml `llm_config.model` |
| Agent reads `agent_state.get_variable("X")` returns None | KEY not in resolved_env | `nac vars set --project-id <pid> X VALUE` then redeploy |

## Recovery sequences

### "I can't authenticate"
```bash
# Step 1: Check current state
nac auth whoami --json      # 只读本机存的令牌，不连服务器、不验证平台
# Step 2: If not authenticated, login
! nac auth login                  # 交互粘贴
! nac auth login --pat <token>     # 非交互
# Step 3: Verify（真正打到平台；200=令牌属于这个平台，401=地址或令牌不对）
nac api GET /api/auth/me --json
```
Non-interactive alternatives (no `auth login`): set `NAC_TOKEN` (PAT or `ak:sk`)
or `NORTH_AUTH_TOKEN` (north-auth-token session cookie, for full-stack embedding).
`NAC_TOKEN` / `--token` wins when both are set.

### "I can't chat with the agent"
```bash
# Step 1: Verify project exists
nac projects get <pid> --json
# Step 2: Check if there are API keys
nac keys list <pid> --json
# Step 3: If no usable key, create one
nac keys create <pid> --name "debug-key" --json
# Step 4: Chat with AK:SK
nac --token "ak_xxx:sk_xxx" --project-id <pid> chat <env> -m "test" --json
```

### "Deploy seems broken"
```bash
# Step 1: Check environments
nac environments list <pid> --json
# Step 2: Check versions
nac versions list <pid> --json
# Step 3: Check specific version status — `status_message` field tells you WHY it failed
#         (e.g., "kubernetes error: timeout waiting for deployment ready: ... Pod=Pending"
#          → image pull failure or cluster resource shortage)
nac api GET /api/projects/<pid>/versions/<vid> --json | jq '.body.status_message'
# Step 4: Verify LLM config is reachable (most "deploys but smoke times out" cases)
nac llm show <pid> --json
# Step 5: Try smoke test
nac --token "ak:sk" --project-id <pid> smoke <env> --timeout 30 --json
# Step 6: Check traces if smoke fails
nac --project-id <pid> traces --json
```

### "Agent ignores my variables"
Two paths to inject values, with different lifecycles.
```bash
# Per-call (transient, only this chat invocation):
nac --token "ak:sk" chat <env> --var KEY=VALUE -m "..." --json

# Persistent (in resolved_env, agent reads via agent_state.get_variable):
nac vars set --project-id <pid> KEY VALUE --json
# IMPORTANT: vars only take effect at DEPLOY time. Redeploy required:
nac deploy <env> --json
# Verify:
nac vars list <pid> --json
```

### "nac dev 退出后临时环境留在那里 / 删不掉 (409)"
这是 0.4.x 实测的现状：`Ctrl+C` 自动清理和 `nac clean` 都会因「有 active release」409。手动清理：
```bash
nac versions list --json                       # 找 active 的 __dev__- 版本
nac versions deactivate <version-id> --confirm
nac environments delete <环境名>
```
日常开发建议不用 nac dev：`nac environments create --name dev` 一次，之后 `nac deploy dev --yes`。

### "Ephemeral lane keeps disappearing"
By design — server-side reconciler deletes envs when `expires_at` lapses.
```bash
# Check expires_at
nac environments list <pid> --json | jq '.[].expires_at'
# Extend before TTL fires
nac environments extend <env-name> --ttl 24h --json
# Or fall back to original TTL (re-arm without changing duration)
nac environments extend <env-name> --json
```
