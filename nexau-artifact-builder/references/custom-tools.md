# custom_tools 编写契约

> **本文覆盖**：自定义工具（`custom_tools/*.py` + `*.tool.yaml` + `agent.yaml` 注册）的完整编写契约——进程边界、框架注入参数、返回值/异常语义、路径解析基准、可用依赖，以及 3 个会让工具每次调用都失败的陷阱。
> **什么时候读**：制品需要「调外部 API / 查数据库 / 读写沙箱文件 / 封装任何非内置能力」时，写第一行 Python 前读。只用内置工具（read_file / search_file_content / …）时不需要读本文，见 `references/builtin-tools.md`。

---

## 0. 三件套最小骨架（可直接抄）

一个自定义工具 = **3 个文件**，缺一不可：

| 文件 | 作用 | 路径基准 |
|---|---|---|
| `custom_tools/my_tool.py` | Python 实现 | 模块路径相对**制品根目录** |
| `tools/my_tool.tool.yaml` | 给模型看的 name/description/input_schema | `yaml_path` 相对**当前 agent.yaml 所在目录** |
| `agent.yaml` 的 `tools:` 条目 | 把二者绑起来 + 注入密钥 | — |

### ① `custom_tools/my_tool.py`

```python
"""自定义工具模板：业务参数 + 框架注入 + extra_kwargs 密钥。"""

from __future__ import annotations

from nexau.archs.main_sub.agent_state import AgentState
from nexau.archs.sandbox import SandboxStatus
from nexau.archs.tool.builtin._sandbox_utils import get_sandbox, resolve_path


def my_tool(
    # ① 业务参数：必须与 tool.yaml 的 input_schema.properties 一一对应（模型只看得到这些）
    file_path: str,
    max_bytes: int = 4096,
    # ② 框架注入：按参数名匹配签名自动注入；禁止写进 input_schema；一律给默认值
    agent_state: AgentState | None = None,
    # ③ extra_kwargs 注入：在 agent.yaml 里配，模型看不到；keyword-only 更安全
    *,
    api_token: str = "",
) -> dict:
    """docstring 不影响模型——模型只看 tool.yaml 的 description。"""
    # ⚠️ 本函数跑在 agent-runtime 进程里，不在沙箱里。裸 open() 读不到 agent 的工作文件。
    try:
        sandbox = get_sandbox(agent_state)
    except Exception as e:
        return {"content": f"拿不到沙箱：{e}"}

    resolved = resolve_path(file_path, sandbox)          # 相对路径按 sandbox.work_dir 拼
    if not sandbox.file_exists(resolved):
        return {"content": f"沙箱里找不到文件：{file_path}"}

    res = sandbox.read_file(resolved, binary=True)       # 二进制一定要 binary=True
    if res.status != SandboxStatus.SUCCESS or res.content is None:
        return {"content": f"读取失败：{file_path}（{res.error}）"}

    data = bytes(res.content)[:max_bytes]

    # 只有 returnDisplay 会被剥掉不发 LLM；其它键都会渲染进模型可见文本。
    return {
        "content": f"读到 {len(data)} 字节",
        "returnDisplay": f"📄 {file_path} · {len(data)}B",
    }
```

### ② `tools/my_tool.tool.yaml`

```yaml
type: tool
name: my_tool
description: >-
  面向模型的说明：这个工具做什么、什么时候该用、返回什么、边界在哪。
  模型选工具只看这段 + 下面每个 property 的 description。
input_schema:
  type: object
  properties:
    file_path:
      type: string
      description: 沙箱内的文件路径，相对路径按工作目录解析
    max_bytes:
      type: integer
      description: 最多读取的字节数，默认 4096
      minimum: 1
  required:
    - file_path
  # ⚠️ 用了 extra_kwargs 就【不要】写 additionalProperties: false（见 §4，必崩）
  # ⚠️ agent_state / sandbox / ctx / global_storage 一律不能出现在这里（含 properties 下面）
```

`.tool.yaml` 的合法顶层字段被 pydantic `ToolYamlSchema`（`extra="forbid"`，`nexau/archs/tool/tool.py:215-232`）锁死，只有：`type / name / description / input_schema / skill_description / disable_parallel / lazy / defer_loading / search_hint / template_override / builtin / binding / formatter`。写别的 key 直接加载失败。

`$schema: http://json-schema.org/draft-07/schema#` **不是必须**——框架用 `validator_for(input_schema)` 自动选 validator（`tool.py:744-752`）。

### ③ `agent.yaml` 注册

