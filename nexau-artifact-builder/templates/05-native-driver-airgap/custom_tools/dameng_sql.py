"""Read-only Dameng SQL query tool for NexAU custom tools."""

from __future__ import annotations

import contextlib
import datetime as dt
import decimal
import json
import logging
import re
import time
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 20
HARD_MAX_ROWS = 1000
DEFAULT_TIMEOUT = 30
HARD_TIMEOUT = 300
MAX_OUTPUT_LENGTH = 50000

_DANGEROUS_KEYWORDS = (
    "DROP", "TRUNCATE", "DELETE", "ALTER", "CREATE", "INSERT",
    "UPDATE", "REPLACE", "MERGE", "CALL", "EXEC", "EXECUTE",
    "GRANT", "REVOKE", "COMMIT", "ROLLBACK",
)
_DANGEROUS_RE = re.compile(rf"\b({'|'.join(_DANGEROUS_KEYWORDS)})\b")

_ALLOWED_URL_SCHEMES = {"dm", "dameng", "dmpython"}
_CONNECT_KWARGS = {
    "user",
    "password",
    "server",
    "host",
    "port",
    "schema",
    "autoCommit",
    "connection_timeout",
    "local_code",
    "login_timeout",
    "dmsvc_path",
    "app_name",
    "compress_msg",
    "lang_id",
}


_DMSSL_LOADED = False


def _preload_dmssl_libs() -> None:
    """Workaround for dmPython 2.5.x [CODE:-70089] Encryption module failed to load.

    dmPython 把 libssl/libcrypto 装在 site-packages/dmssl/ 但没加进 RPATH,
    dlopen 找不到。运行时改 LD_LIBRARY_PATH / ctypes.RTLD_GLOBAL 都无效,
    唯一可靠的修法是在 dmpython.libs/ 下软链同名文件。幂等。
    """
    global _DMSSL_LOADED
    if _DMSSL_LOADED:
        return
    import os
    import site
    import sys

    # 1. 把所有可能的 site-packages 都扫一遍(venv / system / user)
    candidates: list[str] = []
    with contextlib.suppress(Exception):
        candidates.extend(site.getsitepackages())
    with contextlib.suppress(Exception):
        candidates.append(site.getusersitepackages())
    for path in sys.path:
        if path.endswith("site-packages") and path not in candidates:
            candidates.append(path)

    seen: set[str] = set()
    for sp in candidates:
        dmssl_dir = os.path.join(sp, "dmssl")
        libs_dir = os.path.join(sp, "dmpython.libs")
        if sp in seen or not (os.path.isdir(dmssl_dir) and os.path.isdir(libs_dir)):
            continue
        seen.add(sp)

        # libdmdpi 内部 dlopen 既找 libssl.so 也找 libssl-3.so;dmssl/ 只提供
        # libssl.so 和 libcrypto.so,需要给 -3.so 后缀建别名。
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

        _DMSSL_LOADED = True
        logger.debug("Linked dmssl libs into %s", libs_dir)
        return

    logger.debug("dmssl/ not found in any site-packages; skipping preload workaround")


def _strip_sql_comments(sql: str) -> str:
    no_line = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"/\*.*?\*/", "", no_line, flags=re.DOTALL)


def _validation_view(sql: str) -> str:
    without_comments = _strip_sql_comments(sql)
    without_single_quoted = re.sub(r"'(?:''|[^'])*'", "''", without_comments)
    without_double_quoted = re.sub(r'"(?:""|[^"])*"', '""', without_single_quoted)
    return without_double_quoted.strip().upper()


def _validate_read_only_query(sql: str) -> dict[str, Any] | None:
    sql_for_validation = _validation_view(sql)
    sql_without_comments = _strip_sql_comments(sql).strip()
    if not sql_for_validation:
        return {"status": "error", "error": "SQL query cannot be empty"}
    if ";" in sql_without_comments.rstrip(";"):
        return {"status": "error", "error": "Only one SQL statement is allowed.", "sql": sql}
    if not re.match(r"^(SELECT|WITH)\b", sql_for_validation):
        return {"status": "error", "error": "Only SELECT or WITH queries are allowed.", "sql": sql}
    m = _DANGEROUS_RE.search(sql_for_validation)
    if m:
        return {
            "status": "error",
            "error": f"Only read-only SELECT queries are allowed. Found: {m.group(1)}",
            "sql": sql,
        }
    return None


def _coerce_bool(value: str) -> bool | str:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return value


def _coerce_connect_value(key: str, value: str) -> Any:
    value = urllib.parse.unquote(value)
    if key in {"port", "connection_timeout", "local_code", "login_timeout", "lang_id"}:
        try:
            return int(value)
        except ValueError:
            return value
    if key in {"autoCommit", "compress_msg"}:
        return _coerce_bool(value)
    return value


def _parse_key_value_conn_str(conn_str: str) -> dict[str, Any] | None:
    if "=" not in conn_str or ";" not in conn_str:
        return None
    kwargs: dict[str, Any] = {}
    for part in conn_str.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            return None
        key, value = part.split("=", 1)
        key = key.strip()
        if key not in _CONNECT_KWARGS:
            return None
        kwargs[key] = _coerce_connect_value(key, value.strip())
    return kwargs


