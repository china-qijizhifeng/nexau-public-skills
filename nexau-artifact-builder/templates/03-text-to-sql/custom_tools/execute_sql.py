"""Execute SQL tool — runs read-only SELECT queries directly against a local SQLite file."""

from __future__ import annotations

import json
import logging
import re
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_ROWS = 10
MAX_OUTPUT_LENGTH = 50000
DEFAULT_TIMEOUT = 30

# ⚠️ 硬闸门：模型传进来的 max_rows / timeout 一律 clamp 到这里，
# tool.yaml 里的 maximum 只是给模型看的提示，不能当安全边界（模型能传任意值）。
HARD_MAX_ROWS = 1000
HARD_TIMEOUT = 300

# db_path 找不到时的自检扫描预算（秒），防止在大目录上把 rglob 走完。
_SCAN_BUDGET_SECONDS = 2.0
_MAX_CANDIDATES = 20

_DANGEROUS_KEYWORDS = (
    "DROP", "TRUNCATE", "DELETE", "ALTER", "CREATE", "INSERT", "UPDATE",
    "REPLACE", "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX",
    "GRANT", "REVOKE",
)


def _strip_sql_comments(sql: str) -> str:
    no_line = re.sub(r"--[^\n]*", "", sql)
    no_block = re.sub(r"/\*.*?\*/", "", no_line, flags=re.DOTALL)
    return no_block


