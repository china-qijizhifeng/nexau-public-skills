"""一键建库 — 用 ../_shared_schema/schema_seed.sql 注入到本地 SQLite。

用法: uv run python init_db.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_SQL = BASE_DIR.parent / "_shared_schema" / "schema_seed.sql"
DB_PATH = BASE_DIR / "data" / "enterprise_ops.sqlite"


def main() -> None:
    if not SCHEMA_SQL.exists():
        raise SystemExit(f"schema file not found: {SCHEMA_SQL}")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"[INFO] removed old DB: {DB_PATH}")

    sql_text = SCHEMA_SQL.read_text(encoding="utf-8")
    # 注释里含 `;`,先剥掉 `-- ...` 行再按 `;` 切
    no_comments = "\n".join(
        line for line in sql_text.splitlines() if not line.strip().startswith("--")
    )
    statements = [s.strip() for s in no_comments.split(";") if s.strip()]

    conn = sqlite3.connect(str(DB_PATH))
    ok, skipped = 0, 0
    try:
        for stmt in statements:
            try:
                conn.execute(stmt)
                ok += 1
            except sqlite3.OperationalError as exc:
                # 兼容旧 seed 脚本:如果 DROP TABLE 没写 IF EXISTS,空库会走这里。
                if "no such table" in str(exc).lower():
                    skipped += 1
                else:
                    raise
        conn.commit()
    finally:
        conn.close()

    # 用只读连接报告行数,确认数据真的写进去了
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        for table in ("ENTERPRISES", "FINANCIAL_METRICS", "POLICY_SUPPORT"):
            (n,) = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            print(f"[OK]   {table:20s} {n:4d} rows")
    finally:
        conn.close()

    print(
        f"\n[DONE] executed={ok}, skipped_no_table={skipped}, db={DB_PATH}\n"
        f"       下一步: uv run python server.py"
    )


if __name__ == "__main__":
    main()
