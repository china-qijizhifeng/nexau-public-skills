# 达梦数据库 · agent 源码

NexAU `custom_tools` + dmPython 直连达梦的样例 agent。**复制改造前先读同目录的 `TEMPLATE.md`**。

## 文件

| 文件 | 作用 |
|---|---|
| `agent.yaml` | Agent 配置，绑定 `run_dameng_sql` |
| `nexau.json` | 项目清单 + `setup`：离线装 dmPython（`setup[0]`）+ `import` 自检（`setup[1]`） |
| `tools/run_dameng_sql.tool.yaml` | 工具 schema（模型可见） |
| `custom_tools/dameng_sql.py` | dmPython 调用 + SQL 校验 + `[CODE:-70089]` workaround |
| `dmpython-airgap/` | 离线 wheel 目录（whl 需手动跑 `download-whls.sh` 拉） |

## setup 路径说明

`nexau.json` 里的 `/agent/dmpython-airgap` 是 NAC runtime 中的平台 artifact root 下路径。也就是说，本地这个目录：

```text
<制品根目录，即含 nexau.json 的那一层>/dmpython-airgap/
```

打包上传后会在 runtime 里对应：

```text
/agent/dmpython-airgap/
```

它不是本地机器上的绝对路径。

`setup` 的第二条是 `import` 自检（`[setup-check] dmPython OK ...`）。setup 命令失败只打 WARNING、**不会中断部署**，
所以部署后要在 runtime pod 日志里确认看到这行，才算依赖真的装上了。

## 所需 Runtime Vars

| Key | 来源 | 说明 |
|---|---|---|
| `DAMENG_DB_CONN_STR` | 自己在 NAC 项目里配（勾 Secret） | 达梦连接串，注入到 tool 的 `extra_kwargs`，模型看不见 |
| `LLM_MODEL` | 平台自动注入（runtime scope） | 项目一张可见模型卡都没有时不会注入，agent 加载会 ConfigError |

`LLM_BASE_URL` / `LLM_API_KEY` 不需要配：NAC 会无条件覆盖 `llm_config` 的 `base_url` / `api_key`。
