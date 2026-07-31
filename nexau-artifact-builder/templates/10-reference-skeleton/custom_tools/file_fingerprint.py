"""自定义工具示例：通过【NAC 沙箱】计算文件指纹（sha256 + 大小 + 推测类型）。

档案归档场景：归档前给文件算指纹——sha256 相同 = 内容重复（识别重复扫描件），
并把大小/类型记进归档清单。

★ 关键点：本工具读取的是【沙箱里的文件】——也就是 agent 用 read_file / write_file /
  run_shell_command 操作的那套文件，而**不是**运行时进程的本地文件系统（NAC 默认沙箱
  与运行时进程文件系统是隔离的，用裸 `open()/os.path` 读不到 agent 的工作文件）。

  要访问沙箱，工具函数必须声明 `agent_state` 参数——框架会按签名【自动注入】（内置文件
  工具也都这么做）。拿到后用 get_sandbox(agent_state) 取沙箱句柄，走 sandbox.read_file()
  读文件。`agent_state` 不写进 input_schema（schema 里有它会报错）。

custom tool 写法要点：
- 业务参数（file_path）由 LLM 传；agent_state 由框架注入。
- 返回 dict：`content` 要用【字符串】（发给 LLM；返回 dict 模型看不到字段），
  `returnDisplay` 仅前端展示、不发给 LLM。
- 异常转成对模型友好的文字，不要抛原始 traceback。
- 需要密钥时用 agent.yaml 的 extra_kwargs 注入 `*, api_token: str`（示例见「金融数据智能体」样例）。
  ⚠️ 加了 extra_kwargs 就必须把该工具 *.tool.yaml 里的 `additionalProperties: false` 删掉——
  extra_kwargs 会被合并进参数一起送 jsonschema 校验（只有 agent_state/global_storage/sandbox/ctx
  被剔除），否则必报 "Additional properties are not allowed"。
- 本函数跑在【agent-runtime 进程】，读的是 runtime scope 环境变量；沙箱里 run_shell_command
  跑的脚本只能读 sandbox scope，两条通路互不可见。

对应：
- schema:  tools/file_fingerprint.tool.yaml
- binding: custom_tools.file_fingerprint:file_fingerprint
"""

from __future__ import annotations

import hashlib
import mimetypes

from nexau.archs.main_sub.agent_state import AgentState
from nexau.archs.sandbox import SandboxStatus
from nexau.archs.tool.builtin._sandbox_utils import get_sandbox, resolve_path


def file_fingerprint(file_path: str, agent_state: AgentState | None = None) -> dict:
    """通过沙箱读取文件并计算指纹：sha256、大小、推测 MIME 类型。

    Args:
        file_path: 文件路径（来自 LLM；相对路径按沙箱工作目录解析）。
        agent_state: 框架自动注入，用于拿到沙箱句柄（不要写进 input_schema）。
    """
    try:
        sandbox = get_sandbox(agent_state)
    except Exception as e:  # noqa: BLE001 —— agent_state 没注入/无沙箱时给模型友好提示
        return {"content": f"拿不到沙箱（agent_state 未注入？）：{e}"}

    resolved = resolve_path(file_path, sandbox)
    if not sandbox.file_exists(resolved):
        return {"content": f"沙箱里找不到文件：{file_path}"}

    res = sandbox.read_file(resolved, binary=True)
    if res.status != SandboxStatus.SUCCESS or res.content is None:
        return {"content": f"读取失败：{file_path}（{res.status}）"}
    if getattr(res, "truncated", False):
        return {"content": f"文件过大被截断，无法计算可靠指纹：{file_path}"}

    data = (
        res.content
        if isinstance(res.content, (bytes, bytearray))
        else res.content.encode("utf-8", "replace")
    )
    sha256 = hashlib.sha256(data).hexdigest()
    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    # content 必须是【字符串】才会完整发给 LLM（返回 dict 时模型看不到字段）。
    # returnDisplay 仅前端展示，不发给 LLM。
    return {
        "content": (
            f"文件指纹 | path={file_path} | size={len(data)}B "
            f"| sha256={sha256} | mime={mime}"
        ),
        "returnDisplay": f"🔑 {file_path} · {len(data)}B · sha256:{sha256[:12]}…",
    }
