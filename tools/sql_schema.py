"""資料庫 schema 的「單一來源」與檢索工具。

- 來源：sql_library/schema.json（結構化，每張表一筆）。新增資料表只改這個檔。
- full_schema_text() / SCHEMA_OVERVIEW：把所有表渲染成完整總覽字串。表不多時（或需要
  跨領域整體視野的 analyst）直接用它。
- find_tables(question)：表很多時用，只檢索「與問題相關的幾張表」的 schema，不必把整個
  資料庫塞進 prompt —— 這是讓系統能撐住「大量資料表」的關鍵（schema linking）。

與 sql_library 共用 tools/_semantic_index 的 embedding/餘弦/快取，不重複造輪子。
"""

import json
from pathlib import Path

from langchain_core.tools import tool

from tools._semantic_index import build_or_load, rank

_DIR = Path(__file__).resolve().parent.parent / "sql_library"
SCHEMA_FILE = _DIR / "schema.json"
SCHEMA_INDEX = _DIR / "schema_index.json"


def _load() -> dict:
    return json.loads(SCHEMA_FILE.read_text("utf-8"))


def full_schema_text() -> str:
    """把 schema.json 渲染成完整 schema 總覽（依領域/主檔交易分組），給需要整體視野者用。"""
    data = _load()
    grouped: dict[str, dict[str, list[dict]]] = {}
    domain_order: list[str] = []
    for t in data["tables"]:
        dom = t["domain"]
        if dom not in grouped:
            grouped[dom] = {}
            domain_order.append(dom)
        grouped[dom].setdefault(t.get("group", ""), []).append(t)

    lines = ["資料庫（PostgreSQL）共兩大領域：", ""]
    for dom in domain_order:
        lines.append(f"【{dom}】")
        for grp, tables in grouped[dom].items():
            if grp:
                lines.append(f"{grp}：")
            lines += [f"- {t['schema']}" for t in tables]
        lines.append("")
    lines.append(data.get("glossary", ""))
    return "\n".join(lines).strip()


# 完整總覽字串（單一來源；analyst 與「表不多時」直接 import 這個）
SCHEMA_OVERVIEW = full_schema_text()


def _text_of(t: dict) -> str:
    return f"{t['name']}：{t.get('desc', '')}。欄位：{t['schema']}"


@tool
def find_tables(question: str, k: int = 6) -> str:
    """在資料庫 schema 中，用語意檢索找出與問題最相關的資料表（含欄位、外鍵與合法值）。

    當你需要自己寫 SQL、又不確定該碰哪些表時用這個：它只回傳相關的幾張表，不會把整個
    資料庫塞進來。回傳內容附上常用 KPI 算法。請「只根據回傳的表」寫 SQL。

    Args:
        question: 使用者的查詢問題（自然語言）。
        k: 取回幾張最相關的資料表（預設 6）。
    """
    data = _load()
    tables = data["tables"]
    vecs = build_or_load(SCHEMA_INDEX, tables, _text_of)
    hits = rank(question, tables, vecs, k)
    out = [f"與問題最相關的 {len(hits)} 張資料表（→ 表示外鍵關聯）："]
    for t, score in hits:
        out.append(f"\n- {t['schema']}\n  （{t.get('desc', '')}；相關度 {score:.2f}）")
    glossary = data.get("glossary", "")
    if glossary:
        out.append(f"\n{glossary}")
    return "\n".join(out)
