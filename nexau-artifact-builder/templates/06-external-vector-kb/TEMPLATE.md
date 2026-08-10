# 模板：复用外部向量库平台（06-external-vector-kb）

> 把**已经存在的第三方向量库平台**（本例 MAP）的检索 API 封装成 Agent 工具，不重建索引、不动目标平台。难度 🟢 Level 1（改配置为主，代码开箱即用）。来源：nexau-cookbook《MAP 知识库问答》/ `tutorial-map-vector-kb.md`。

## 这个模板教你什么

1. **「KB 白名单直接写进 systemprompt」而不是给 Agent 一个「搜库工具」**——能在编辑期枚举的，绝不留给运行时发现；prompt 是成本最低的索引。
2. **cross-product 批检索工具**：`queries[] × knowledge_base_ids[]` 一次调用、线程池 8 路并发、按 chunk id 去重、`matched_queries[]` 累积成置信信号——用工具形状把 Agent 从「串行循环单查询」的退化模式里拽出来。
3. **结果裁剪即 token 治理**：服务端 hit 十余字段只回传 5 个（`page_content/title/file_name/file_id/segment_position`），主动丢掉 `id`/`score`/`metadata`——不是省钱，是**去掉会误导 LLM 的字段**（跨 query 的 score 量纲不可比）。
4. **上游服务端 bug 在工具层兜底**：识别两类已知报错自动降级 hybrid→semantic，并在 hit 上打 `fallback: true`，由 systemprompt 指导 Agent 向用户说明——错误不上浮成异常，而是降级成带标记的数据。
5. **鉴权三层分离**：`_map_client.py`（token 进程级缓存 + 按 token 值条件失效 + 一次 auth 重试 + 两次 transient 退避）／`map_api.py`（业务加工）／`agent.yaml + systemprompt`（唯一需要改的编排层）。
6. **密钥经 `extra_kwargs` 注入，对 LLM 不可见**——同时这是本模板最容易踩死的地方，见「已知的坑」第 1 条。

## 什么时候用它 / 什么时候不用

| 你的场景 | 用不用 | 替代 |
|---|---|---|
| 客户已有 RAG/向量库平台（MAP / Dify / RAGFlow / 自建 ES），KB 已切好片 | ✅ 就用这个 | — |
| 语料是一堆静态文档，你要自己组织检索 | ❌ | `01-agentic-rag`（skill + grep/Agentic Search，无需向量库） |
| 目标平台是标准 REST 业务 API（非检索语义） | ❌ | `02-rest-api-tool` |
| 目标平台已提供 MCP server | ❌ | `04-mcp-server` |
| 结构化数据问答（表/库） | ❌ | `03-text-to-sql` |
| 完全离线、不能出网 | ❌（本模板必须能访问外部平台） | `05-native-driver-airgap` |
| KB 只有个位数、且长期不变 | ⚠️ 可用，但 batch cross-product 的收益变小 | 同上，或退化成单 KB 直查 |

**Agentic RAG（01）vs 复用外部向量库（06）取舍**：01 的检索质量你自己能调（切片、grep、目录层级），但语料得自己带进制品；06 完全吃平台既有资产、零索引成本，代价是**检索质量的上限被平台锁死**——你只剩三个旋钮：选哪个 KB、query 怎么写、top_k/weights。所以本模板把 60% 的 prompt 篇幅花在「选库流程」和「搜索词优化」上，那才是你唯一能动的地方。

## 目录结构