```yaml
tools:
  - name: my_tool                          # 会【覆盖】tool.yaml 里的 name（原名存 source_name）
    yaml_path: ./tools/my_tool.tool.yaml   # 相对【本 agent.yaml 所在目录】
    binding: custom_tools.my_tool:my_tool  # Python 模块路径，相对【制品根目录】(sys.path)
    extra_kwargs:                          # 模型看不到；同名参数会被模型传参覆盖
      api_token: ${env.MY_API_TOKEN}
```

> `custom_tools/` **不需要** `__init__.py`（Python 3 namespace package 即可）；但目录名会成为模块名，避免和已安装的第三方包重名。

---

## 1. ⚠️ 进程边界：custom tool 不在沙箱里跑（最重要的一条）

| | custom tool 的 Python 函数 | `read_file` / `run_shell_command` 等内置工具**的副作用落点** |
|---|---|---|
| 代码在哪跑 | **agent-runtime 进程内**（`tool.py:579` `impl(**filtered_params)` 直接调用） | Python 部分**同样**在 agent-runtime 进程内（内置工具就是普通 binding 函数，签名同样声明 `agent_state=None`），只是它们**全部通过 sandbox 句柄**做 IO |
| 文件/命令实际落在 | runtime 容器自己的文件系统：制品挂在 `/agent`（Python Runtime 下**只读**），**cwd = `/home/user`** | 沙箱容器（E2B HTTP RPC → sandboxd），cwd = `/home/user` |
| `os.getenv` 读到的 | runtime pod 的 env（runtime scope） | 沙箱 env（sandbox scope），两者**互不可见** |

> 换句话说：**内置工具和自定义工具是同一套契约**，唯一区别是内置工具从不裸 `open()`，一律走 sandbox 句柄。想不出该怎么写时，直接照抄 `nexau/archs/tool/builtin/file_tools/` 下的实现。

### 🚫 最阴的一条：两边都有 `/home/user`，而且都能写

runtime 容器里 `/home/user` **真实存在且可写**，还正好是进程的工作目录（ `mkdir -p … /home/user` + `:149` `WORKDIR /home/user`；`k8s.rs:2127` `working_dir: Some("/home/user")`）。所以：

```python
open("/home/user/report.md", "w").write(x)   # 🚫 不报错、静默成功
```

写进的是 **runtime 容器**的 `/home/user`，和 agent 用 `read_file` / `run_shell_command` 看到的**沙箱** `/home/user` 是两个不同容器里的同名目录。工具返回「已写入」，agent 下一步 `read_file` 却报文件不存在——**没有任何报错帮你发现，只有行为对不上**。相对路径（`open("out.txt")`）同样落在 runtime 的 `/home/user`。

结论（写代码时按这个判断）：

- **要读写「agent 用 read_file / write_file / run_shell_command 操作的那套文件」→ 必须走 sandbox 句柄**（见 §2）。custom tool 里出现任何裸 `open()` / `Path.write_text()` 指向 `/home/user` 或相对路径，都是 bug。
- **随制品打包的静态资源**（sqlite 文件、词典、模板、离线数据）→ 用裸 `Path` 读**是对的**，它们就在 `/agent` 下。推荐用 `Path(__file__).resolve().parent.parent / "data" / "x.db"` 定位，别硬编码 `/agent`。
- **`/agent` 只读**：任何往制品目录写文件的自定义工具都会 `Read-only file system` 失败（这条反而是响亮报错）。要落盘给 agent 看的产物就写沙箱；只做进程内临时中转才用 runtime 的 `/tmp` 或 `/home/user`（沙箱看不见）。

---

## 2. 拿沙箱的两条路

两条都合法，任选：

```python
# 路 A：直接声明 sandbox 参数，框架把 BaseSandbox 实例注入进来（最短）
def my_tool(q: str, sandbox=None) -> dict:
    res = sandbox.execute_shell("ls /home/user", timeout=30_000)
    ...

# 路 B：声明 agent_state，再用 helper
from nexau.archs.tool.builtin._sandbox_utils import get_sandbox, resolve_path
def my_tool(q: str, agent_state: AgentState | None = None) -> dict:
    sandbox = get_sandbox(agent_state)          # 拿不到 → raise SandboxError("Sandbox not found")
    abs_path = resolve_path("out/report.md", sandbox)   # 相对路径拼 sandbox.work_dir
```

- 注入源头：`nexau/archs/main_sub/execution/tool_executor.py:257-258`（`execution_params["agent_state"]` / `["sandbox"]`）+ `:261`（`["ctx"]`，仅当 `framework_context is not None`）。除 `LoadSkill` 外所有工具执行前都会先 `agent_state.get_sandbox()`（`tool_executor.py:135-136`）。
- helper 定义：`nexau/archs/tool/builtin/_sandbox_utils.py:17-31`。
- 选 A 还是 B：只用文件/命令 → A 更短；还要 `global_storage` / `get_variable` / `get_sandbox_env` → 用 B（`agent_state` 能拿到更多东西）。

