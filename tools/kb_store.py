"""RAG 知識庫的 Postgres + pgvector 後端（含 Obsidian [[ ]] 關聯表）。

預設 RAG 仍用 JSON / S3（見 rag_tools）。設 `KB_BACKEND=postgres` 後，知識庫切段、向量與
筆記間的連結改存進 Postgres：
- `kb_chunks`：每段文字 + 向量（pgvector `vector(1536)`）+ 來源 / 雜湊 / 資料夾 / 原檔路徑。
  建了 HNSW 餘弦索引,日後要做 ANN 加速可直接用。
- `kb_links`：筆記間的 [[ ]] 關聯（src_note → dst_note）——Obsidian 的關聯進 DB 後可用 SQL
  直接查反向連結 / 斷鏈 / 孤島，不必再掃檔。

刻意保持與 JSON 後端「相同的 dict 形狀」（{text, source, vec, hash?, folder?, path?}），
所以 rag_tools 的混合檢索（語意 + BM25 + 重排 + 連結感知）一行都不用改。多租戶以 tenant
欄位隔離（與站內信箱、控制面同一套放在 public 的紀律）。
"""

import os
import re
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()

KB_EMBED_DIM = int(os.getenv("KB_EMBED_DIM", "1536"))  # text-embedding-3-small = 1536
DATABASE_URL = os.getenv("KB_DATABASE_URL") or os.getenv(
    "DATABASE_URL", "postgresql://erp@localhost:5433/erp"
)

KB_DDL = f"""
CREATE TABLE IF NOT EXISTS kb_chunks (
    id         BIGSERIAL PRIMARY KEY,
    tenant     TEXT NOT NULL,
    source     TEXT NOT NULL,
    text       TEXT NOT NULL,
    embedding  vector({KB_EMBED_DIM}),
    hash       TEXT,
    folder     TEXT,
    path       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kb_chunks_tenant_idx ON kb_chunks (tenant);
CREATE INDEX IF NOT EXISTS kb_chunks_tenant_source_idx ON kb_chunks (tenant, source);
CREATE INDEX IF NOT EXISTS kb_chunks_embed_idx
    ON kb_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS kb_links (
    tenant   TEXT NOT NULL,
    src_note TEXT NOT NULL,
    dst_note TEXT NOT NULL,
    PRIMARY KEY (tenant, src_note, dst_note)
);
CREATE INDEX IF NOT EXISTS kb_links_dst_idx ON kb_links (tenant, dst_note);
"""


def enabled() -> bool:
    return os.getenv("KB_BACKEND", "").lower() == "postgres"


_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=0,
            max_size=int(os.getenv("KB_POOL_MAX", "5")),
            timeout=5,
            kwargs={"autocommit": True, "connect_timeout": 3},
            configure=register_vector,  # 讓 vector 欄位進出都是 Python list / numpy
            open=True,
        )
    return _pool


@contextmanager
def _conn():
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public")
        yield conn


def ensure_kb() -> None:
    """建立 kb_chunks / kb_links 與索引（冪等）。需先 CREATE EXTENSION vector。"""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(KB_DDL, prepare=False)  # 多語句 DDL 走 simple protocol


# ── 與 rag_tools 對接：load / save 維持相同 dict 形狀 ──────────────────────
def load(tenant: str) -> list[dict]:
    """讀回某租戶全部切段，形狀同 JSON 後端：{text, source, vec, hash, folder, path}。"""
    ensure_kb()
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT text, source, embedding, hash, folder, path "
            "FROM kb_chunks WHERE tenant = %s ORDER BY id",
            (tenant,),
        )
        out = []
        for r in cur.fetchall():
            item = {"text": r["text"], "source": r["source"],
                    "vec": list(r["embedding"]) if r["embedding"] is not None else []}
            if r["hash"]:
                item["hash"] = r["hash"]
            if r["folder"]:
                item["folder"] = r["folder"]
            if r["path"]:
                item["path"] = r["path"]
            out.append(item)
        return out


def save(tenant: str, items: list[dict]) -> None:
    """以「整租戶覆寫」寫回（rag_tools 一律傳該租戶完整清單，與 JSON 全檔重寫語意一致）。

    同時依各段內容的 [[ ]] 重建 kb_links（Obsidian 關聯入庫，可用 SQL 查詢）。
    """
    ensure_kb()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM kb_chunks WHERE tenant = %s", (tenant,))
        for it in items:
            cur.execute(
                "INSERT INTO kb_chunks (tenant, source, text, embedding, hash, folder, path) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (tenant, it["source"], it["text"], it.get("vec"),
                 it.get("hash"), it.get("folder"), it.get("path")),
            )
        _rebuild_links(cur, tenant, items)


# ── Obsidian [[ ]] 關聯 ───────────────────────────────────────────────────
def _rebuild_links(cur, tenant: str, items: list[dict]) -> None:
    """由各段文字的 [[標題]] 重算筆記關聯，整租戶覆寫 kb_links。"""
    text_by_note: dict[str, list[str]] = {}
    for it in items:
        text_by_note.setdefault(it["source"], []).append(it["text"])
    title_to_src = {Path(s).stem: s for s in text_by_note}
    edges = set()
    for src, chunks in text_by_note.items():
        for raw in re.findall(r"\[\[([^\]]+)\]\]", "\n".join(chunks)):
            tgt = raw.split("|")[0].split("#")[0].strip()  # 去別名/錨點
            dst = title_to_src.get(tgt)
            if dst and dst != src:
                edges.add((src, dst))
    cur.execute("DELETE FROM kb_links WHERE tenant = %s", (tenant,))
    for src, dst in edges:
        cur.execute(
            "INSERT INTO kb_links (tenant, src_note, dst_note) VALUES (%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (tenant, src, dst),
        )


def graph_stats(tenant: str) -> dict:
    """關聯圖狀態（給後台/查詢用）：連結數、斷鏈（連到不存在的筆記）、孤島（無進出連結）。"""
    ensure_kb()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source FROM kb_chunks WHERE tenant = %s", (tenant,))
        notes = {Path(r[0]).stem for r in cur.fetchall()}
        cur.execute("SELECT src_note, dst_note FROM kb_links WHERE tenant = %s", (tenant,))
        edges = cur.fetchall()
    linked = set()
    broken = set()
    for src, dst in edges:
        linked.add(Path(src).stem)
        if Path(dst).stem in notes:
            linked.add(Path(dst).stem)
        else:
            broken.add(Path(dst).stem)
    orphans = sorted(notes - linked)
    return {"notes": len(notes), "links": len(edges),
            "broken": sorted(broken), "orphans": orphans}


def backlinks(tenant: str, note: str) -> list[str]:
    """某筆記的反向連結（哪些筆記連到它）。note 可給 source 或標題。"""
    ensure_kb()
    stem = Path(note).stem
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT src_note FROM kb_links WHERE tenant = %s "
            "AND (dst_note = %s OR split_part(dst_note,'.',1) = %s)",
            (tenant, note, stem),
        )
        return [r[0] for r in cur.fetchall()]
