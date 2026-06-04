"""SQL 範例庫 + 語意檢索（retrieval-augmented SQL）。

- 範例庫 sql_library/catalog.json：一份「問題 → 經過驗證的 SQL」清單，每條都實際在資料庫
  跑得通（含真實欄位值，例如請假狀態是『已核准』而非『已批准』）。
- find_sql(question)：用問題語意檢索最相近的幾條，讓 sql_agent「高度命中就直接用、否則當
  few-shot 改寫」。新增 SQL 只要往 catalog.json 加一筆，下次呼叫會自動重建索引。

embedding / 餘弦 / 快取邏輯與 schema 檢索共用 tools/_semantic_index。
"""

import json
from pathlib import Path

from langchain_core.tools import tool

from tools._semantic_index import build_or_load, rank

_DIR = Path(__file__).resolve().parent.parent / "sql_library"
CATALOG_FILE = _DIR / "catalog.json"
INDEX_FILE = _DIR / "index.json"


def _catalog() -> list[dict]:
    return json.loads(CATALOG_FILE.read_text("utf-8")).get("queries", [])


def _text_of(q: dict) -> str:
    return f"{q['question']}。{q.get('note', '')}"


@tool
def find_sql(question: str, k: int = 3) -> str:
    """在「SQL 範例庫」中用語意檢索找出與問題最相近、已驗證可執行的 SQL 範例。

    下任何資料查詢前都先呼叫這個：若回傳的最相近範例與使用者問題幾乎一致（相關度高），
    直接拿它的 SQL 交給 run_sql_query 執行（必要時依問題微調條件即可）；若都不夠相近，
    就把這些範例當作寫法參考（few-shot），再自己組 SQL。範例裡的欄位值都是資料庫真實值。

    Args:
        question: 使用者的查詢問題（自然語言）。
        k: 取回幾條最相近的範例（預設 3）。
    """
    queries = _catalog()
    if not queries:
        return "SQL 範例庫是空的。請先在 sql_library/catalog.json 補上範例。"
    vecs = build_or_load(INDEX_FILE, queries, _text_of)
    hits = rank(question, queries, vecs, k)
    out = [f"找到 {len(hits)} 條最相近的範例 SQL（相關度越高越可直接採用）："]
    for q, score in hits:
        out.append(
            f"\n[{q['id']}]（相關度 {score:.2f}）"
            f"\n  對應問題：{q['question']}"
            f"\n  說明：{q.get('note', '')}"
            f"\n  SQL：{q['sql']}"
        )
    return "\n".join(out)