### BaseSandbox 常用方法签名（全部**同步**，定义见 `nexau/archs/sandbox/base_sandbox.py:581-1005`）

| 方法 | 签名要点 | 返回 |
|---|---|---|
| `execute_shell` | `(command, timeout=None, cwd=None, user=None, envs=None, background=False)` | `CommandResult(status, stdout, stderr, exit_code, duration_ms, error, truncated, background_pid, output_dir)` |
| `execute_bash` | 同上，**legacy 别名**，新代码用 `execute_shell` | `CommandResult` |
| `execute_code` | `(code, language, ...)` | `CodeExecutionResult` |
| `read_file` | `(file_path, encoding="utf-8", binary=False)` | `FileOperationResult(status, file_path, content, size, error, truncated)` |
| `write_file` | `(file_path, content: str\|bytes, encoding="utf-8", binary=False, create_directories=True, user=None)` | `FileOperationResult` |
| `list_files` | `(directory_path, recursive=False, pattern=None)` | `list[FileInfo]` |
| `glob` | `(pattern, recursive=True, user=None)` | `list[str]` |
| `file_exists` | `(file_path)` | `bool` |
| `get_file_info` / `create_directory` / `delete_file` / `edit_file` | 见源码 | — |
| `upload_file` / `download_file` / `upload_directory` / `download_directory` | 本地 ↔ 沙箱 | `FileOperationResult` |

> ⚠️ **`timeout` 单位是毫秒**（`base_sandbox.py:603` docstring `Optional timeout in milliseconds`）。写 `timeout=120` 意思是 0.12 秒。而 agent.yaml 顶层的 `timeout: 300` 是**秒**，别混。
> 沙箱 `work_dir` 默认 `/home/user`（`base_sandbox.py:169` `E2B_DEFAULT_WORK_DIR`；NAC 侧 `server.py:3148` 显式传 `work_dir="/home/user"`）。

---

## 3. 4 个保留注入参数名

框架保留的参数名共 4 个，常量在 `tool.py:52`：

```python
_INJECTED_PARAM_KEYS = frozenset({"agent_state", "global_storage", "sandbox", "ctx"})
```

| 参数名 | 类型 | 注入条件 |
|---|---|---|
| `agent_state` | `AgentState` | 签名里有就注入 |
| `sandbox` | `BaseSandbox` | 签名里有就注入（框架自带文档漏写了它，但代码支持：`tool.py:568` + `tool_executor.py:258`） |
| `ctx` | `FrameworkContext` | 签名里有就注入。**不写类型标注**只打 warning；**标注成 `FrameworkContext` 以外的类型直接 `ConfigError`**（`tool.py:446-478`），要么正确标注 `ctx: FrameworkContext`（`from nexau.archs.main_sub.framework_context import FrameworkContext`），要么干脆不标 |
| `global_storage` | dict | **只在函数没声明 `agent_state` 时才注入**，见下方坑 |

规则（`tool.py:552-573`）：

1. **按签名参数名匹配**：签名里没有的键会被 `pop` 掉，所以不写就不会 `TypeError`。
2. **一律给默认值**（`agent_state: AgentState | None = None`），防止调用路径变化导致 `TypeError`。
3. **绝不能写进 `input_schema`**（含 `properties` 下面，见 §5）。
4. **`extra_kwargs` 不能用 `agent_state` / `global_storage` / `ctx` 当 key**（`tool.py:291-296` 直接 `ConfigError`）；⚠️ 但 **`sandbox` 不在这个保留列表里**——用 `sandbox` 当 extra_kwargs 的 key 不会报错，却会和框架注入撞车，禁止这么写。

### 🚫 坑：`agent_state` 和 `global_storage` 不能同时声明

`global_storage` 的注入逻辑**嵌在「函数没声明 agent_state」这个分支里**（`tool.py:560-567`；`execute_async` 同款逻辑在 `tool.py:672-679`）：

```python
if "agent_state" in merged_params:
    if "agent_state" not in sig.parameters:
        filtered_params.pop("agent_state", None)
        if "global_storage" in sig.parameters:              # ← 只在这个分支里注入
            filtered_params["global_storage"] = agent_state.global_storage
```

后果：

| 签名 | 结果 |
|---|---|
| `def f(q, global_storage=None)` | ✅ 拿到 `agent_state.global_storage` |
| `def f(q, agent_state=None, global_storage=None)` | ⚠️ `global_storage` 恒为 `None`（静默） |
| `def f(q, agent_state, global_storage)`（都无默认值） | 💥 `TypeError: missing 1 required positional argument: 'global_storage'` |