def _coerce_value(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def execute_sql(
    sql: str,
    db_path: str,
    timeout: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Execute a read-only SQL query against a local SQLite database file.

    Args:
        sql: SQL query (SELECT / WITH ... SELECT only).
        db_path: Path to the SQLite database file on the local filesystem.
        timeout: Query timeout in seconds (default 30, hard-capped at 300).
        max_rows: Max rows to return (default 10, hard-capped at 1000).
    """
    # 模型传的值不可信：clamp 到 HARD_* 闸门内（custom-tools.md §10「别信模型传的值」）
    try:
        timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), HARD_TIMEOUT))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    try:
        max_rows = max(1, min(int(max_rows or MAX_ROWS), HARD_MAX_ROWS))
    except (TypeError, ValueError):
        max_rows = MAX_ROWS

    if not sql or not sql.strip():
        return {"status": "error", "error": "SQL query cannot be empty"}

    sql_cleaned_upper = _strip_sql_comments(sql).strip().upper()
    for keyword in _DANGEROUS_KEYWORDS:
        if re.match(rf"^{keyword}(?:\s|$)", sql_cleaned_upper):
            return {
                "status": "error",
                "error": f"Only SELECT queries are allowed. Found: {keyword}",
                "sql": sql,
            }
    if not re.match(r"^(SELECT|WITH)\b", sql_cleaned_upper):
        return {
            "status": "error",
            "error": "Only SELECT or WITH ... SELECT queries are allowed.",
            "sql": sql,
        }

    db_file = Path(db_path)
    if not db_file.exists():
        cwd = Path.cwd()
        candidates: list[str] = []
        # /agent 是 NAC 上制品被解包的根目录（AGENT_PROJECT_DIR 默认值），必须在搜索范围里。
        # 刻意不扫 /tmp 和 cwd.parent（runtime 里分别是噪声源和 /home，都不会放制品自带的 sqlite）。
        search_roots = [
            cwd,
            Path("/agent"),
            Path("/app"),
            Path("/workspace"),
            Path("/artifacts"),
        ]
        seen: set[str] = set()
        scan_deadline = time.time() + _SCAN_BUDGET_SECONDS
        scan_truncated = False
        for root in search_roots:
            if not root.exists() or str(root) in seen:
                continue
            seen.add(str(root))
            try:
                for found in root.rglob("*.sqlite*"):
                    candidates.append(str(found))
                    if len(candidates) >= _MAX_CANDIDATES or time.time() > scan_deadline:
                        scan_truncated = True
                        break
            except (PermissionError, OSError):
                continue
            if scan_truncated:
                break

        try:
            cwd_listing = sorted(os.listdir(cwd))[:50]
        except OSError as e:
            cwd_listing = [f"<listdir error: {e}>"]

        # ⚠️ 排障信息只给人看：走 returnDisplay，会被 markdown formatter 剥掉，
        # 不进模型上下文（custom-tools.md §6 / §10 窄数据原则）。
        # 模型只需要 error 那一句话，路径清单和目录列表对它没用还烧 token。
        diagnostics_lines = [
            f"db_path 参数: {db_path}",
            f"解析后的绝对路径: {db_file.resolve()}",
            f"进程 cwd: {cwd}",
            f"cwd 内容（最多 50 项）: {', '.join(cwd_listing) or '<empty>'}",
            f"扫到的 sqlite 候选（最多 {_MAX_CANDIDATES} 条）: "
            + (", ".join(candidates) if candidates else "<none found>"),
            f"扫描根目录: {', '.join(str(r) for r in search_roots if r.exists())}",
        ]
        if scan_truncated:
            diagnostics_lines.append("（扫描已截断：达到候选数上限或超出扫描时间预算）")

        return {
            "status": "error",
            "error": f"Database file not found: {db_path}",
            "sql": sql,
            "returnDisplay": "数据库文件未找到，排障信息：\n" + "\n".join(diagnostics_lines),
        }

    start = time.time()
    try:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return {
            "status": "error",
            "error": f"Failed to open database: {e}",
            "sql": sql,
        }

    conn.row_factory = sqlite3.Row
    deadline = time.time() + timeout
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 1000)

    try:
        cursor = conn.execute(sql)
        cols = [d[0] for d in cursor.description] if cursor.description else []
        # 只多取一行用来判断是否被截断；绝不 fetchall()——大表会先把全表读进内存
        # （mcp-and-subagents.md：fetchmany(limit+1) 判断截断，防上下文被一次全表扫爆）
        rows = list(cursor.fetchmany(max_rows + 1))
        truncated = len(rows) > max_rows
        visible = rows[:max_rows]
        data = [{k: _coerce_value(v) for k, v in dict(r).items()} for r in visible]
        duration_ms = int((time.time() - start) * 1000)

        # 已截断时不知道全表行数（没有 fetchall），只能给下界；要精确值请另跑 COUNT(*)
        total_rows: Any = f">={len(rows)}" if truncated else len(visible)

        result: dict[str, Any] = {
            "status": "success",
            "command_status": f"SELECT {total_rows}",
            "sql": sql,
            "columns": cols,
            "data": data,
            "row_count": len(data),
            "total_rows": total_rows,
            "truncated": truncated,
            "duration_ms": duration_ms,
        }

        warnings = []
        if not rows:
            warnings.append("Query returned 0 rows.")
        if truncated:
            warnings.append(
                f"Results truncated at max_rows={max_rows}. "
                "Run COUNT(*) if you need the exact total."
            )
        if warnings:
            result["warnings"] = warnings
    except sqlite3.OperationalError as e:
        duration_ms = int((time.time() - start) * 1000)
        msg = str(e)
        if "interrupted" in msg.lower():
            result = {
                "status": "timeout",
                "error": f"Query timed out after {timeout}s",
                "sql": sql,
                "duration_ms": duration_ms,
            }
        else:
            result = {
                "status": "error",
                "error": msg,
                "error_type": "OperationalError",
                "sql": sql,
                "duration_ms": duration_ms,
            }
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        result = {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
            "sql": sql,
            "duration_ms": duration_ms,
        }
    finally:
        conn.close()

    if len(json.dumps(result, ensure_ascii=False)) > MAX_OUTPUT_LENGTH:
        data = result.get("data", [])
        while len(data) > 1 and len(json.dumps(result, ensure_ascii=False)) > MAX_OUTPUT_LENGTH:
            data = data[:-1]
            result["data"] = data
            result["row_count"] = len(data)
            result["truncated"] = True
        warnings = result.get("warnings", [])
        if not any("length limit" in w for w in warnings):
            warnings.append("Results truncated due to length limit.")
            result["warnings"] = warnings

    logger.info("SQL executed: status=%s db=%s", result.get("status"), db_path)
    return result
