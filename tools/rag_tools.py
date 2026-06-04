"""RAG 知識庫工具 —— 丟文件進去自動建索引，之後用自然語言查回相關內容。

設計（刻意輕量、零額外依賴）：
- 向量：用 OpenAI 的 text-embedding-3-small（透過 langchain_openai，專案本來就有）。
- 索引：純 Python 存成一個 JSON 檔（rag_index/index.json），含每段文字、來源與向量；
  持久化在磁碟，程式重開、之後再查都還在。
- 相似度：純 Python 餘弦相似度（不需要 numpy / faiss / chroma）。
  資料量大時應改用真正的向量資料庫，但這已能做到「丟資料→建索引→查得到」。
"""

import hashlib
import json
import math
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from pypdf import PdfReader

load_dotenv()

INDEX_DIR = Path(__file__).resolve().parent.parent / "rag_index"
INDEX_FILE = INDEX_DIR / "index.json"
EMBED_MODEL = "text-embedding-3-small"


# ── 索引存取 ───────────────────────────────────────────────────────────
def _embeddings():
    return OpenAIEmbeddings(model=EMBED_MODEL, api_key=os.getenv("OPENAI_API_KEY"))


def _load() -> list[dict]:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text("utf-8")).get("items", [])
    return []


def _save(items: list[dict]) -> None:
    INDEX_DIR.mkdir(exist_ok=True)
    INDEX_FILE.write_text(json.dumps({"items": items}, ensure_ascii=False), "utf-8")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _chunk(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    """把長文字切成有重疊的小段，盡量在換行/空白處斷句。"""
    text = text.strip()
    chunks, i, n = [], 0, len(text)
    while i < n:
        end = min(i + size, n)
        if end < n:  # 試著斷在換行或空白，避免切到句子中間
            br = text.rfind("\n", i, end)
            if br < i + size // 2:
                br = text.rfind(" ", i, end)
            if br > i + size // 2:
                end = br
        seg = text[i:end].strip()
        if seg:
            chunks.append(seg)
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return chunks


def _file_hash(p: Path) -> str:
    """檔案內容雜湊；用來判斷某個檔有沒有變動（變了才重新建索引）。"""
    return hashlib.md5(p.read_bytes()).hexdigest()


def _read_file(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        pages = [(pg.extract_text() or "") for pg in PdfReader(str(p)).pages]
        return "\n".join(pages)
    return p.read_text("utf-8", errors="ignore")


def _add(chunks: list[str], source: str, path: str | None = None) -> int:
    """把多段文字嵌入並加進索引，回傳新增段數。

    path：原檔在後端的保存路徑（選填）；有給就記進每段，供日後重嵌 / 下載 / 追溯。
    """
    chunks = [c for c in chunks if c.strip()]
    if not chunks:
        return 0
    vecs = _embeddings().embed_documents(chunks)
    items = _load()
    items.extend(
        {"text": c, "source": source, "vec": v, **({"path": path} if path else {})}
        for c, v in zip(chunks, vecs)
    )
    _save(items)
    return len(chunks)


# ── 工具 ───────────────────────────────────────────────────────────────
@tool
def ingest_file(file_path: str) -> str:
    """把一個檔案（PDF 或純文字 .txt/.md）讀進來、切塊、建立向量索引，加入知識庫。

    使用者上傳檔案要「加入知識庫 / 建索引」時用這個。索引會存檔，之後可用 search_knowledge_base 查。

    Args:
        file_path: 檔案完整路徑（訊息中「已上傳檔案路徑：…」的那個路徑）。
    """
    try:
        text = _read_file(file_path)
    except Exception as e:  # noqa: BLE001
        return f"讀取檔案失敗：{e}"
    if not text.strip():
        return "這個檔案沒有可擷取的文字（可能是掃描檔或空檔），無法建索引。"
    n = _add(_chunk(text), Path(file_path).name, path=str(Path(file_path).resolve()))
    return f"已將「{Path(file_path).name}」加入知識庫：新增 {n} 段，目前知識庫共 {len(_load())} 段。"


@tool
def ingest_text(text: str, source: str = "貼上的內容") -> str:
    """把一段文字內容切塊、建立向量索引，加入知識庫。

    使用者直接貼一段資料（如公司規章、產品說明）要你「記起來 / 加入知識庫」時用這個。

    Args:
        text: 要加入知識庫的文字內容。
        source: 這段內容的來源標籤（選填，方便日後標示出處）。
    """
    if not text.strip():
        return "內容是空的，沒有東西可以加入。"
    n = _add(_chunk(text), source)
    return f"已加入知識庫：新增 {n} 段（來源：{source}），目前共 {len(_load())} 段。"


@tool
def sync_folder(folder_path: str) -> str:
    """指定一個資料夾，把裡面所有文件（PDF / .txt / .md，含子資料夾）自動建成知識庫索引。

    這是「增量同步」：用檔案內容雜湊比對，只重新建索引「有變動的單一檔」，沒變的略過、
    已從資料夾刪掉的檔也會從索引移除。之後檔案有更動，再呼叫一次本工具即可只更新那幾筆。

    Args:
        folder_path: 資料夾完整路徑。
    """
    base = Path(folder_path).expanduser()
    if not base.is_dir():
        return f"找不到資料夾「{folder_path}」（請給一個存在的資料夾路徑）。"
    exts = {".txt", ".md", ".markdown", ".pdf"}
    files = sorted(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in exts)
    folder_key = str(base)
    items = _load()
    # 此資料夾過去同步過的：source（相對路徑）-> 內容雜湊
    existing = {it["source"]: it.get("hash") for it in items if it.get("folder") == folder_key}

    present, added, updated, skipped, failed = set(), 0, 0, 0, 0
    for p in files:
        src = str(p.relative_to(base))
        present.add(src)
        h = _file_hash(p)
        if existing.get(src) == h:  # 沒變 → 略過
            skipped += 1
            continue
        if src in existing:  # 內容變了 → 先移除該檔舊 chunks，再重嵌
            items = [it for it in items
                     if not (it.get("folder") == folder_key and it.get("source") == src)]
            updated += 1
        else:
            added += 1
        try:
            chunks = _chunk(_read_file(str(p)))
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        if not chunks:
            continue
        vecs = _embeddings().embed_documents(chunks)
        items.extend(
            {"text": c, "source": src, "vec": v, "hash": h, "folder": folder_key}
            for c, v in zip(chunks, vecs)
        )

    # 資料夾內已刪除的檔 → 從索引移除
    removed = [s for s in existing if s not in present]
    if removed:
        items = [it for it in items
                 if not (it.get("folder") == folder_key and it.get("source") in removed)]
    if added or updated or removed:  # 有變動才寫回檔（自動監看會頻繁呼叫，省去無謂磁碟寫入）
        _save(items)
    if not (added or updated or removed):
        tail = f"（讀取失敗 {failed}）" if failed else ""
        return f"已檢查資料夾「{base.name}」（{len(files)} 個文件）：無變動{tail}。知識庫共 {len(items)} 段。"
    parts = [f"新增 {added}", f"更新 {updated}", f"未變略過 {skipped}"]
    if removed:
        parts.append(f"移除已刪檔 {len(removed)}")
    if failed:
        parts.append(f"讀取失敗 {failed}")
    return (f"已同步資料夾「{base.name}」（共掃到 {len(files)} 個文件）："
            + "、".join(parts) + f"。知識庫目前共 {len(items)} 段。")


@tool
def search_knowledge_base(query: str, k: int = 4) -> str:
    """在知識庫中找出與問題最相關的內容片段（語意向量檢索），回傳片段與來源供回答依據。

    回答使用者問題前先用這個取回資料，再「只根據取回的內容」作答並標來源。

    Args:
        query: 使用者的問題或查詢關鍵字。
        k: 取回幾段最相關內容（預設 4）。
    """
    items = _load()
    if not items:
        return "知識庫目前是空的。請先上傳檔案（ingest_file）或貼上內容（ingest_text）建立索引。"
    qv = _embeddings().embed_query(query)
    ranked = sorted(items, key=lambda it: _cosine(qv, it["vec"]), reverse=True)[: max(1, k)]
    out = [f"檢索到 {len(ranked)} 段最相關內容："]
    for i, it in enumerate(ranked, 1):
        score = _cosine(qv, it["vec"])
        out.append(f"\n[{i}] 來源：{it['source']}（相關度 {score:.2f}）\n{it['text']}")
    return "\n".join(out)


@tool
def kb_stats() -> str:
    """查看知識庫目前有哪些來源、共幾段內容。無參數。"""
    items = _load()
    if not items:
        return "知識庫目前是空的。"
    sources: dict[str, int] = {}
    for it in items:
        sources[it["source"]] = sources.get(it["source"], 0) + 1
    lines = [f"知識庫共 {len(items)} 段，來自 {len(sources)} 個來源："]
    lines += [f"  - {s}：{c} 段" for s, c in sources.items()]
    return "\n".join(lines)


def kb_summary() -> dict:
    """知識庫現況的「結構化」版本（給後台 UI 用，非工具）：總段數、來源數、各來源段數。"""
    items = _load()
    counts: dict[str, int] = {}
    for it in items:
        counts[it["source"]] = counts.get(it["source"], 0) + 1
    return {
        "total_segments": len(items),
        "source_count": len(counts),
        "sources": [{"name": s, "segments": c} for s, c in counts.items()],
    }