**正确做法：声明 `agent_state`，用 `agent_state.global_storage` 取值。`global_storage` 参数是 legacy 兼容通道，新代码别用。**

### 🚫🚫 坑：`(*args, **kwargs)` 万能签名拿不到**任何**注入参数（静默）

注入是**按具名形参匹配**的，`**kwargs` 不算。`inspect.signature()` 对可变参数只产出 `args` / `kwargs` 这两个名字（kind 为 `VAR_POSITIONAL` / `VAR_KEYWORD`），所以：

```python
def my_tool(*args, **kwargs):                       # 🚫 sig.parameters == {'args', 'kwargs'}
    sandbox = kwargs.get("sandbox")                 # 恒为 None——框架根本没传进来
    agent_state = kwargs.get("agent_state")         # 同上
```

`"agent_state" in sig.parameters` 恒为 `False` → `tool.py:562` 把它 `pop` 掉。**不报错、不告警、没有日志**，工具照常执行，只是永远拿不到沙箱。四个保留参数（`agent_state` / `sandbox` / `ctx` / `global_storage`）全部适用。

**为什么这个坑特别容易踩**：为了「兼容不同 runner 既可能传 kwargs、也可能传单个 dict」，很多制品会写一个 `_payload(args, kwargs)` 归一化函数，于是签名自然就成了 `(*args, **kwargs)`——一旦这么写，注入参数就永久失联。而且失联后代码往往会「顺理成章」地回落到裸 `open()` / `pathlib`，直接踩进 §1 的进程边界坑：读不到 agent 的工作文件、或把文件静默写进 runtime 容器。

**正确写法：保留 payload 兼容的同时，把注入参数写成 keyword-only 具名形参**（kwonly 会正常出现在 `sig.parameters` 里）：

```python
def my_tool(*args: Any, agent_state: AgentState | None = None, **kwargs: Any) -> dict:
    data = _payload(args, kwargs)                   # payload 兼容照旧
    sandbox = get_sandbox(agent_state)              # ✅ 拿得到
```

自查一行命令（在制品根目录跑，直接复刻框架判据）：

```bash
python3 -c "
import ast,sys
for mod,fn in [('document_tools','read_document')]:          # 换成你的 (模块, 函数)
    n=next(x for x in ast.parse(open(mod+'.py').read()).body
           if isinstance(x,ast.FunctionDef) and x.name==fn)
    names=[a.arg for a in n.args.args]+[a.arg for a in n.args.kwonlyargs]
    print(fn, names, 'agent_state 可注入:', 'agent_state' in names)"
```

> 真实事故：某制品的 `read_document` / `file_exists` / `replace` / `write_docx_file` 四个自定义工具全部写成 `(*args, **kwargs)` + 裸 `pathlib`。表现是 agent 读用户上传的文档恒报 `File not found`——文件在沙箱的 `/home/user/uploads/`，而工具在 runtime 容器里找。因为返回的是普通 dict 而非异常，**runtime 日志零 warn/error、sandbox-proxy 无任何请求记录、trace 里也没有失败 span**，整条链路在可观测层面完全静默，只能靠对话结果反推。其中 `write_docx_file` 更隐蔽：它在 runtime 容器里写文件会**真的成功**，`created: True` 照常返回，agent 汇报「文档已生成」，但沙箱里没有这个文件、用户下载不到。

---

## 4. ⚠️⚠️ P0 陷阱：`extra_kwargs` 与 `additionalProperties: false` 互斥

**症状**：工具**每一次**调用都抛
```
ValueError: Invalid parameters for tool 'my_tool': Additional properties are not allowed ('api_token' was unexpected). params={'api_token': 'SECRET', 'q': 'hi'}
```
（本条已在本仓 `agent-runtime` 环境用真实 `Tool.from_yaml(...).execute(...)` 复现，上面是原样报错文本。）

**机制**（`tool.py:548` → `572-573`）：

```python
merged_params   = {**self.extra_kwargs, **params}          # extra_kwargs 先铺，模型传参在后（会覆盖同名键）
...
validation_params = {k: v for k, v in filtered_params.items() if k not in _INJECTED_PARAM_KEYS}
self.validate_params(validation_params)                     # → jsonschema.validate(params, input_schema)
```

关键：`validation_params` **只剔除 4 个 `_INJECTED_PARAM_KEYS`，不剔除 `extra_kwargs`**。所以 `api_token` 会被送进 jsonschema 校验；schema 又写了 `additionalProperties: false` 且 properties 里没有它 → 必然报错。

