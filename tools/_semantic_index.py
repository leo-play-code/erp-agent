"""tools 內部共用的輕量語意索引（非 Tool，是基礎元件）。

給「SQL 範例庫」(find_sql) 與「schema 檢索」(find_tables) 共用，避免各自重寫 embedding /
餘弦 / 快取邏輯。刻意零重量級依賴：OpenAI embedding（text-embedding-3-small）+ 純 Python
餘弦，索引快取成 JSON，以「被嵌入文字」的雜湊為 key —— 內容變了才重嵌，否則直接載入，
不重複花 embedding 費用。資料量很大時再換成真正的向量資料庫即可，呼叫端介面不變。
"""

import hashlib
import json
import math
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()

EMBED_MODEL = "text-embedding-3-small"


def _embeddings():
    return OpenAIEmbeddings(model=EMBED_MODEL, api_key=os.getenv("OPENAI_API_KEY"))


def _hash(texts: list[str]) -> str:
    return hashlib.md5("\n".join(texts).encode("utf-8")).hexdigest()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def build_or_load(index_path, records: list[dict], text_of) -> list[list[float]]:
    """取得（必要時重建）records 的向量，順序與 records 對應。

    Args:
        index_path: 索引快取檔路徑。
        records: 要嵌入的資料（list[dict]）。
        text_of: record -> 要拿去嵌入的字串。
    內容雜湊與快取相同就直接載入；否則重嵌並寫回。
    """
    texts = [text_of(r) for r in records]
    h = _hash(texts)
    p = Path(index_path)
    if p.exists():
        cached = json.loads(p.read_text("utf-8"))
        if cached.get("hash") == h and len(cached.get("vecs", [])) == len(records):
            return cached["vecs"]
    vecs = _embeddings().embed_documents(texts)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"hash": h, "vecs": vecs}, ensure_ascii=False), "utf-8")
    return vecs


def rank(query: str, records: list[dict], vecs: list[list[float]], k: int):
    """把 query 向量化，對 records 算餘弦相似度，回傳 [(record, score), ...] 取前 k 筆。"""
    qv = _embeddings().embed_query(query)
    scored = [(r, _cosine(qv, v)) for r, v in zip(records, vecs)]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[: max(1, k)]
