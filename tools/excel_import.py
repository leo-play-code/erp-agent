"""Excel → PostgreSQL 匯入(scenario B:數據型 Excel,要精確算數/排序/篩選/JOIN)。

與 RAG(語意問答)分工:規章/說明型文件丟 RAG(tools/rag_tools.py);這裡處理「數據型」
Excel——把每個分頁建成一張資料表灌進 DB,再自動登記到 sql_library/schema_imports.json,
之後 sql agent 就能用 SQL 精確查詢(SUM、排序、跨表 JOIN)。

設計(依商定的預設):
- 單位:一個工作表(sheet)= 一張表。一個 .xlsx 有 N 個分頁就建 N 張表。
- 表名:imp_<檔名+分頁的雜湊>,小寫英數、加 imp_ 前綴,與內建 ERP 表隔開、永不撞名;
  同檔同分頁再上傳→同表名→覆蓋重建(drop + recreate)。中文原名存進登記檔的 desc。
- 欄名:保留 Excel 表頭原文(中文也行),在 SQL 裡以雙引號識別字使用。
- 型別:用 pandas 推斷(整數→BIGINT、浮點→DOUBLE PRECISION、布林→BOOLEAN、
  日期→TIMESTAMP、其餘→TEXT),這樣數字欄才能正確聚合/比較;推不準就退 TEXT。
- 登記:寫進 sql_library/schema_imports.json(與 schema.json 同結構),保持人工策展的
  schema.json 乾淨。find_tables 會自動合併兩個檔、並依內容雜湊重建索引。

這是「後台管理」動作(由 API 端點直接呼叫、不經 LLM),不是給 agent 用的 @tool。
"""

import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pandas.api.types as pt
import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://erp@localhost:5433/erp")
_SCHEMA_IMPORTS = Path(__file__).resolve().parent.parent / "sql_library" / "schema_imports.json"


def _table_name(source: str, sheet: str) -> str:
    """由「原檔名 + 分頁名」算出穩定的表名:同檔同分頁→同名→再上傳即覆蓋。"""
    h = hashlib.md5(f"{source}::{sheet}".encode("utf-8")).hexdigest()[:10]
    return f"imp_{h}"


def _q(ident: str) -> str:
    """把識別字(表名/欄名)包成安全的 PostgreSQL 雙引號識別字。"""
    return '"' + ident.replace('"', '""') + '"'


def _clean_columns(cols) -> list[str]:
    """整理欄名:空白/未命名→col_N;截到 63 byte 上限;重複的補序號避免衝突。"""
    out, seen = [], {}
    for i, c in enumerate(cols):
        name = str(c).strip()
        if not name or name.lower().startswith("unnamed"):
            name = f"col_{i + 1}"
        name = name.encode("utf-8")[:63].decode("utf-8", "ignore")  # PG 識別字上限
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def _pg_type(series: pd.Series) -> str:
    """由 pandas 欄位型別推斷 PostgreSQL 欄位型別;認不出就用 TEXT(最安全)。"""
    if pt.is_bool_dtype(series):
        return "BOOLEAN"
    if pt.is_integer_dtype(series):
        return "BIGINT"
    if pt.is_float_dtype(series):
        return "DOUBLE PRECISION"
    if pt.is_datetime64_any_dtype(series):
        return "TIMESTAMP"
    return "TEXT"


def _load_imports() -> dict:
    if _SCHEMA_IMPORTS.exists():
        return json.loads(_SCHEMA_IMPORTS.read_text("utf-8"))
    return {"_comment": "由 tools/excel_import.py 自動產生:使用者上傳的 Excel 匯入表。", "tables": []}


def _register(entry: dict) -> None:
    """把一張匯入表的 schema 登記寫進 schema_imports.json(同名則覆蓋該筆)。"""
    data = _load_imports()
    data["tables"] = [t for t in data["tables"] if t["name"] != entry["name"]] + [entry]
    _SCHEMA_IMPORTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _import_sheet(conn, table: str, df: pd.DataFrame) -> tuple[str, int]:
    """把一個分頁的 DataFrame 建表並灌資料,回傳 (schema 字串, 列數)。"""
    cols = _clean_columns(df.columns)
    df = df.copy()
    df.columns = cols
    types = {c: _pg_type(df[c]) for c in cols}

    # 重建表(覆蓋):DROP 再 CREATE
    col_defs = ", ".join(f"{_q(c)} {types[c]}" for c in cols)
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {_q(table)}")
        cur.execute(f"CREATE TABLE {_q(table)} ({col_defs})")

        # NaN/NaT → None;TEXT 欄一律轉字串避免型別不符
        records = df.astype(object).where(pd.notnull(df), None)
        rows = []
        for row in records.itertuples(index=False, name=None):
            rows.append(tuple(
                (str(v) if types[c] == "TEXT" and v is not None else v)
                for c, v in zip(cols, row)
            ))
        if rows:
            placeholders = ", ".join(["%s"] * len(cols))
            col_list = ", ".join(_q(c) for c in cols)
            cur.executemany(
                f"INSERT INTO {_q(table)} ({col_list}) VALUES ({placeholders})", rows
            )
    conn.commit()

    # schema 字串:沿用 schema.json 的風格,欄名用雙引號標出(中文欄名照樣可用)
    schema_str = f"{table}(" + ", ".join(f'{_q(c)}' for c in cols) + ")"
    return schema_str, len(df)


def import_excel(file_path: str, source_name: str | None = None) -> str:
    """把一個 Excel(.xlsx/.xls)的每個分頁匯入 PostgreSQL,並登記給 sql agent 查詢。

    Args:
        file_path: Excel 檔在後端的完整路徑。
        source_name: 顯示用的原始檔名(預設取 file_path 的檔名)。
    回傳:給後台顯示的友善摘要字串。
    """
    source = source_name or Path(file_path).name
    try:
        sheets = pd.read_excel(file_path, sheet_name=None)  # 全部分頁:{名稱: DataFrame}
    except Exception as e:  # noqa: BLE001
        return f"讀取 Excel 失敗:{e}"

    done = []
    with psycopg.connect(DATABASE_URL) as conn:
        for sheet, df in sheets.items():
            df = df.dropna(how="all").dropna(axis=1, how="all")  # 去掉全空的列/欄
            if df.empty or len(df.columns) == 0:
                continue
            table = _table_name(source, sheet)
            schema_str, n = _import_sheet(conn, table, df)
            _register({
                "name": table,
                "domain": "匯入 Imported",
                "group": "Excel 匯入",
                "desc": f"由 Excel 匯入:原檔「{source}」/ 分頁「{sheet}」,共 {n} 列。",
                "schema": schema_str,
            })
            done.append(f"分頁「{sheet}」→ 資料表 {table}({n} 列、{len(df.columns)} 欄)")

    if not done:
        return f"「{source}」裡沒有可匯入的資料(分頁都是空的)。"
    return f"已匯入「{source}」:\n" + "\n".join(f"  • {d}" for d in done) + \
        "\n\n之後在對話中用自然語言即可查詢這些資料(sql 會自動找到對應的表)。"
