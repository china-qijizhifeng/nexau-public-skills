"""读取制品内 materials/ 目录下的待办材料（市民来信、网民留言等）。

进程边界：本函数跑在 **agent-runtime 进程**内，裸 `Path` 看到的是制品目录（`/agent`，只读）。
内置 `read_file` 走的是**沙箱**文件系统（cwd=`/home/user`），沙箱里没有制品目录，
所以「读随制品打包的材料」必须用本工具，不能用内置 read_file。

本工具的返回值会成为 tool result 进入下一轮 `before_model`，
被 SensitiveWordMiddleware 扫描——这就是「工具结果拦截」这条链路的触发点。
"""

from __future__ import annotations

from pathlib import Path

# 用 __file__ 定位而不是硬编码 /agent：本地裸跑 / 换挂载点都不用改代码。
MATERIALS_DIR = Path(__file__).resolve().parent.parent / "materials"

# 材料全文会进模型上下文，做个上限，避免一份大文件把 context 撑爆。
MAX_CHARS = 8000


def read_material(file_name: str) -> dict:
    """Read one text material shipped inside the artifact's materials/ dir."""
    # 1. 只允许读 materials/ 目录内的文件，挡掉 ../ 逃逸与绝对路径
    target = (MATERIALS_DIR / file_name).resolve()
    try:
        target.relative_to(MATERIALS_DIR)
    except ValueError:
        return {"content": f"拒绝访问：{file_name} 不在 materials/ 目录内。"}

    # 2. 不存在时把可读清单一并返回，让模型自我纠正而不是空手重试
    if not target.is_file():
        available = sorted(p.name for p in MATERIALS_DIR.glob("*") if p.is_file())
        listing = "、".join(available) if available else "（空）"
        return {"content": f"未找到材料：{file_name}。当前可读材料：{listing}"}

    # 3. 读取 + 截断
    text = target.read_text("utf-8", errors="replace")
    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS]

    return {
        "content": text + ("\n…（内容已截断）" if truncated else ""),
        # returnDisplay 是唯一不会发给 LLM 的键，用来放给人看的摘要。
        "returnDisplay": f"📄 materials/{file_name} · {len(text)} 字",
    }