**两种正确写法**：

| 写法 | 做法 | 密钥是否对模型可见 | 推荐度 |
|---|---|---|---|
| (a) 删掉 `additionalProperties` | 该工具的 `input_schema` 里**不写** `additionalProperties` 这一行 | ❌ 不可见（安全） | ✅ **默认选它** |
| (b) 把 key 声明进 `properties` | `properties: { api_token: {type: string, ...} }` | ✅ 模型能看见 | 🚫 密钥场景不可接受 |

为什么 (b) 对密钥不可接受：`merged_params = {**extra_kwargs, **params}` 里 **params 在后**，模型传的同名参数会**覆盖** extra_kwargs 的值——等于把密钥的控制权交给了模型。密钥必须走 (a)。

> ⚠️ **抄任何模板/样例前先跑这条机械判据**：
> 对 `agent.yaml` 里每个带 `extra_kwargs:` 的 tools 条目，打开它 `yaml_path` 指向的 `.tool.yaml`，若 `input_schema` 里有 `additionalProperties: false` → **删掉那一行**。
>
> cookbook 原版有三处踩了这个坑（从 cookbook 原仓复制时必删）：
> - 金融数据智能体 `tools/finnhub_*.tool.yaml`（配 `extra_kwargs: api_token`）
> - MAP 知识库问答 `tools/map_vec_*.tool.yaml`（配 `extra_kwargs: app_key / app_secret`）
> - 企业数据库问数 `tools/execute_sql.tool.yaml`（配 `extra_kwargs: db_path`——注意**不是密钥也一样炸**，任何 extra_kwargs 键都参与校验）
>
> ✅ **本 skill 的 `templates/02` / `06` / `03` 已全部修好**（11 个 extra_kwargs 工具注册实测零命中），照抄本 skill 的模板不会踩。
>
> 补充：不用 `extra_kwargs` 的工具（比如纯内置工具的 tool.yaml）保留 `additionalProperties: false` 是安全的，它能让模型乱传参数时立刻报错。判据只有一条：**这个工具有没有 `extra_kwargs`**。

---

## 5. `input_schema` 保留字守卫只查顶层 key

`Tool.from_yaml` 会拒绝 `input_schema` 里出现保留字（`tool.py:357-373`）：

```python
if "global_storage" in input_schema: raise ValueError(...)
if "agent_state"    in input_schema: raise ValueError(...)
if "ctx"            in input_schema: raise ValueError(...)
```

⚠️ 三处判断的对象都是 `input_schema` **本身**，不是 `input_schema["properties"]`。后果：

| 写法 | 结果 |
|---|---|
| `input_schema: { agent_state: ... }`（顶层） | 💥 加载期 `ValueError`，能发现 |
| `input_schema.properties.agent_state` | 😶 **静默通过**，并把 `agent_state` 泄漏进发给模型的 schema |

而且 `sandbox` **四个保留字里唯独它连顶层都不查**。

**别指望框架帮你拦：自己保证 4 个保留名不出现在 `input_schema` 的任何层级。**

---

## 6. 返回值语义：任意类型都合法

`tool.py:606-622`（`execute`）/ `700-715`（`execute_async`）的包装规则：

| 函数返回 | 框架最终结果 |
|---|---|
| `dict` | 原样 |
| dataclass 实例 | `dataclasses.asdict(...)` |
| `list` | `{"result": [...]}`（元素里的 dataclass 也会转 dict） |
| `str` / `int` / `None` / 其它标量 | `{"result": <值>}` |

**所以返回 `str` 完全合法，不强制返回 dict。**

### 🚫 修正一个常见错误说法

cookbook 的注释写「返回 dict 模型看不到字段」——**这是错的**。默认 markdown formatter（`nexau/archs/tool/formatters/markdown.py`）的真实行为：

1. 只有 **`returnDisplay`** 会被剥掉不发给 LLM（`markdown.py:18` `_DISPLAY_ONLY_KEYS = frozenset({"returnDisplay"})`）；剥离是**递归**的（`markdown.py:71-79`），嵌套 dict/list 里的 `returnDisplay` 也会被剥。
2. 剥掉 `returnDisplay` 后**恰好只剩单个 `content`（或单个 `result`）键** → 直通裸值（`markdown.py:47-68`）。
3. 否则**其余所有字段都会被渲染进模型可见文本**（Metadata 段 + Body 段，`markdown.py:88-107`）。

这套 formatter 就是真实的 LLM-facing 路径：`tool_executor.py:350` `tool.format_output_for_llm(...)`；未在 tool.yaml 显式配 `formatter` 时默认回落 `markdown`（`tool.py:398-408`）。