```
06-external-vector-kb/
├── nexau.json                              # 只声明 agents 映射；excluded 平台不解析（见下）
├── agent.yaml                              # 骨架：llm_config + 7 个工具 + skills: [] + 上下文压缩中间件
├── systemprompt.md                         # 指挥官：角色 + 精选 KB 映射表 + 选库/检索/引用流程（文件名固定，不可改）
├── custom_tools/
│   ├── __init__.py                         # 空文件，使 custom_tools 成为可 import 的包（必须存在）
│   ├── _map_client.py                      # 低层 HTTP：token 缓存/失效重取/transient 重试/自签名 SSL
│   └── map_api.py                          # 4 个 map_vec_* 工具实现 + 结果裁剪 + fallback + 并发
└── tools/
    ├── read_file.tool.yaml                 # 标配三件套（内置工具的 schema 声明）
    ├── search_file_content.tool.yaml
    ├── run_shell_command.tool.yaml
    ├── map_vec_batch_search.tool.yaml       # 主力：cross-product 批检索，N=1 也走它
    ├── map_vec_semantic_search.tool.yaml    # 备用：纯语义
    ├── map_vec_fulltext_search.tool.yaml    # 备用：纯 BM25
    └── map_vec_get_chunks_by_file.tool.yaml # 取同源文档的其他切片（客户端 file_id 过滤）
```

## 复制后必须改的地方

| # | 位置 | 改成什么 |
|---|---|---|
| 1 | `systemprompt.md` §「精选 KB 映射表」 | **换成你自己平台的 KB id + 主题名**。人工筛选 10–50 个；名字用「用户能理解的主题」，剥掉平台原始库名里的 `-pg/-es/-v2/2/3` 内部后缀（这些后缀对选库零帮助且会误导）。这是本模板 90% 的工作量。 |
| 2 | `systemprompt.md` §「主题大类速查」+「选库流程」 | 按 #1 的 KB 重写：把「用户可能问的关键词」映射到「该搜哪几个库」。这决定选库准确率上限。 |
| 3 | `systemprompt.md` §「铁律 2 — 同义词扩召回」表 | 换成你业务的术语对（示例是政务/法规域）。**这张表的收益高于任何工具参数调优**——向量检索的命中质量主要由 query 质量决定。 |
| 4 | **`MAP_HOST` 运行时变量（安全项，必配）** | 填你自己的 MAP 网关地址。本模板**没有默认 host**：不配就在第一次调工具时报 `MAP_HOST is not configured`。这是刻意的——原版兜底到一台公网演示机（`https://<第三方演示机>`），配了自己的 `MAP_APP_SECRET` 却忘了 `MAP_HOST` 的人会把企业密钥静默发给一台不属于自己的机器，而且默认还不校验证书。详见「已知的坑」的 TLS 那两行。 |
| 5 | `custom_tools/_map_client.py` 的 `_fetch_new_token` / `_auth_headers` / `_is_ok` / `_looks_like_auth_failure` | **只有换平台时才动**。这四处编码了 MAP 特有的鉴权语义：token 走 `accessToken` header（不是 `Bearer`）、成功位是 `success`/`result`/`succeed` 三选一、鉴权失败表现为 `HTTP 500 + state=28201`。换平台就把这几处按新平台的约定重写。 |
| 6 | `custom_tools/map_api.py` 的 `_HYBRID_ENDPOINT` / `_SEMANTIC_ENDPOINT` / `_FULLTEXT_ENDPOINT` + `_build_search_body` | 换平台时改路径与 body 形状。`_slim_search_hit` 的字段映射也要跟着改（它读的是 MAP 的 `metadata.{title,file_name,file_id,source,segment_position}`）。 |
| 7 | `custom_tools/map_api.py:_HYBRID_FALLBACK_TRIGGERS` | 换平台时清空或替换为新平台的已知服务端 bug 特征串；**不要保留 MAP 的错误串**（永远匹配不到，等于没有 fallback）。 |
| 8 | `agent.yaml: name` / `description` / `nexau.json: agents` 的 key | 三处名字必须一致，改成你的 agent 名。 |
| 9 | 运行时环境变量（**runtime scope**，不是 sandbox scope） | `MAP_APP_KEY` / `MAP_APP_SECRET` / `MAP_USER_ID` **必填**（走 `${env.*}`，未设置 = 加载期 ConfigError，agent 起不来）；`MAP_HOST` **也必填**，但走 `os.environ` 读（未设置不炸加载期，改成第一次调工具时报错，见 #4）；`MAP_VERIFY_SSL`（正式环境应设为 `true`）/ `MAP_VECTOR_KB_ID` 可选。详见 `../../references/env-vars-and-secrets.md`。 |
| 10 | `agent.yaml: llm_config.model` | 保持 `${env.LLM_MODEL}` 跟随项目默认模型；⚠️ 项目里一张可见模型卡都没有时该变量不会注入，加载会 ConfigError。 |
| 11 | （可选）`agent.yaml` 里 `map_vec_semantic_search` / `map_vec_fulltext_search` 两段 | 建议**注释掉**（不是删除）。经验值：可见工具越多越容易选错工具，batch_search 已覆盖绝大多数场景。🚫 **永远不要注释 `map_vec_batch_search`**——它兼容 N=1 单查询，是唯一的主力检索入口。 |

