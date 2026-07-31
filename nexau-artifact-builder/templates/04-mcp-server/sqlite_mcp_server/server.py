"""SQLite MCP server — cookbook 教学版,DM8 的轻量替代。

把同一个企业经营数据库 schema 落到本地 SQLite,通过 FastMCP 暴露成
Streamable-HTTP MCP server。工具契约和 `dm8_mcp_server` 一致,
Agent 端 `agent.yaml` 只换 `mcp_servers[*].url` 即可切换。

用法:
    uv run python init_db.py    # 一次性建库 + 注入数据
    uv run python server.py     # 监听 http://127.0.0.1:8000/mcp

环境变量:
    MCP_PORT (默认 8000)
    MCP_HOST (默认 127.0.0.1)
    DB_PATH (默认 ./data/enterprise_ops.sqlite,相对 server.py)
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "enterprise_ops.sqlite"
DB_PATH = Path(os.environ.get("DB_PATH", DEFAULT_DB_PATH)).resolve()

MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("MCP_PORT", "8000"))
MCP_PATH = os.environ.get("MCP_PATH", "/mcp")
MAX_ROWS = 200

# 三层只读防护:白名单 + 关键字黑名单 + 驱动层 mode=ro
_READONLY_PREFIX = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_BANNED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|REINDEX)\b",
    re.IGNORECASE,
)

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[h.strip() for h in os.environ.get(
        "MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*"
    ).split(",") if h.strip()],
    allowed_origins=[o.strip() for o in os.environ.get(
        "MCP_ALLOWED_ORIGINS", "*"
    ).split(",") if o.strip()],
)

mcp = FastMCP(
    "sqlite-mcp",
    host=MCP_HOST,
    port=MCP_PORT,
    streamable_http_path=MCP_PATH,
    transport_security=transport_security,
)


@mcp.tool()
def server_info() -> str:
    """Return backend metadata so the agent can pick the right SQL dialect."""
    return (
        "backend=sqlite\n"
        "dialect=sqlite\n"
        "read_only=true\n"
        "limit_syntax=LIMIT N\n"
        f"default_max_rows={MAX_ROWS}"
    )


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database file not found: {DB_PATH}\n"
            f"  先跑 `uv run python init_db.py` 建库 + 注入数据"
        )
    # mode=ro 让驱动层兜底拦截写操作,即便 SQL 校验被绕过也写不进
    uri = f"file:{DB_PATH}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _resolve_max_rows(max_rows: int | None) -> int:
    try:
        value = int(max_rows) if max_rows is not None else MAX_ROWS
    except (TypeError, ValueError):
        value = MAX_ROWS
    return max(1, min(value, MAX_ROWS))


def _format_table(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    """SQLite 的查询输出格式化成跟 disql 类似的对齐表格,方便 LLM 解析。"""
    if not rows:
        return "(no rows)"
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    sep = " ".join("-" * w for w in widths)
    head = " ".join(f"{h:<{widths[i]}}" for i, h in enumerate(headers))
    body = "\n".join(
        " ".join(f"{str(v):<{widths[i]}}" for i, v in enumerate(row))
        for row in rows
    )
    return f"{head}\n{sep}\n{body}\n\n{len(rows)} row{'s' if len(rows) != 1 else ''}"


@mcp.tool()
def query_sql(sql: str, max_rows: int | None = None) -> str:
    """Execute a read-only SQL query against the SQLite database.

    Supports SELECT / WITH only. Mutating keywords are rejected
    at the application layer; database opens with mode=ro as a second
    layer of defense. Returns at most 200 rows, or a smaller max_rows
    requested by the caller, formatted as an aligned text table.
    """
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        return "[ERROR] SQL must not be empty"
    if not _READONLY_PREFIX.match(statement):
        return f"[ERROR] Only SELECT / WITH allowed (got: {statement.split()[0]!r})"
    if _BANNED.search(statement):
        return "[ERROR] Mutating SQL keywords are not allowed"
    if ";" in statement:
        return "[ERROR] Only a single SQL statement is allowed"

    row_limit = _resolve_max_rows(max_rows)

    try:
        with _connect() as conn:
            cursor = conn.execute(statement)
            rows = cursor.fetchmany(row_limit + 1)
            truncated = len(rows) > row_limit
            rows = rows[:row_limit]
            headers = [d[0] for d in (cursor.description or [])]
        out = _format_table(headers, rows)
        if truncated:
            out += f"\n\n(truncated to {row_limit} rows)"
        return out
    except sqlite3.Error as exc:
        return f"[SQL ERROR] {exc}"


@mcp.tool()
def list_tables() -> str:
    """List user tables in the SQLite database (excludes sqlite_* internals)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return "\n".join(r[0] for r in rows) if rows else "(no tables)"


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Show columns of a table (name, type, nullable)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        return f"[ERROR] Invalid table name: {table_name!r}"
    with _connect() as conn:
        rows = conn.execute(
            f'PRAGMA table_info("{table_name}")'
        ).fetchall()
    if not rows:
        return f"(table {table_name!r} not found)"
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    headers = ["COLUMN_NAME", "DATA_TYPE", "NULLABLE"]
    formatted = [(r[1], r[2], "N" if r[3] else "Y") for r in rows]
    return _format_table(headers, formatted)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