实测（本仓真实运行）：

```python
{"content": "body", "returnDisplay": "ui only", "total_available": 42}
# → 模型看到：
# '## Tool Result\n\n### Metadata\n- `total_available`: 42\n\n### Body (`content`)\n\nbody'

{"content": "body", "returnDisplay": "ui only"}
# → 模型看到：'body'
```

**实践口诀**：
- 正文放 `content`；纯 UI 展示放 `returnDisplay`；**想让模型看到的元数据（如 `total_available`）就大方放顶层键**——它会进 Metadata 段，这正是「窄数据原则」（§10）需要的。
- 想要「只给模型一段干净文本」→ 只返回 `{"content": ...}` 或 `{"content": ..., "returnDisplay": ...}`。
- 不要把大对象、原始 JSON、内部 ID 塞进顶层键——它们都会进模型上下文烧 token。

---

## 7. 异常语义：错误即数据

两类失败，语义完全不同：

| 失败点 | 行为 | 代码 |
|---|---|---|
| **工具函数内部抛异常** | 被 Tool 层吞掉，转成 `{"error": str(e), "error_type": ..., "traceback": ..., "tool_name": ...}` **返回给模型**，走完整 formatter 链 | `tool.py:626-636`（async 同款 `:719-729`） |
| **schema 校验失败** | Tool 层抛 `ValueError`（发生在 `try` **之前**），不走上面的兜底；**但 Executor 还有一层兜底**，最终模型收到的是错误串 `Invalid parameters for tool 'x': …` 而不是 crash | `tool.py:572-573` → `:737-742`，兜底在 `execution/executor.py:2779-2780`（sync）/ `:2150-2151`（async） |
| `AskPermission` / `PermissionDenied` | 唯一会穿透 Tool 层的两个异常（由 Executor 转成 Ask/Deny outcome） | `tool.py:626-628` |

**两条路都不会让 agent 崩**，区别只在模型看到什么：前者是结构化 `{error, error_type, traceback, tool_name}`（会被渲染成 Metadata + Body），后者是一行原始 `ValueError` 文本。

实测（本仓真实运行）：

```python
raise RuntimeError("kaboom")
# → {'error': 'kaboom', 'error_type': 'RuntimeError', 'traceback': '...', 'tool_name': 'boom'}

# required 参数缺失
# → ValueError: Invalid parameters for tool 'p2': 'q' is a required property. params={'api_token': 'SECRET'}
```

**推论：错误即数据。** `traceback` 对模型基本是噪声（还很长）。业务错误自己捕获，转成对模型友好的文字：

```python
try:
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
except httpx.HTTPStatusError as e:
    return {"content": f"查询失败：接口返回 {e.response.status_code}。请确认股票代码是否正确，或稍后重试。"}
except httpx.TimeoutException:
    return {"content": "查询超时（10s）。可以换更小的时间范围重试。"}
```

对「查无结果」也一样：返回 `{"content": "未找到匹配记录。可尝试的做法：①换关键词 ②放宽日期范围"}`，比返回空 list 更能让模型自我纠正。

---

## 8. 两套路径基准（agent.yaml 放子目录时最容易踩）

（下表 `config.py` = `nexau/archs/main_sub/config/config.py`，`common.py` = `nexau/archs/main_sub/utils/common.py`）

| 字段 | 基准 | 代码 |
|---|---|---|
| `tools[].binding` | **制品根目录**（Python 模块路径，走 `importlib.import_module`） | `common.py:21-50`；NAC runtime 把 `<制品根>` 与 `<制品根>/src` 前插 sys.path + PYTHONPATH，见  |
| `tools[].yaml_path` | **当前 agent.yaml 所在目录** | `config.py:1211` `_resolve_config_path(yaml_path, base_path)`，`base_path = config_path.parent`（`config.py:220-224`） |
| `sub_agents[].config_path` | 同上 | `config.py:947`（`_resolve_config_resource`，同一套 base_path 语义） |
| `system_prompt` | 同上 | `config.py:1108-1116` 走同一套 `_resolve_config_path` |

制品根放 `agent.yaml` 时两者看起来一样，一旦把 agent.yaml 放进 `agents/` 子目录就分叉：

```
my-agent/                       ← 制品根 = sys.path 根
├── nexau.json
├── agents/
│   └── main.yaml               ← base_path 是这里
├── tools/
│   └── my_tool.tool.yaml
└── custom_tools/
    └── my_tool.py
```

```yaml
# agents/main.yaml
tools:
  - name: my_tool
    yaml_path: ../tools/my_tool.tool.yaml   # ← 相对 agents/
    binding: custom_tools.my_tool:my_tool   # ← 相对制品根，【不】写 ../custom_tools/...
```

