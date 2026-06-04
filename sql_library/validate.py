"""驗證 SQL 範例庫：把 catalog.json 裡每一條 SQL 實際在資料庫跑一次（唯讀），回報通過/失敗。

新增大量 SQL 後務必跑這個，確保每條都跑得通、欄位/合法值沒寫錯：
    venv/bin/python sql_library/validate.py

需要 PostgreSQL 已啟動（bash db/pg.sh start）。任一條失敗時 exit code = 1。
"""

import json
import os
import sys
from pathlib import Path

import psycopg

CATALOG = Path(__file__).resolve().parent / "catalog.json"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://erp@localhost:5433/erp")
MAX_ROWS = 100  # 與 tools/sql_tools.py 的包裝一致


def main() -> int:
    queries = json.loads(CATALOG.read_text("utf-8")).get("queries", [])
    if not queries:
        print("catalog.json 沒有任何查詢。")
        return 1

    conn = psycopg.connect(
        DATABASE_URL,
        options="-c default_transaction_read_only=on -c statement_timeout=5000",
    )
    ok = bad = 0
    failures = []
    for q in queries:
        qid = q.get("id", "?")
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM ({q['sql']}) AS _sub LIMIT {MAX_ROWS}")
                rows = cur.fetchall()
            print(f"✓ {qid:<28} rows={len(rows)}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"✗ {qid:<28} ERROR: {str(e).strip()[:100]}")
            failures.append(qid)
            bad += 1
            conn.rollback()
    conn.close()

    print(f"\n總計 {len(queries)} 條：通過 {ok}、失敗 {bad}")
    if failures:
        print("失敗的範例：" + "、".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