## 关键设计要点

**为什么不给一个「按主题搜 KB」的工具？** tutorial 给了三条实测理由：(a) 每次会话都要先 list/search 一轮才能开始检索，纯额外开销；(b) 平台上库名往往高度相似（同一主题会有 `xxx` / `xxx2` / `xxx-pg` / `xxx-es` 好几份），关键词搜索区分不出哪个能用，**易选错库**；(c) 库的总量可能很大，但真正可用的通常只有数十个，剩下全是无效检索面。→ 通用原则：**能在编辑期枚举的，不交给 Agent 在运行时发现**。

**为什么单查询也强制走 batch_search？** 通用原则：当同一能力存在「易用但低效」和「稍复杂但高效」两种调用方式时，**把低效的那个藏起来**——Agent 看不见的工具就不会调。tool description 里显式写死「Even single-query / single-KB callers MUST use this tool」，systemprompt 再补一句「绝对不要对同一 KB 连发 5 次以上单查询」。

**为什么同义词要拆成 `queries[]` 而不是拼成一个字符串？** `"政务 政府 行政"` 会被服务端当 phrase 而非 OR，score 被稀释。拆成数组后每个词独立打分、并行发起、结果 union 去重，同时 `matched_queries.length ≥ 2` 天然成为「多同义词共同命中」的强相关信号，供 Agent 优先引用。

**为什么裁掉 `score`？** 不是为省 token（虽然 20 个 hit 能省几千）。真正原因是：hybrid hit 的 score（bm25+向量加权）与 fallback 后 semantic hit 的 score（纯余弦）**量纲不同**，混排后 fallback hit 会不公平地靠前。既然排序本身不可信，就别把它给 LLM——让 Agent 直接读 `page_content` 判断相关性。（本案例接受这个不公平；对排序敏感的场景需在 `map_api.py` 里加 penalty 或强制非 fallback 优先。）

**hybrid body 必须写全**：MAP 的 `/retriever_search_docs` 如果只传 `query + knowledge_base_id`，**不报错**但会静默退化成 semantic。所以 `_build_search_body` 显式带上 `retriever_type=hybrid` + 完整 `config`（top_k / bm_top_k / weights / score_threshold）。→ 通用教训：对上游「简化 body 也返回 200」的端点，永远怀疑它在静默降级。

**token 缓存按 token 值条件失效**：`invalidate_token(rejected_token)` 只在缓存里的 token **等于**被拒绝的那个时才清除。并发请求下这能避免 A 请求把 B 请求刚刷新的新 token 误删。auth 重试预算（1 次）与 transient 重试预算（2 次，0.6s 退避）**分开计**，保证晚到的 auth 失败仍有一次用新 token 的机会。

**性能瓶颈在上游不在 Agent**：agent-runtime 容器无显式 CPU 限制，瓶颈是外网 RTT 和并发数（8）。优化优先级：压缩 query 数量（5 个同义词边际收益已低，3 个够）> 过滤历史上持续 fallback 的 KB > 会话级 LRU cache。**不要去调 runtime pod 资源。**

## 已知的坑

