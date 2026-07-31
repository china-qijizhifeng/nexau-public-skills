"""DM8 MCP server (cookbook edition) — dmPython TCP 直连。

启动:
    DM8_CONN_STR="SYSDBA/<pass>@<host>:5236" uv run server.py
    # 监听 http://127.0.0.1:8000/mcp/(MCP_PORT 可覆盖)

dmPython 2.5.x 有个老 bug 报 `[CODE:-70089] Encryption module failed
to load` —— wheel 把 libssl/libcrypto 装在 site-packages/dmssl/ 但没加
进 dlopen 路径。`_preload_dmssl_libs()` 在 dmpython.libs/ 下软链同名文件
+ `-3.so` 别名解决。
"""
from __future__ import annotations

import contextlib
import datetime as dt
import decimal
import logging
import os
import re
import site
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

EXEC_TIMEOUT_SEC = 30
DEFAULT_MAX_ROWS = 200
HARD_MAX_ROWS = 1000

_DANGEROUS_KEYWORDS = (
    "DROP", "TRUNCATE", "DELETE", "ALTER", "CREATE", "INSERT",
    "UPDATE", "REPLACE", "MERGE", "CALL", "EXEC", "EXECUTE",
    "GRANT", "REVOKE", "COMMIT", "ROLLBACK",
)
_DANGEROUS_RE = re.compile(rf"\b({'|'.join(_DANGEROUS_KEYWORDS)})\b")

_DMSSL_LINKED = False


def _preload_dmssl_libs() -> None:
    """在 dmpython.libs/ 下软链 dmssl/{libssl,libcrypto}.so,绕开 [-70089]。

    dmPython 内部 dlopen 找的是 libssl(-3).so / libcrypto(-3).so,搜索路径
    包含 dmpython.libs/ 但不含 dmssl/,所以 dmssl/ 里的文件被 dlopen 看不见。
    这里给四个文件名(含 -3.so 别名)各建一个软链,文件系统层面修复。

    幂等:模块级标志位 + os.path.exists 双重保险。
    """
    global _DMSSL_LINKED
    if _DMSSL_LINKED:
        return

    candidates: list[str] = []
    with contextlib.suppress(Exception):
        candidates.extend(site.getsitepackages())
    with contextlib.suppress(Exception):
        candidates.append(site.getusersitepackages())
    for path in sys.path:
        if path.endswith("site-packages") and path not in candidates:
            candidates.append(path)

    for sp in candidates:
        dmssl_dir = os.path.join(sp, "dmssl")
        libs_dir = os.path.join(sp, "dmpython.libs")
        if not (os.path.isdir(dmssl_dir) and os.path.isdir(libs_dir)):
            continue
        link_specs = [
            ("libssl.so", "libssl.so"),
            ("libssl.so", "libssl-3.so"),
            ("libcrypto.so", "libcrypto.so"),
            ("libcrypto.so", "libcrypto-3.so"),
        ]
        for src_name, link_name in link_specs:
            src = os.path.join(dmssl_dir, src_name)
            link = os.path.join(libs_dir, link_name)
            if not os.path.exists(src) or os.path.exists(link):
                continue
            with contextlib.suppress(OSError):
                os.symlink(src, link)
        _DMSSL_LINKED = True
        logger.info("preloaded dmssl libs from %s", dmssl_dir)
        return

    logger.warning("dmssl/ not found; if connect raises -70089, install dmpython properly")


_preload_dmssl_libs()
import dmPython  # noqa: E402  必须在 _preload_dmssl_libs 之后


def _get_conn_str() -> str:
    conn_str = os.environ.get("DM8_CONN_STR", "").strip()
    if not conn_str:
        raise SystemExit(
            "[ERROR] DM8_CONN_STR env var not set.\n"
            '  Example: DM8_CONN_STR="SYSDBA/<password>@<dm-host>:5236" uv run server.py\n'
            "  Or use start.sh which validates this for you."
        )
    return conn_str


def _connect() -> "dmPython.Connection":
    """Open a fresh dmPython connection from DM8_CONN_STR."""
    conn = dmPython.connect(_get_conn_str(), autoCommit=False)
    return conn


def _strip_sql_comments(sql: str) -> str:
    no_line = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"/\*.*?\*/", "", no_line, flags=re.DOTALL)


def _validation_view(sql: str) -> str:
    without_comments = _strip_sql_comments(sql)
    without_single_quoted = re.sub(r"'(?:''|[^'])*'", "''", without_comments)
    without_double_quoted = re.sub(r'"(?:""|[^"])*"', '""', without_single_quoted)
    return without_double_quoted.strip().upper()


