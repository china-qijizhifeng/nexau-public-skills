# 平台限制：撞到时的表现、能不能调、怎么自测

> ⚠️⚠️ **带「约」字的数值都是部署级默认值，私有化部署可能不同。**
> **把它们当量级用，不要写死进代码。** 每一条都给了你自己能跑的判据 —— 判据永远比数字可靠。
>
> 「能不能调」三档：**✅ 你自己能改**（控制台或 CLI）/ **⚠️ 部分可调**（有客户端旋钮或参数）/
> **❌ 改不了**（部署级或硬编码，要变只能找平台方）。

---

## 1. 制品与部署

| 限制 | 撞到时你看到什么 | 能不能调 |
|---|---|---|
| 制品包 **100 MiB** | 413 + `Agent Artifact exceeds the 100MB compressed archive size limit. Compressed archive size: <N> bytes; limit: 104857600 bytes.` | ❌ 硬上限。⚠️ 文案里的 "compressed" 是措辞遗留 —— **`nac deploy` 打的是未压缩 tar**，按 gzip 体积估算会严重低估 |
| 超大包的行为 | **一开始就拒**，不会「传一半再报错」 | ❌ |
| 打包固定排除 | `.git` `node_modules` `__pycache__` **`.env`** `target` `dist` `.nac`（任意层级，目录和文件都算） | ⚠️ 只能**加**：`nexau.json` 的 `"excluded": ["fixtures/", …]`（相对制品根） |
| **符号链接** | **既不入包也不报错** | ❌ 改用真实文件 |
| 嵌套 `nexau.json` | `nac deploy` **直接报错拒绝打包**：`Found nested nexau.json at '…'` | ❌ 删掉它或把父目录加进 `excluded` |
| 同一版本重复上传制品 | 409 `Artifact already uploaded for version <vid>` | ❌ 设计如此，版本是不可变快照 |
| `setup` 时间预算 | 约 **2 分钟**。超了实例被判启动失败并反复重启，**表现是「起不来」而不是「慢一点」** | ❌ 重依赖随包带 wheel，或挪到 MCP 服务 |
| `setup` 失败 | ⚠️ **不会让部署失败**，只写一行 `WARNING: setup command failed:` | ❌ 这是行为不是限制。判据见 `symptom-index.md` |
| `nac deploy` 等待上限 | 默认 10 分钟；超时打印 `Deployment timed out after 10m …` | ✅ `--timeout 20m`；`--no-wait` 不等 |
| 同一环境并发部署 | 409 `environment <id> already has deploy operation <op-id> in progress` | ❌ 串行化流水线。执行方异常中断时约 15 分钟后自动失效 |

**自测包大小**：`nac deploy` 打包后会打印 `  <N> bytes`，**以这个数为准**。
⚠️ `--dry-run` 不会真打包，看不到这个数。

---

## 2. 对话面请求

| 限制 | 撞到时你看到什么 | 能不能调 |
|---|---|---|
| `/agent-api/chat` 请求体 **100 MiB** | 413（⚠️ 信封里的 `code` 却是 `INTERNAL_SERVER_ERROR`，判错看状态码 + `message`） | ❌ 多张 base64 图片最容易撞，改走文件上传 |
| **非流式 `stream:false` 约 300 秒硬超时** | **500 `INTERNAL_SERVER_ERROR`，不是 504** —— 很容易误判成「agent 崩了」 | ❌ 长任务必须 `stream: true` |
| **流式 `stream:true`** | 无整体超时，agent 跑多久都行 | — |
| **`stream:false` 时 `/events` 收不到任何事件** | 订阅端一直空转 | ❌ 架构约束。改用 `/actions` 轮询 |
| **同一会话同时只能跑一个 run** | 409 `SESSION_BUSY`，或 SSE 里 `LOCK_CONFLICT` | ❌ 先 `POST /agent-api/stop` 再重试。⚠️ 只读订阅 `/events` **不占**这个名额 |
| `/events` 事件记录保留 | 约 **6 小时滑动 TTL**（每来一条刷新）；超时后旧 `Last-Event-ID` 续不上 | ❌ **历史不受影响**（历史在 `/actions`） |
| `/actions` 分页 | `limit` 默认 50，**传超过 500 不报错、静默截到 500** | ⚠️ 用游标翻页 |
| 会话文件上传 | 单文件 **100 MiB**；整个 multipart 略高一点点。超了 413 `multipart upload exceeds <N> bytes` | ❌ |
| 会话目录列举 | 单目录原始条目约 **5 万**，超了 413 | ❌ |
| 会话文件 PDF 转换 | 端到端预算约 **450 秒**，同步阻塞；超时 504 `RESOURCE_OPS_TIMEOUT` | ❌ **客户端 read timeout 要 ≥ 450 秒** |

**自测非流式超时**：写一个故意跑 6 分钟的 agent，`stream:true` / `stream:false` 各打一次。

---

## 3. 容量、限流、冷启动