def _parse_url_conn_str(conn_str: str) -> dict[str, Any] | None:
    parsed = urllib.parse.urlparse(conn_str)
    if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        return None
    if not parsed.hostname:
        raise ValueError("Dameng URL connection string must include a host.")

    kwargs: dict[str, Any] = {
        "server": parsed.hostname,
        "autoCommit": True,
    }
    if parsed.username:
        kwargs["user"] = urllib.parse.unquote(parsed.username)
    if parsed.password:
        kwargs["password"] = urllib.parse.unquote(parsed.password)
    if parsed.port:
        kwargs["port"] = parsed.port
    path = parsed.path.lstrip("/")
    if path:
        kwargs["schema"] = urllib.parse.unquote(path)

    for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=False).items():
        if key in _CONNECT_KWARGS and values:
            kwargs[key] = _coerce_connect_value(key, values[-1])
    return kwargs


def _build_connect_args(conn_str: str) -> tuple[tuple[Any, ...], dict[str, Any]]:
    conn_str = conn_str.strip()
    if not conn_str:
        raise ValueError("db_conn_str is required.")

    url_kwargs = _parse_url_conn_str(conn_str)
    if url_kwargs is not None:
        return (), url_kwargs

    kv_kwargs = _parse_key_value_conn_str(conn_str)
    if kv_kwargs is not None:
        kv_kwargs.setdefault("autoCommit", True)
        return (), kv_kwargs

    # Official dmPython compact form, e.g. SYSDBA/pass@127.0.0.1:5236/SCHEMA.
    return (conn_str,), {"autoCommit": True}


def _coerce_value(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _rows_to_dicts(columns: list[str], rows: list[Any]) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = []
    for row in rows:
        data.append({column: _coerce_value(value) for column, value in zip(columns, row, strict=False)})
    return data


def _trim_large_result(result: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(result, ensure_ascii=False)) <= MAX_OUTPUT_LENGTH:
        return result
    data = result.get("data", [])
    while len(data) > 1 and len(json.dumps(result, ensure_ascii=False)) > MAX_OUTPUT_LENGTH:
        data = data[:-1]
        result["data"] = data
        result["row_count"] = len(data)
        result["truncated"] = True
    warnings = result.get("warnings", [])
    if not any("length limit" in warning for warning in warnings):
        warnings.append("Results truncated due to length limit.")
        result["warnings"] = warnings
    return result


def run_dameng_sql(
    sql: str,
    db_conn_str: str | None = None,
    timeout: int | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Run a read-only SQL query against a Dameng database.

    Args:
        sql: SELECT/WITH query to execute.
        db_conn_str: Dameng connection string injected via agent YAML extra_kwargs.
        timeout: Driver execution timeout in seconds.
        max_rows: Maximum rows returned to the model.
    """
    if not sql or not sql.strip():
        return {"status": "error", "error": "SQL query cannot be empty"}

    validation_error = _validate_read_only_query(sql)
    if validation_error:
        return validation_error

    if db_conn_str is None or not db_conn_str.strip() or db_conn_str.strip().startswith("${env."):
        return {
            "status": "error",
            "engine": "dameng",
            "error": "db_conn_str is required. Configure DAMENG_DB_CONN_STR as a runtime env var.",
            "sql": sql,
        }

    row_limit = max_rows or DEFAULT_MAX_ROWS
    row_limit = max(1, min(int(row_limit), HARD_MAX_ROWS))
    query_timeout = timeout or DEFAULT_TIMEOUT
    query_timeout = max(1, min(int(query_timeout), HARD_TIMEOUT))

    _preload_dmssl_libs()  # 必须在 import dmPython 之前,见函数注释
    try:
        import dmPython
    except ImportError as exc:
        return {
            "status": "error",
            "engine": "dameng",
            "error": "dmPython is not installed or Dameng native libraries are not on LD_LIBRARY_PATH.",
            "error_type": type(exc).__name__,
            "sql": sql,
        }

    conn = None
    cursor = None
    start = time.time()
    try:
        args, kwargs = _build_connect_args(db_conn_str)
        kwargs.setdefault("connection_timeout", query_timeout)
        conn = dmPython.connect(*args, **kwargs)
        cursor = conn.cursor()
        cursor.execute(sql)

        columns = [description[0] for description in cursor.description] if cursor.description else []
        rows = list(cursor.fetchmany(row_limit + 1))
        duration_ms = int((time.time() - start) * 1000)
        truncated = len(rows) > row_limit
        visible_rows = rows[:row_limit]

        result: dict[str, Any] = {
            "status": "success",
            "engine": "dameng",
            "sql": sql,
            "columns": columns,
            "data": _rows_to_dicts(columns, visible_rows),
            "row_count": len(visible_rows),
            "total_rows": f">={len(rows)}" if truncated else len(visible_rows),
            "truncated": truncated,
            "duration_ms": duration_ms,
        }

        warnings: list[str] = []
        if not visible_rows:
            warnings.append("Query returned 0 rows.")
        if truncated:
            warnings.append("Results truncated due to row limit.")
        if warnings:
            result["warnings"] = warnings
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        result = {
            "status": "error",
            "engine": "dameng",
            "error": str(exc),
            "error_type": type(exc).__name__,
            "sql": sql,
            "duration_ms": duration_ms,
        }
    finally:
        if cursor is not None:
            with contextlib.suppress(Exception):
                cursor.close()
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()

    logger.info("Dameng SQL executed: status=%s rows=%s", result.get("status"), result.get("row_count"))
    return _trim_large_result(result)


__all__ = ["run_dameng_sql"]