def _validate_read_only_sql(sql: str) -> tuple[bool, str]:
    statement = sql.strip()
    if not statement:
        return False, "[ERROR] SQL must not be empty"

    statement_without_comments = _strip_sql_comments(statement).strip()
    if ";" in statement_without_comments.rstrip(";"):
        return False, "[ERROR] Only a single SQL statement is allowed"

    executable_sql = statement.rstrip(";").strip()
    validation_sql = _validation_view(executable_sql)
    if not validation_sql:
        return False, "[ERROR] SQL must not be empty"
    if not re.match(r"^(SELECT|WITH)\b", validation_sql):
        first = validation_sql.split(maxsplit=1)[0]
        return False, f"[ERROR] Only SELECT / WITH queries are allowed (got: {first!r})"

    match = _DANGEROUS_RE.search(validation_sql)
    if match:
        return False, f"[ERROR] Mutating SQL keywords are not allowed: {match.group(1)}"

    return True, executable_sql


def _resolve_max_rows(max_rows: int | None) -> int:
    raw = max_rows if max_rows is not None else os.environ.get("MCP_MAX_ROWS", DEFAULT_MAX_ROWS)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_MAX_ROWS
    return max(1, min(value, HARD_MAX_ROWS))


def _coerce(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    return str(value)


def _format_rows(columns: list[str], rows: list[tuple]) -> str:
    """Format a result set as a fixed-width text table (LLM-friendly)."""
    if not columns:
        return "(no columns)"
    if not rows:
        header = " | ".join(columns)
        return header + "\n" + "(0 rows)"

    str_rows = [[_coerce(v) for v in row] for row in rows]
    widths = [
        max(len(col), *(len(r[i]) for r in str_rows))
        for i, col in enumerate(columns)
    ]
    sep = "-+-".join("-" * w for w in widths)
    header = " | ".join(col.ljust(widths[i]) for i, col in enumerate(columns))
    body = "\n".join(
        " | ".join(val.ljust(widths[i]) for i, val in enumerate(r))
        for r in str_rows
    )
    return f"{header}\n{sep}\n{body}\n({len(rows)} rows)"


mcp = FastMCP("dm8-mcp")


@mcp.tool()
def server_info() -> str:
    """Return backend metadata so the agent can pick the right SQL dialect."""
    return (
        "backend=dm8\n"
        "dialect=dm8\n"
        "read_only=true\n"
        "limit_syntax=FETCH FIRST N ROWS ONLY\n"
        f"default_max_rows={_resolve_max_rows(None)}\n"
        f"hard_max_rows={HARD_MAX_ROWS}"
    )


@mcp.tool()
def query_sql(sql: str, max_rows: int | None = None) -> str:
    """Execute one read-only SQL statement against DM8 and return formatted output.

    - Supports SELECT / WITH only.
    - Mutating keywords are rejected at the application layer.
    - Single statement only — don't chain with `;`.
    - Returns at most MCP_MAX_ROWS rows (default 200, hard cap 1000).
    - Credentials come from env var DM8_CONN_STR.
    """
    ok, result = _validate_read_only_sql(sql)
    if not ok:
        return result

    row_limit = _resolve_max_rows(max_rows)

    conn = None
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(result)
        if cur.description:
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(row_limit + 1)
            truncated = len(rows) > row_limit
            out = _format_rows(columns, rows[:row_limit])
            if truncated:
                out += f"\n(truncated to {row_limit} rows)"
            return out
        return "(no result set)"
    except dmPython.DatabaseError as e:
        return f"[ERROR] {e}"
    except Exception as e:  # noqa: BLE001
        return f"[ERROR] {type(e).__name__}: {e}"
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


@mcp.tool()
def list_tables() -> str:
    """List user tables in the current DM8 schema (excludes system tables).

    DM8 的 USER_TABLES 会带 ##HISTOGRAMS_TABLE / ##PLAN_TABLE 之类
    会话辅助表(双井号开头),业务用不到,过滤掉。
    """
    return query_sql(
        "SELECT TABLE_NAME FROM USER_TABLES "
        "WHERE TABLE_NAME NOT LIKE '##%' "
        "ORDER BY TABLE_NAME"
    )


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Show column definitions for a given table (name, type, nullable)."""
    safe = table_name.replace("'", "''").upper()
    return query_sql(
        "SELECT COLUMN_NAME, DATA_TYPE, NULLABLE "
        "FROM USER_TAB_COLUMNS "
        f"WHERE TABLE_NAME = '{safe}' "
        "ORDER BY COLUMN_ID"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info("starting dm8-mcp, conn = %s", _get_conn_str().split("@")[-1])
    # 显式 bind 0.0.0.0 让宿主机 / 同集群 sandbox 可达(FastMCP 版本间默认值有变)
    mcp.settings.host = os.environ.get("MCP_HOST", "0.0.0.0")
    mcp.settings.port = int(os.environ.get("MCP_PORT", "8000"))
    mcp.run(transport="streamable-http")