| ⚠️ 坑 | 症状 | 修法 |
|---|---|---|
| **`extra_kwargs` × `additionalProperties: false` 互斥（P0）** | 工具一调用就 `ValueError: Invalid parameters for tool 'map_vec_batch_search': Additional properties are not allowed ('app_key' was unexpected)` | 该工具的 `input_schema` **删掉 `additionalProperties: false`**。框架把 `extra_kwargs` 并进参数后只剔除 `agent_state/global_storage/sandbox/ctx` 四个注入键，`extra_kwargs` 会原样进 jsonschema 校验。**绝不要把 `app_key` 等写进 `properties` 来"合法化"**——那样模型就能看见并覆盖密钥（框架也会因 extra_kwargs 与 properties 冲突而报错）。本模板已修。|
| 密钥配错 scope | 工具返回 `Missing required runtime variable(s): MAP_APP_KEY...`，或 agent 加载期直接 ConfigError | `custom_tools` 跑在 **agent-runtime 进程**内，读 **runtime scope** 环境变量；`${env.*}` 也是从这里取值。配到「沙箱环境变量」里读不到。（cookbook tutorial 写的「通过 Playground 沙箱环境变量设置」对本模板是错的。） |
| `${env.X}` 未设置 = 硬失败 | agent 加载期 ConfigError，整个制品起不来 | `${env.*}` 不支持默认值语法。**可选变量一律走 `os.environ.get()` 在 Python 里读**——本模板的 `_resolve_vector_kb_id` / `_verify_ssl_enabled` 就是这么做的。`MAP_HOST` 也走 `os.environ`（不接 `${env.*}`），但它**语义上是必填**：只是把「加载期整个制品起不来」换成「第一次调工具报一句人话」，不是真的可选。另注意：加载期是对**整个 agent.yaml 文本**做正则替换，**YAML 注释里的 `${env.X}` 一样会被解析**，别在注释里随手写。 |
| 老批次 KB 的 hybrid 端点报服务端 bug | `'Document' object has no attribute 'id'` 或 `不支持全文检索` | 工具层已自动降级到 semantic 并打 `fallback: true`；systemprompt 已指导 Agent 在回答里说明。**回答里偶尔出现「该结果为降级返回」是正常机制，不是缺陷。** |
| KB 只索引了下载链接、没索引正文 | hit 的 `page_content` 全是 `PDF文件下载地址:` / `WORD文件下载地址:` | systemprompt 已教 Agent 识别并提示用户换库。筛 KB 白名单时提前剔掉这类库。 |
| 非 ES 后端静默退化 | 明明配了 hybrid，命中质量像纯语义 | `vector_store_type == "elasticSearch"` 的库才支持完整 hybrid；pg / milvus / faiss 后端可能静默退化。命中明显偏低时先怀疑后端类型。 |
| **⚠️ 默认不校验 TLS 证书，而 `app_secret` 正是走这条链路发出去的** | 表面症状是「自签名证书也能连通」，没有报错——所以很容易一直这么上生产 | `_map_client.py` 的 `_make_ssl_context` 默认 `check_hostname=False` + `verify_mode=CERT_NONE`（私有化 MAP 网关多为自签，这是让模板开箱可用的取舍，**没有改默认**）。代价必须说清：`getSessionToken` 会把 `app_secret` POST 到这条未校验的连接上，能劫持路由的人可以出示任意证书拿走密钥并做中间人。正式环境**必须**设 `MAP_VERIFY_SSL=true`，并给网关配正式证书或把企业 CA 装进信任库。关校验时客户端每进程会 `logger.warning` 一次，日志里搜 "TLS certificate verification is DISABLED" 能查出哪些环境还在裸奔。 |
| **⚠️ 没有默认 host——`MAP_HOST` 不配就报错（刻意的）** | 第一次调 `map_vec_*` 返回 `MAP_HOST is not configured...` | 这是**修掉的一个真实隐患**，不是缺陷：cookbook 原版 `_resolve_host` 兜底到公网演示机 `https://<第三方演示机>`，而 `MAP_APP_KEY/SECRET/USER_ID` 是 `${env.*}` 必填、`MAP_HOST` 是可选——组合起来就是「用户一定配了自己的真凭证，却不一定配 host」，缺 host 时不报错不告警，把企业 `app_secret` 静默发给第三方机器，且不验证对方是谁。现在 `MapClient.__init__` 在 host 为空时直接抛 `MapApiError`，三个调用点都已 `except MapApiError` → 转成给模型的 error 文本，不会炸进程。 |
| 中间件 import 路径漏 `execution` 层 | import 错误 | 必须是 `nexau.archs.main_sub.execution.middleware.context_compaction:ContextCompactionMiddleware`；参数名是 `threshold`（不是 `threshold_ratio`），`ContextCompactionMiddleware` 是 `extra=forbid`，传错名直接报错。 |
| cross-product 爆炸 | `Too many search pairs (36 = 6 queries × 6 KBs). Cap is 30.` | 硬上限 30 对，工具层拦。systemprompt 已写明上限，Agent 应自行缩范围或分多次调。 |
| 提示词文件改名 | 静态校验报 `artifact.required_file.missing: systemprompt.md` | 顶层提示词文件名**必须**是 `systemprompt.md`（本模板原名 `systemprompt_vb.md`，已改）。复制改造时别为了区分业务而重命名，也别只改 `agent.yaml: system_prompt` 指向别的文件名。 |
| 打包 | 上传 413 / 400 | 压缩包 ≤ 100 MiB；归档**不能含符号链接**（含则 400）；必须含 `nexau.json`。见 `../../references/nexau-json-and-packaging.md`。 |