| 限制 | 撞到时你看到什么 | 能不能调 |
|---|---|---|
| **容量拒绝** | 429 + `Retry-After: <秒>` + `x-nac-capacity-trace-id` + message `runtime pod at capacity, please retry shortly` | ⚠️ 见下 |
| **429 之前的排队** | 默认约 30 秒、上限约 60 秒 | ✅ **请求头 `X-Max-Queue-Wait: <秒>`**：`0` = 不等直接 429；`>0` 取 `min(你的值, 上限)`；不传用默认；**非法值当没传，不报错** |
| 已扩到副本上限且全部满载 | **不排队直接 429**（fail-fast） | ❌ |
| **沙箱容量不足** | 开流前：503，body 含 `sandbox_at_capacity (<reason>), retry later`；已开流：SSE 里 `{"type":"TRANSPORT_ERROR","reason":"sandbox_at_capacity","retry_after":5}` | ❌ **按 `reason` 分流重试，别只看 `type`** |
| **冷启动** | 响应头 `x-nac-cold-start: true`；平台等实例就绪的预算约 120 秒，正常十几秒 | ⚠️ 别把最小副本设成 0 就基本不会遇到 |
| 缩容到零 | **默认不缩零**（最小副本 1） | ✅ 控制台 负载均衡 tab 把「最小副本数」设为 0；闲置回收小时数范围 [1, 720]，留空 = 24 小时 |
| 拒流阈值（并发 / CPU% / 内存%） | 默认三个都不配 = 不限流 | ✅ 控制台 资源上限 tab，按项目或环境 |

**客户端纪律**：
- **读 `Retry-After`，不要硬编码退避秒数。**
- 重试时**复用同一个 `session_id`**，上下文不会丢。
- 被 429 拒的那一轮**没有被执行**，但会在会话记录里留下一条红色痕迹（控制台看得到，不是凭空消失）。

**自测排队行为**：压测时对比带不带 `X-Max-Queue-Wait: 0`，看 429 出现的快慢。

### 副本与扩缩容的可配项与边界

控制台 → **负载均衡** tab（也可 `nac versions scaling <vid> --min N --max M`）：

| 字段 | 范围 | 越界时的提示原文 |
|---|---|---|
| 最小副本数 | ≥ 0，且 ≤ 最大副本数 | `最小副本数不能大于最大副本数。` |
| 最大副本数 | ≥ 1 | `最大副本数必须是正整数。` |
| 活跃连接数阈值（每副本） | (0, 1000] | `活跃连接数阈值必须落在 (0, 1000]。` |
| CPU 阈值 (%) | [1, 100] 或留空 | `CPU 阈值必须落在 [1, 100]，或留空。` |
| 内存阈值 (%) | [1, 100] 或留空 | `内存阈值必须落在 [1, 100]，或留空。` |
| 最大副本 = 1 时 | CPU/内存阈值**必须留空** | `最大副本数为 1 时，CPU / 内存阈值必须留空。` |
| 闲置回收小时数 | 仅最小副本 = 0 时可填 | `仅当最小副本数为 0 时才能配置闲置回收小时数。` |

---

## 4. 沙箱

| 限制 | 撞到时你看到什么 | 能不能调 |
|---|---|---|
| **闲置约 5 分钟自动暂停** | 隔几分钟再对话，第一次工具调用明显变慢（数秒级） | ❌ |
| 恢复速度 | 命中保活池：亚秒级；未命中冷恢复：数秒级 | ❌ |
| **跨暂停/恢复只保住少数目录** | 默认 `/home/user`（也是工作目录）、`/tmp`、`/usr/local`、`/var/cache`、`/opt` | ❌ 具体清单取决于你所用的部署 |
| **系统包管理器数据库不在保留清单里** | **沙箱里 `apt-get install` 的包恢复后等于没装**；`pip install --user` / `npm install -g` 落在保留路径里，能活下来 | ❌ |
| **沙箱 CPU / 内存** | 由平台配置 | ❌ **项目/环境级改不了**（能改的只有 Runtime 那一侧，见 §6） |
| **沙箱磁盘** | **没有明确配额**。撑爆的表现不是报错，而是实例被回收 | ❌ **别在沙箱里囤 GB 级中间文件**；状态越大，暂停/恢复越慢越易失败 |
| **出网只允许公网单播 IPv4** | 连内网服务时连接被拒 | ❌ 不可关。公网通不通取决于部署方是否启用出网白名单 |
| 私有网段 / IPv6 | 全禁（`10.` `172.16-31.` `192.168.` `127.` `169.254.` 等；IPv6 完全不支持） | ❌ |
| **DNS 重绑定防护** | 域名解析结果里**只要有一个是禁止地址，整条连接直接拒**（不是「挑一个能用的」） | ❌ 内网 DNS 把公网域名解析到内网 IP 的场景会整体失败 |
| **`run_shell_command` 默认超时 30 分钟** | 工具结果里 `Timeout: command timed out after 30.0 minutes.` | ⚠️ 超时是工具参数，agent 可按需传更短的值 |
| **shell 输出超约 1 万字符被截断** | 每一路各留**头 5000 + 尾 5000 字符**，截断处有明确标记 `... [N characters omitted] ...` 和 `(Full output: <目录>/stdout.txt)` —— **不是静默的** | ❌ 阈值不可调，但完整输出落在沙箱文件里，让 agent 去 `read_file` 即可。**大文件优先 `grep` / `head`，别 `cat`** |