排障信号：

- `ConfigError: Skipped tool 'x': Could not import module from 'custom_tools.impl:x': No module named 'custom_tools'` → binding 的模块路径不对（或目录名拼错）。
- `FileNotFoundError: Tool YAML file not found: ...` → `yaml_path` 相对基准算错了。

其它两条：

- `binding` 里**含 `os.sep` 或以 `.py` 结尾**会走「按文件路径 `spec_from_file_location`」分支（`common.py:38-48`），是另一套语义。**统一用模块路径 `pkg.mod:func`**，别写 `./custom_tools/my_tool.py:my_tool`。
- `yaml_path` 里**不能出现 `:`**——`_resolve_config_path`（`config.py:88-112`）见到非绝对路径带 `:` 会当成 `pkg:resource` 去 importlib.resources 里找。

---

## 9. async / sync 与可用依赖

### async 原生支持

```python
async def my_async_tool(query: str, agent_state=None) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.get(url)
    return {"content": r.text}
```

分流规则（`nexau/archs/main_sub/execution/executor.py:2003-2020`、`:2085`）：

| 实现 | 执行方式 | 含义 |
|---|---|---|
| `def`（sync） | `await asyncio.to_thread(...)`，整条链在 worker 线程里跑 | **做阻塞 IO（`requests.get`、同步 DB 驱动、`sandbox.execute_shell`）是安全的**，不会卡住 event loop |
| `async def` | 在主 event loop 上 `await tool_obj.execute_async(...)` | 里面**不要**调 sync-only 的阻塞 API |

BaseSandbox 的方法全是同步的 → **需要频繁操作沙箱的工具写成 sync `def` 最省事**。

### 可用依赖（跑在 agent-runtime 进程内 ≠ 沙箱）

custom tool 能 import 的是 **agent-runtime 镜像**的依赖（已核实）：

`httpx` · `requests` · `beautifulsoup4` · `PyMuPDF`(fitz) · `Pillow` · `numpy` · `psycopg2-binary` · `pydantic` · `chardet` · `jieba` · `rank-bm25` · `markitdown` · `python-dotenv` · `arxiv` · `pdfdeal` · `tos` · `fastapi` / `uvicorn` / `anyio` / `e2b` / OTel 一族。

沙箱（`run_shell_command` 跑的脚本）是**另一套依赖集**，见 `references/nexau-json-and-packaging.md`。

> 🚫 **cookbook 金融篇写「NAC sandbox 默认只有 Python 标准库、所以要用 `urllib` 不用 `requests`」——这句已过时，不要照抄。** custom tool 用 `httpx` / `requests` 都可以。
> 仍然成立的建议：**不确定时优先 stdlib 更可移植**，但这是偏好，不是平台限制。
> 需要额外第三方库：走 `nexau.json` 的 `setup`（离线 whl），见 `references/nexau-json-and-packaging.md`。

---

## 10. 窄数据原则：输出要 LLM 友好

自定义工具最常见的失败不是报错，而是**返回太多东西把上下文烧穿**。四条硬规则：

| 规则 | 做法 |
|---|---|
| **限条数** | 加 `limit` 参数（`default: 10`，`maximum: 50`），代码里再 hard cap 一次，别信模型传的值 |
| **限字段** | 上游 API 返 40 个字段就挑 5 个转发；不要 `return resp.json()` 原样透传 |
| **限字长** | 长文本字段截断（如新闻正文取前 300 字），截断处加 `…` |
| **给元数据** | 返回 `total_available` / `truncated` / `next_offset` 这类顶层键——它们会进 Metadata 段（§6），模型据此判断「是不是还有更多、要不要换查询条件」 |

```python
return {
    "content": json.dumps(rows[:limit], ensure_ascii=False),
    "total_available": total,          # 模型可见的 Metadata
    "truncated": total > limit,
}
```

另外两条来自 cookbook 的经验：

- **工具越少越好**——模型可见工具越多，选错概率越大。同一能力有「易用但低效」和「稍复杂但高效」两种调用方式时，**隐藏低效那个**（或用 `defer_loading: true` 让它只在 ToolSearch 命中时才进上下文）。
- **`description` 就是路由器**：`tool.yaml` 的 `description` 和每个 property 的 `description` 是模型选工具/选参的**唯一依据**，写清「什么时候该用 / 什么时候不该用」，比在 systemprompt 里补说明有效得多。

---

## 11. 沙箱写二进制

```python
res = sandbox.write_file("/home/user/out/report.pdf", pdf_bytes,
                         binary=True, create_directories=True)
if res.status != SandboxStatus.SUCCESS:
    return {"content": f"写入失败：{res.error}"}
```