## 本模板相对 cookbook 原版的改动

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `tools/map_vec_batch_search.tool.yaml`<br>`tools/map_vec_semantic_search.tool.yaml`<br>`tools/map_vec_fulltext_search.tool.yaml`<br>`tools/map_vec_get_chunks_by_file.tool.yaml` | **删掉 `additionalProperties: false`**，原地留注释说明原因 | **P0，不改必挂**。这 4 个工具都用 `extra_kwargs` 注入 `app_key/app_secret/user_id`；框架 `merged_params = {**extra_kwargs, **params}` 后只剔除 `agent_state/global_storage/sandbox/ctx`，`extra_kwargs` 会进 `jsonschema.validate`，`additionalProperties: false` 必报 `Additional properties are not allowed`。 |
| `agent.yaml: llm_config` | 删掉 `api_type` / `base_url` / `api_key` / `stream`，只留 `model` + `max_tokens` + `temperature`；顶部加注释说明「本地裸跑 NexAU 需自行补 base_url / api_key」 | NAC 上 `base_url`/`api_key` 被平台无条件覆盖、`api_type` 被模型卡派生值覆盖、`stream` 在流式路径被强制 True——写了纯噪声，还会误导后来者以为这些能配。 |
| `agent.yaml` MAP 工具块 | 新增注释：extra_kwargs 与 `additionalProperties: false` 的互斥规则、密钥必须配 runtime scope、未设置即 ConfigError | 生成新制品的 agent 最容易在这两处翻车，把约束写在它一定会看到的地方。 |
| `custom_tools/_map_client.py:DEFAULT_HOST`<br>`custom_tools/map_api.py:_resolve_host` | **删掉公网演示机兜底**：`DEFAULT_HOST = "https://<第三方演示机>"` 常量整个移除，`_resolve_host` 读不到 `MAP_HOST` 就返回空串，`MapClient.__init__` 见空 host 抛 `MapApiError`；那个 IP 只作为格式示例留在 docstring 注释里 | 安全。凭证三件套是 `${env.*}` **必填**、host 却是可选 —— 用户一定配了自己的真 `app_secret`，却可能忘了 host，于是密钥被静默发到一台第三方机器，且默认还不校验证书。这是「必填项与可选项搭配错了」造成的静默凭证外发。**只改兜底，不改加密行为**（CERT_NONE 默认保留，见下一行）。 |
| `custom_tools/_map_client.py` 的 TLS 部分 | **默认行为一字未改**（仍是 `check_hostname=False` + `CERT_NONE`），只加了三样：模块 docstring 顶部的 ⚠️ SECURITY 段、关校验时每进程一次的 `logger.warning`、TEMPLATE.md「已知的坑」里把后果写实 | 私有化 MAP 网关自签证书是真实常态，把默认反转成「必须校验」会让开箱即挂、反而逼人去改代码绕过。所以选择「保留默认 + 把代价说响」：静默重写别人的加密行为比留着它更危险，而没人告诉你 `app_secret` 正走在这条链路上才是原版真正的问题。 |
| `custom_tools/_map_client.py` 模块 docstring | 「so it runs inside any NexAU sandbox」→ 改为说明 custom_tools 跑在 **agent-runtime 进程**、读 runtime scope、且 runtime 镜像本就有 httpx/requests（stdlib 是可移植性选择而非硬约束） | 原文会让人误以为 custom_tools 在沙箱里跑 → 直接导致把密钥配成 sandbox scope；同时「沙箱只有标准库」在当前 NAC 已过时。 |
| `systemprompt_vb.md` → `systemprompt.md`<br>`agent.yaml: system_prompt` | 提示词文件**重命名**为 `systemprompt.md`，`system_prompt` 同步改为 `./systemprompt.md`；正文逐字未动 | 平台静态校验把 `systemprompt.md` 列为必需顶层文件（`artifact.required_file.missing`），文件名不能自定义。原名 `systemprompt_vb.md` 直接判不合规。 |
| `systemprompt.md` §「沙箱通用三件套」 | 在三件套表格后补一段路径说明：工作目录 / **skills 根目录位于 `/home/user/.skills/`** / 读 skill 附带文件时以 `LoadSkill` 返回的 `SkillFolder` 为权威路径 | 静态校验强制 systemprompt 里出现 skills 根目录声明（`agent.system_prompt.required_pattern_missing`）。本模板不带 skill，所以写成「你正常不需要翻那里，真要读就认 SkillFolder」，既过检又不会诱导 Agent 去拼路径。 |
| `agent.yaml` | 新增 `skills: []` | `skills` 是必需的列表字段，缺失即 `skills.invalid_type`。本模板知识全在外部向量库，空列表是语义正确的声明。 |
| `custom_tools/__pycache__/` | 删除（含 3 个 `.pyc`） | 构建产物不该进模板；`nexau.json: excluded` 只是打包端约定，平台不解析，留着会被一起打包。 |
| 未改动 | `nexau.json` 的 `excluded` 字段原样保留 | 平台**完全不解析** `excluded`，它只是打包端约定。因为无害且是既有约定，逐字保留；只在此说明「别以为平台会按它排除文件」。 |
| 未改动 | `tool_call_mode: structured` | 原版就是合法值（合法值只有 `xml` / `structured`），无需改。 |
| 未改动 | `read_file` / `search_file_content` / `run_shell_command` 三个 tool.yaml 的 `additionalProperties: false` | 这三个是内置工具、**没有 extra_kwargs**，只有框架注入参数（会被剔除），`additionalProperties: false` 可以安全保留。 |
| 未改动 | 中间件 import 路径、`threshold: 0.6`、`max_iterations: 50`、`max_context_tokens: 128000`、全部 Python 逻辑 | 已实测可加载、取值合法 / 属业务调参。 |
| 裁剪情况 | **无裁剪**——本模板与 cookbook 原目录逐文件一致（除上述修正） | 完整原版见 `nexau-cookbook/MAP 知识库问答/MAP 知识库问答/`，配套 tutorial 见同级 `tutorial-map-vector-kb.md`。 |

## 延伸

- 通用知识：`../../references/custom-tools.md`（extra_kwargs / binding / 注入参数）、`../../references/env-vars-and-secrets.md`（runtime vs sandbox scope）、`../../references/llm-config.md`、`../../references/agent-yaml-fields.md`、`../../references/nexau-json-and-packaging.md`、`../../references/builtin-tools.md`
- 相关模板：`01-agentic-rag`（自带语料、无向量库的另一条 RAG 路线）｜`02-rest-api-tool`（同款「REST API → 工具」封装手法，业务 API 版）｜`04-mcp-server`（平台已给 MCP 时的更省事路线）