### 两个必须自己跑一遍的自测

**出网边界**（Playground 里让 agent 执行；正常结果是「第一条通、后两条失败」）：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://example.com   # 公网：取决于是否启用出网白名单
curl -sS --max-time 5 http://10.0.0.5:8080                      # 私网：一定失败
curl -6 --max-time 5 https://ipv6.google.com                    # IPv6：一定失败
```

**路径持久性**：

```bash
echo hi > /home/user/x && echo hi > /var/log/x
# 闲置 5 分钟以上，再回来
cat /home/user/x    # 应该还在
cat /var/log/x      # 多半没了
```

> **关于隔离强度**：不同部署启用的隔离档位不同（容器级 / 内核级）。
> 这项由部署方配置，**你在使用侧无法自证** —— 要拿它做「能否运行不可信代码」的风险决策，
> 请直接向平台方书面确认，不要从任何文档措辞推断。

---

## 5. 单次运行内部（这些你自己完全可控，写在 `agent.yaml`）

| 字段 | 默认 | 撞到时 |
|---|---|---|
| `max_context_tokens` | 128000 | 触发上下文压缩，SSE 上出 `COMPACTION_STARTED` / `COMPACTION_FINISHED` |
| `max_iterations` | 100 | 强制收尾，**最终回复末尾追加 `[Note: Maximum iteration limit reached]`** ← 这就是判据 |
| `max_running_subagents` | 5 | 并行子 agent 上限 |
| `retry_attempts` | 5 | 模型调用重试次数 |
| `timeout` | 300 秒 | **单次工具 / 模型调用**超时（⚠️ 别和 `run_shell_command` 的 30 分钟混了，也别和非流式的 300 秒整体超时混了） |

字段写法见 `nexau-artifact-builder`。

**模型调用的部署级超时**（你改不了但要知道）：空闲超时约 300 秒（只要模型还在持续吐字就不截断，
连续 300 秒没有新数据才判超时）；总时长兜底约 3600 秒 ⇒ **生成长文档不会被固定超时切断，
但单次模型调用最长约 1 小时**。

---

## 6. 你自己能改的配置一览（控制台 → 项目设置）

| tab | 管什么 | 相关章节 |
|---|---|---|
| 基本信息 | 项目名 / 描述 | — |
| API Keys | 项目 AK/SK | `SKILL.md` §1 |
| **运行配置** | LLM 配置 / 运行时变量 / 沙盒变量 | 见下 |
| S3 对象存储挂载 | 项目级对象存储 | 制品侧，见 `nexau-artifact-builder` |
| Privacy Domain（隐私域） | 字段级加密。⚠️ **口令不可找回** | `evidence-sources.md` §7 |
| **负载均衡** | 最小/最大副本、扩容阈值、缩零闲置小时 | §3 |
| **资源上限** | Runtime CPU/内存上限 + 三维拒流阈值 | §3 / 见下 |
| **网络策略** | 出网白名单**申请**（⚠️ **仅项目 owner 可见**，需管理员审批） | `symptom-index.md`「连不上我们自己的服务」 |
| IM Channels | 绑定消息平台 | — |
| Members | owner / developer / viewer | — |
| 危险操作 | 删除项目（要手打项目名） | `SKILL.md` §2.5 |

**资源上限 tab 的关键区分**（不讲清楚容易调错地方）：
项目/环境级**只能调 Runtime 的 CPU / 内存上限**；**沙箱那两项只有平台级有**。
界面上若出现沙箱字段，会弹一条警告：自定义沙箱上限会让该范围**失去预热加速**（改为冷创建），
首次启动延迟略增。上限校验：`必须是 ≤ 65536 的正整数`。

**每个 tab 都是「跟随平台 / 跟随项目 / 自定义」三态**：选「跟随」时不能带配置体
（否则报 `follow mode must not carry a config blob`）；选「自定义」必须给完整配置块
（否则 `mode=custom requires a complete config blob`）。

**环境变量约束**（`nac vars` 或 运行配置 tab）：
- key 只能字母 / 数字 / 下划线，≤ 255 字符
- `LANGFUSE_*` 是平台保留前缀，写入被拒并给出明确提示
- 有 **`runtime` / `sandbox` 两个作用域，显式传**（不传按 runtime 处理且已标记废弃）

---

## 7. 你**改不了**、需要找平台方的

- 沙箱 CPU / 内存 / 磁盘配额、闲置暂停时长、跨暂停恢复的持久路径清单
- 制品包与请求体的 100 MiB 上限、非流式的 300 秒超时
- 出网白名单的**批准**（申请你能提，批准必须管理员）
- trace 存储是否开通（`403 Langfuse not configured`）
- 平台侧总容量 / 实例数上限（**你能调的只有自己版本的副本上下限**）
- 沙箱隔离档位
- 模型卡（有哪些模型对本项目可见）