读同理：`sandbox.read_file(path, binary=True)` → `res.content` 是 `bytes`。

- ⚠️ **`binary=True` 不是可选修饰**，但两种 sandbox 实现对它的敏感度不同——**无脑都写上才本地/线上都对**：

  | | `write_file(bytes)` | `read_file` |
  |---|---|---|
  | `LocalSandbox`（本地 `nexau` CLI 调试） | **必须 `binary=True`**：`binary=False` 会走 `content.decode(encoding)`（`nexau/archs/sandbox/local_sandbox.py:855-860`），非 UTF-8 字节 → `SandboxStatus.ERROR` | 必须 `binary=True`，否则解码失败 → ERROR |
  | `E2BSandbox`（**NAC 线上实际走这条**） | `binary` **被忽略**，bytes 原样透传给 `_filesystem.write`（`e2b_sandbox.py:1321`），带不带都能写对 | **认 `binary`**：`binary=False` 时 `raw.decode(encoding)`（`e2b_sandbox.py:1246-1249`），二进制 → `UnicodeDecodeError` → ERROR（`:1262-1270`） |

  两边都是**响亮报错**（返回 `status=ERROR` + `error` 文本），不是静默损坏。⚠️ 反过来也要注意：**「本地 LocalSandbox 跑通」不等于线上跑通，反之亦然**——写路径上 E2B 比 LocalSandbox 宽松，本地漏写 `binary=True` 会先炸；读路径两边一致。
- 🚫 **不要用 `base64` 中转**。历史上 sandboxd 确实有一个「写二进制被 UTF-8 round-trip 破坏」的 bug（旧实现 `String::from_utf8_lossy` 手写切 multipart），**已修复**（ 改用 `multer::Multipart` 流式 `field.chunk()` 原样落盘），并留有 Rust 单测 + e2e 双回归守卫。现在 base64 中转只徒增两次落盘和一次 shell 往返。
- 可选的廉价校验（值得留）：写完 `sandbox.execute_shell(f"wc -c < {path}", timeout=60_000)` 比对字节数，或比 sha256。

---

## 12. 交付前自查清单

```
[ ] 3 个文件都在：custom_tools/*.py、tools/*.tool.yaml、agent.yaml 的 tools 条目
[ ] 用了 extra_kwargs 的 tool.yaml → 已删掉 additionalProperties: false        ← P0
[ ] input_schema 任何层级都没有 agent_state / sandbox / ctx / global_storage    ← 框架只拦顶层
[ ] 函数签名的业务参数与 input_schema.properties 逐一对应（名字完全一致）
[ ] 4 个注入参数都给了默认值 = None
[ ] 注入参数是**具名形参**（含 keyword-only），不是靠 *args/**kwargs 接        ← 静默拿不到沙箱
[ ] 没有同时声明 agent_state 和 global_storage
[ ] 要访问 agent 的工作文件 → 走 sandbox 句柄；没有裸 open("/home/user/...")，也没有裸 open("相对路径")  ← 静默写错容器
[ ] 「写成功」的判据来自 sandbox 返回的 status / file_exists，不是本地 path.exists()  ← 否则是假成功
[ ] 声明了 ctx 的话，标注是 FrameworkContext（标错类型 = ConfigError）或干脆不标注
[ ] 读写制品静态资源 → 用 Path(__file__).parent 定位，没有往 /agent 写入
[ ] execute_shell / read_file 的 timeout 用的是毫秒
[ ] 写 bytes 带了 binary=True
[ ] 业务异常已转成对模型友好的 {"content": "..."}，没有把 traceback 丢给模型
[ ] 返回值做了限条数 / 限字段 / 限字长，并给了 total_available 之类元数据
[ ] binding 用模块路径（相对制品根），yaml_path 用相对路径（相对 agent.yaml 目录），两者基准没混
[ ] tool.yaml 的 description 写清了「什么时候该用 / 不该用」
```

---

## 相关文档

- 内置工具清单与 `.tool.yaml` 来源 → `references/builtin-tools.md`
- `${env.X}` / runtime scope / sandbox scope 三通道密钥注入 → `references/env-vars-and-secrets.md`
- `sub_agents` 与自动注入的 `Agent` 工具、`stop_tools` 陷阱 → `references/mcp-and-subagents.md`
- agent.yaml 校验强度分层（为什么 `tools` 条目拼错 key 是静默失效）→ `references/agent-yaml-fields.md`
- 制品打包硬约束 / `setup` 装依赖 / `/agent` 只读 → `references/nexau-json-and-packaging.md`
