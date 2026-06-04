"""SQL 查詢工具：對 ERP 的 PostgreSQL 做「唯讀」查詢。

設計：
- 連線字串集中在環境變數 DATABASE_URL（換真資料庫只改 .env，Agent / graph 不動）。
- 安全防線分兩層：
    1. 應用層：只允許 SELECT / WITH 開頭、禁止分號多語句與寫入類關鍵字。
    2. 資料庫層：連線即設 default_transaction_read_only=on 與 statement_timeout，
       就算第一層漏掉，伺服器端也會擋下任何寫入並限制執行時間。
- 回傳一律是「給 LLM 閱讀的字串」（表格化結果或友善錯誤說明），不丟例外。
"""

import os
import re

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://erp@localhost:5433/erp")
MAX_ROWS = 100  # 回給 LLM 的最大列數，避免一次塞爆 context

# 全資料庫 schema 概覽已移到 tools/sql_schema.py（單一結構化來源 sql_library/schema.json）。
# 需要完整總覽：from tools.sql_schema import SCHEMA_OVERVIEW；需要檢索相關表：用 find_tables。

# 寫入 / DDL 類關鍵字（以單字邊界比對），出現任一個就拒絕
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|"
    r"copy|call|do|vacuum|merge|comment|reindex|cluster|lock)\b",
    re.IGNORECASE,
)


def _get_conn():
    """取得唯讀、有逾時保護的連線。"""
    return psycopg.connect(
        DATABASE_URL,
        options="-c default_transaction_read_only=on -c statement_timeout=5000",
    )


def _validate(query: str) -> str | None:
    """檢查 SQL 是否為單一唯讀查詢；通過回 None，否則回錯誤字串。"""
    q = query.strip().rstrip(";").strip()
    if not q:
        return "查詢為空。"
    if ";" in q:
        return "一次只能執行一條查詢，請移除分號與多語句。"
    if not re.match(r"(?is)^(select|with)\b", q):
        return "只允許 SELECT / WITH 開頭的唯讀查詢。"
    if _FORBIDDEN.search(q):
        return "偵測到非唯讀關鍵字（如 insert/update/delete/drop 等），已拒絕。"
    return None


def _format_rows(columns, rows) -> str:
    """把查詢結果排成等寬表格字串。"""
    if not rows:
        return "查詢成功，但沒有符合的資料。"
    widths = [len(c) for c in columns]
    str_rows = []
    for r in rows:
        cells = ["" if v is None else str(v) for v in r]
        str_rows.append(cells)
        for i, cell in enumerate(cells):
            widths[i] = max(widths[i], len(cell))
    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
    sep = "-+-".join("-" * widths[i] for i in range(len(columns)))
    body = "\n".join(
        " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))
        for cells in str_rows
    )
    note = f"\n（僅顯示前 {MAX_ROWS} 列）" if len(rows) >= MAX_ROWS else ""
    return f"{header}\n{sep}\n{body}\n共 {len(rows)} 列{note}"


from langchain_core.tools import tool


@tool
def describe_schema() -> str:
    """列出 ERP 資料庫所有資料表與其欄位（含型別）。

    在不確定有哪些表、欄位叫什麼時先呼叫這個，再用 run_sql_query 下查詢。
    """
    sql = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    try:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001 連不上等狀況回友善字串
        return f"無法讀取 schema：{e}。請確認 PostgreSQL 已啟動（bash db/pg.sh start）。"

    if not rows:
        return "資料庫中沒有任何資料表，請先執行 venv/bin/python -m db.seed 灌入 mock 資料。"
    out, current = [], None
    for table, col, dtype in rows:
        if table != current:
            out.append(f"\n■ {table}")
            current = table
        out.append(f"    - {col}: {dtype}")
    return "資料表結構如下：" + "".join(out)


@tool
def run_sql_query(query: str) -> str:
    """對 ERP 的 PostgreSQL 執行一條「唯讀」SQL 查詢（只允許 SELECT / WITH）並回傳結果。

    用於查詢員工、部門、特休餘額、請假紀錄等。下查詢前若不確定表結構，
    可先呼叫 describe_schema。寫入類語句（INSERT/UPDATE/DELETE/DDL）一律會被拒絕。

    Args:
        query: 一條完整的 SELECT 查詢（不要加分號、不要多語句）。
    """
    err = _validate(query)
    if err:
        return f"查詢未執行：{err}"
    try:
        with _get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT * FROM ({query.strip().rstrip(';')}) AS _sub LIMIT {MAX_ROWS}")
            columns = [d.name for d in cur.description]
            rows = cur.fetchall()
        return _format_rows(columns, rows)
    except Exception as e:  # noqa: BLE001 把 SQL 錯誤回給 LLM 讓它自行修正
        return f"查詢執行失敗：{e}"
