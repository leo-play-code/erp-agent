"""RAG 知識庫工具 —— 丟文件進去自動建索引，之後用自然語言查回相關內容。

設計（刻意輕量、零額外依賴）：
- 向量：用 OpenAI 的 text-embedding-3-small（透過 langchain_openai，專案本來就有）。
- 索引：純 Python 存成一個 JSON 檔（rag_index/index.json），含每段文字、來源與向量；
  持久化在磁碟，程式重開、之後再查都還在。
- 相似度：純 Python 餘弦相似度（不需要 numpy / faiss / chroma）。
  資料量大時應改用真正的向量資料庫，但這已能做到「丟資料→建索引→查得到」。
- 檢索：search_knowledge_base 採「混合檢索」——語意餘弦 + 關鍵字 BM25（純 Python）以 RRF
  融合，再加多重查詢改寫與 LLM 重排，盡量讓確實在庫裡的資料不被漏掉（見該函式上方說明）。
"""

import functools
import hashlib
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from markitdown import MarkItDown
from pypdf import PdfReader  # markitdown 轉換失敗時的 PDF 後援

from tools.tenant import get_tenant  # 多租戶：每使用者一個獨立知識庫

load_dotenv()

INDEX_DIR = Path(__file__).resolve().parent.parent / "rag_index"
INDEX_FILE = INDEX_DIR / "index.json"
EMBED_MODEL = "text-embedding-3-small"

# 索引持久化（白皮書 §25：RAG 索引也是「狀態」，多 replica/跨節點要共用才不會擴展就掉資料）。
# 設了 S3_ENDPOINT_URL+S3_BUCKET → 索引存物件儲存（MinIO/S3）；沒設 → 退回本地檔（單機開發）。
# **多租戶**：每使用者一份索引——key = rag/<tenant>/index.json（default 租戶沿用舊路徑以相容）。
# 用 etag 記憶體快取（per-tenant）：每次只做輕量 head 檢查，內容沒變就用記憶體、不重抓整包。
_idx_cache: dict = {}  # tenant -> {"etag":..., "items":...}


def _index_key() -> str:
    t = get_tenant()
    return "rag/index.json" if t == "default" else f"rag/{t}/index.json"


def _local_index_file() -> Path:
    t = get_tenant()
    return INDEX_FILE if t == "default" else INDEX_DIR / t / "index.json"


def _s3_enabled() -> bool:
    return bool(os.getenv("S3_ENDPOINT_URL") and os.getenv("S3_BUCKET"))


def _kb_pg_enabled() -> bool:
    """設 KB_BACKEND=postgres → 知識庫切段/向量/[[ ]]關聯改存 Postgres（pgvector）。"""
    return os.getenv("KB_BACKEND", "").lower() == "postgres"


@functools.lru_cache(maxsize=1)
def _s3():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
    )


# ── 索引存取 ───────────────────────────────────────────────────────────
def _embeddings():
    return OpenAIEmbeddings(model=EMBED_MODEL, api_key=os.getenv("OPENAI_API_KEY"))


def _load() -> list[dict]:
    tenant = get_tenant()
    if _kb_pg_enabled():  # Postgres + pgvector 後端（含 Obsidian 關聯入庫）
        from tools import kb_store
        return kb_store.load(tenant)
    if _s3_enabled():
        from botocore.exceptions import ClientError

        bucket, key = os.getenv("S3_BUCKET"), _index_key()
        cache = _idx_cache.get(tenant)
        try:
            etag = _s3().head_object(Bucket=bucket, Key=key)["ETag"]
            if cache and cache["etag"] == etag:
                return cache["items"]  # 沒變：用記憶體快取，不重抓
            obj = _s3().get_object(Bucket=bucket, Key=key)
            items = json.loads(obj["Body"].read().decode("utf-8")).get("items", [])
            _idx_cache[tenant] = {"etag": etag, "items": items}
            return items
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return []  # 這個租戶還沒建過索引
            return cache["items"] if cache else []  # 連線等問題：退回快取/空，別讓查詢炸掉
    f = _local_index_file()
    if f.exists():
        return json.loads(f.read_text("utf-8")).get("items", [])
    return []


def _save(items: list[dict]) -> None:
    tenant = get_tenant()
    if _kb_pg_enabled():
        from tools import kb_store
        kb_store.save(tenant, items)
        return
    if _s3_enabled():
        bucket = os.getenv("S3_BUCKET")
        body = json.dumps({"items": items}, ensure_ascii=False).encode("utf-8")
        resp = _s3().put_object(
            Bucket=bucket, Key=_index_key(), Body=body, ContentType="application/json"
        )
        _idx_cache[tenant] = {"etag": resp.get("ETag"), "items": items}
        return
    f = _local_index_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"items": items}, ensure_ascii=False), "utf-8")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# 章節邊界：Markdown 標題（#…）或「第N條」條文標記，遇到就另起一段，避免不同主題混在一塊。
# 刻意不把「一、二、」當邊界——同一條文下的並列項（如薪資發放的一/二/三/四款）本就該留在一起。
_ARTICLE_RE = re.compile(r"^\s*第[一二三四五六七八九十百零0-9]+條")


def _has_content(s: str) -> bool:
    """濾掉 PDF 抽取殘渣（直書括號 ︵︶、零星符號等）：有效字元（中日韓文/英數）<4 就視為無意義。
    門檻刻意壓低，連『第二十八條 休假日工作』這種本來就短的真條文都會保留。"""
    return len(re.findall(r"\w", s)) >= 4


def _char_split(text: str, size: int, overlap: int) -> list[str]:
    """字元視窗切法（原邏輯）：在換行/空白處斷句、段間留 overlap。供單一過長區塊內部細切用。"""
    text = text.strip()
    out, i, n = [], 0, len(text)
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
            out.append(seg)
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return out


def _table_split(table: str, size: int) -> list[str]:
    """表格過長時以「整列」為單位切，不切斷單列；每段盡量帶上表頭兩行（標題 + 分隔線）。"""
    rows = table.splitlines()
    header = rows[:2] if len(rows) >= 2 and set(rows[1].strip()) <= set("|-: ") else []
    out, cur = [], list(header)
    for r in rows[len(header):]:
        if len(cur) > len(header) and sum(len(x) for x in cur) + len(r) > size:
            out.append("\n".join(cur))
            cur = list(header)
        cur.append(r)
    if len(cur) > len(header):
        out.append("\n".join(cur))
    return out


def _blocks(text: str) -> list[str]:
    """依結構把文字切成語意區塊：標題行 / 條文標記另起一塊；連續的表格列（| 開頭）自成原子塊。"""
    blocks, cur, in_table = [], [], False

    def flush():
        seg = "\n".join(cur).strip()
        if seg:
            blocks.append(seg)
        cur.clear()

    for line in text.splitlines():
        is_table = line.lstrip().startswith("|")
        if is_table != in_table:  # 進入或離開表格 → 斷塊（表格整體獨立）
            flush()
            in_table = is_table
        elif not is_table and (line.lstrip().startswith("#") or _ARTICLE_RE.match(line)):
            flush()  # 遇到標題 / 條文 → 另起新塊
        cur.append(line)
    flush()
    return blocks


def _chunk(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    """結構感知切塊：先依 markitdown 的結構（標題 / 條文 / 表格）切成語意區塊，
    再把同區塊內過長的細切、表格不切碎。每段語意單純，embedding 才銳利、檢索才準。

    刻意不跨「章節邊界」合併區塊——不同條文混在一段會稀釋語意（這正是先前發薪規定查不到的主因）。
    無結構的純文字（沒有標題/條文/表格）會退化成原本的字元視窗切法，行為不變。
    """
    text = text.strip()
    if not text:
        return []

    # 打包：把相鄰的小區塊併到接近 size，減少無意義微碎片；但「條文/標題起始」與「表格」
    # 一律不與前文合併——保住每條文語意純淨、表格原子完整。
    packed: list[str] = []
    buf = ""
    for blk in _blocks(text):
        starts_section = (
            blk.lstrip().startswith(("#", "|")) or bool(_ARTICLE_RE.match(blk))
        )
        buf_is_table = buf.lstrip().startswith("|") if buf else False
        if not buf:
            buf = blk
        elif starts_section or buf_is_table or len(buf) + 1 + len(blk) > size:
            packed.append(buf)
            buf = blk
        else:
            buf += "\n" + blk
    if buf:
        packed.append(buf)

    # 仍超長的區塊才細切：表格以整列切、其餘走字元視窗。
    chunks: list[str] = []
    for blk in packed:
        if len(blk) <= size:
            chunks.append(blk)
        elif blk.lstrip().startswith("|"):
            chunks.extend(_table_split(blk, size))
        else:
            chunks.extend(_char_split(blk, size, overlap))
    return [c for c in (c.strip() for c in chunks) if _has_content(c)]


def _file_hash(p: Path) -> str:
    """檔案內容雜湊；用來判斷某個檔有沒有變動（變了才重新建索引）。"""
    return hashlib.md5(p.read_bytes()).hexdigest()


_md_converter = None


def _markitdown() -> MarkItDown:
    """延遲建立 markitdown 轉換器（單例，避免每次讀檔重建）。"""
    global _md_converter
    if _md_converter is None:
        _md_converter = MarkItDown(enable_plugins=False)
    return _md_converter


def _read_file(path: str) -> str:
    """把檔案轉成文字 / Markdown 供建索引。

    優先用 markitdown 統一轉換：Excel / Word / PowerPoint / CSV / HTML / PDF 等都會被
    轉成乾淨的 Markdown（表格、標題都保留），正是 RAG 切塊、嵌入最好吃的格式。
    萬一轉換失敗或轉不出內容，退回 pypdf（PDF）/ 純文字讀取，確保不會比原本更差。
    """
    p = Path(path)
    try:
        text = (_markitdown().convert(str(p)).text_content or "").strip()
        if text:
            return text
    except Exception:  # noqa: BLE001  轉換失敗就走下面的後援讀法
        pass
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
    """把一個檔案讀進來、切塊、建立向量索引，加入知識庫。

    支援格式（透過 markitdown 轉換）：Excel(.xlsx/.xls)、Word(.docx)、PowerPoint(.pptx)、
    CSV、HTML、PDF、純文字(.txt/.md) 等。表格類檔（Excel/CSV）會轉成 Markdown 表格再建索引。
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
    """指定一個資料夾，把裡面所有文件（Excel/Word/PPT/CSV/PDF/純文字等，含子資料夾）自動建成知識庫索引。

    這是「增量同步」：用檔案內容雜湊比對，只重新建索引「有變動的單一檔」，沒變的略過、
    已從資料夾刪掉的檔也會從索引移除。之後檔案有更動，再呼叫一次本工具即可只更新那幾筆。

    Args:
        folder_path: 資料夾完整路徑。
    """
    base = Path(folder_path).expanduser()
    if not base.is_dir():
        return f"找不到資料夾「{folder_path}」（請給一個存在的資料夾路徑）。"
    exts = {
        ".txt", ".md", ".markdown", ".pdf",
        ".docx", ".pptx", ".xlsx", ".xls", ".csv",  # 透過 markitdown 轉換
        ".html", ".htm", ".json", ".xml",
    }
    files = sorted(
        p for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in exts
        # 略過隱藏資料夾/檔(如 Obsidian 的 .obsidian 設定、.git 等),不把工具設定當知識索引
        and not any(part.startswith(".") for part in p.relative_to(base).parts)
    )
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


# ── 混合檢索（語意 + 關鍵字 + 多重查詢 + 重排）────────────────────────────
# 目標：像搜尋引擎一樣「不漏」。純語意檢索抓得到意思、卻常擠掉「字面精確」的東西
# （料號、人名、專有名詞、金額）；純關鍵字抓得到字面、卻不懂同義。兩者並用 + 改寫問法
# + 重排，才能把「明明在知識庫裡」的資料穩定撈回來。
def _tokenize(s: str) -> list[str]:
    """混合斷詞：英數詞（料號/代號/英文）原樣保留；中文用「單字 + 相鄰雙字」，
    讓 BM25 既能命中精確字面、又容忍少量斷詞差異（中文無空白，無外部斷詞器時的通用作法）。"""
    s = s.lower()
    ascii_tok = re.findall(r"[a-z0-9][a-z0-9_\-./]*", s)
    cjk = re.findall(r"[一-鿿]", s)
    bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return ascii_tok + cjk + bigrams


def _bm25_scores(query: str, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """對每段算 BM25 關鍵字分數（純 Python，零依賴）。docs 是各段已斷好的 token 清單。"""
    n = len(docs)
    if n == 0:
        return []
    avgdl = sum(len(d) for d in docs) / n or 1.0
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    q_terms = set(_tokenize(query))
    scores = [0.0] * n
    for i, d in enumerate(docs):
        if not d:
            continue
        tf: dict[str, int] = {}
        for t in d:
            tf[t] = tf.get(t, 0) + 1
        dl = len(d)
        s = 0.0
        for t in q_terms:
            f = tf.get(t)
            if not f:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / avgdl))
        scores[i] = s
    return scores


def _rrf_fuse(score_lists: list[list[float]], n: int, k0: int = 60) -> list[float]:
    """Reciprocal Rank Fusion：把多組「量綱不同」的分數（餘弦、BM25）依各自排名融合成
    單一分數，不需要正規化。每組各自排名，名次越前貢獻 1/(k0+rank) 越大。"""
    fused = [0.0] * n
    for scores in score_lists:
        order = sorted(range(n), key=lambda i: scores[i], reverse=True)
        for rank, idx in enumerate(order):
            fused[idx] += 1.0 / (k0 + rank)
    return fused


def _expand_query(query: str) -> list[str]:
    """用 LLM 把問題改寫成數種等義說法（正式用語 / 同義詞 / 精確關鍵字），擴大召回。
    失敗或沒有 LLM 就只用原問題，不影響主流程。"""
    variants: list[str] = []
    try:
        from agents.base_agent import get_llm

        prompt = (
            "你是檢索助手。把下面的查詢改寫成 3 種不同說法，分別涵蓋正式用語、同義詞、"
            "精確關鍵字，用來在公司知識庫做全文與語意檢索。每行一種，只輸出改寫結果，"
            "不要編號、不要解釋。\n\n查詢：" + query
        )
        content = get_llm().invoke(prompt).content
        variants = [ln.strip(" -•　\t") for ln in content.splitlines() if ln.strip()]
    except Exception:  # noqa: BLE001  改寫失敗就只用原問題
        pass
    seen, out = set(), []
    for q in [query, *variants]:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:4]


def _rerank(query: str, candidates: list[dict], k: int) -> list[dict]:
    """用 LLM 對候選段落做相關性重排，把真正答得了問題的段落提到最前面（取前 k 段）。
    失敗就退回候選池原順序的前 k 段（即混合檢索結果），不影響主流程。"""
    if len(candidates) <= k:
        return candidates
    try:
        from agents.base_agent import get_llm

        listing = "\n".join(f"[{i}] {c['text'][:400]}" for i, c in enumerate(candidates))
        prompt = (
            f"使用者問題：{query}\n\n"
            f"以下為候選資料片段。請依「最能直接回答問題」到「次相關」列出其編號"
            f"（最多 {k} 個），只輸出編號、用逗號分隔；都不相關就輸出 none。\n\n{listing}"
        )
        resp = get_llm().invoke(prompt).content.strip()
        order = [int(x) for x in re.findall(r"\d+", resp)]
        picked = [candidates[i] for i in order if 0 <= i < len(candidates)]
        if picked:
            chosen = {id(c) for c in picked}
            for c in candidates:  # 不足 k 段時，依候選池原順序補滿，確保提供足夠上下文
                if len(picked) >= k:
                    break
                if id(c) not in chosen:
                    picked.append(c)
            return picked[:k]
    except Exception:  # noqa: BLE001  重排失敗就用混合檢索原順序
        pass
    return candidates[:k]


def _note_graph(items: list[dict]):
    """由索引重建「筆記→全文」與 [[ ]] 連結圖,供連結感知檢索用。

    source 形如「婚假.md」;[[ ]] 目標是筆記標題(無副檔名)。回傳:
    text_by_note(來源→各段文字)、outlinks(來源→它連到的來源集合)、backlinks(反向)。
    """
    text_by_note: dict[str, list[str]] = defaultdict(list)
    for it in items:
        text_by_note[it["source"]].append(it["text"])
    title_to_src = {Path(s).stem: s for s in text_by_note}
    outlinks: dict[str, set] = defaultdict(set)
    for src, chunks in text_by_note.items():
        for raw in re.findall(r"\[\[([^\]]+)\]\]", "\n".join(chunks)):
            tgt = raw.split("|")[0].split("#")[0].strip()  # 去別名/錨點
            dst = title_to_src.get(tgt)
            if dst and dst != src:
                outlinks[src].add(dst)
    backlinks: dict[str, set] = defaultdict(set)
    for src, tgts in outlinks.items():
        for t in tgts:
            backlinks[t].add(src)
    return text_by_note, outlinks, backlinks


@tool
def search_knowledge_base(query: str, k: int = 8) -> str:
    """在知識庫中找出與問題最相關的內容片段，回傳片段與來源供回答依據。

    採「混合檢索」：同時用語意向量（懂意思）＋ 關鍵字 BM25（認字面），並把問題自動改寫成
    多種說法擴大召回，再用 LLM 重排，盡量讓「確實存在於知識庫」的資料不被漏掉。
    此外會順著筆記間的 [[ ]] 連結，把命中筆記「相連的相關筆記」一併帶出（標為「🔗 相關連結筆記」），
    讓散在多篇、靠連結串起來的資料一起浮現，供延伸參考。
    回答使用者問題前先用這個取回資料，再「只根據取回的內容」作答並標來源。

    Args:
        query: 使用者的問題或查詢關鍵字。
        k: 最終回傳幾段（預設 8；內部會先取較大候選池再重排，取窄了易漏抽正確段落）。
    """
    items = _load()
    if not items:
        return "知識庫目前是空的。請先上傳檔案（ingest_file）或貼上內容（ingest_text）建立索引。"

    # ① 多重查詢：把問題改寫成多種等義說法，擴大召回
    queries = _expand_query(query)

    # ② 語意檢索：每種問法各算一次餘弦，得到多組分數
    qvecs = _embeddings().embed_documents(queries)
    sem_scores = [[_cosine(qv, it["vec"]) for it in items] for qv in qvecs]

    # ②-1 信心門檻（Phase 1）：若連最相關片段的語意相似度都過低，代表知識庫沒有相關資料，
    #      直接誠實拒答，不把不相關片段丟給 LLM 硬湊答案。門檻可用環境變數 RAG_MIN_SCORE 調整
    #      （實測：庫內問題約 0.65~0.83、庫外約 0.26~0.30，預設 0.40 取中間安全帶）。
    min_score = float(os.getenv("RAG_MIN_SCORE", "0.40"))
    best_sem = max((max(s) for s in sem_scores if s), default=0.0)
    if best_sem < min_score:
        return (f"知識庫中查不到與此問題足夠相關的資料（最高相關度 {best_sem:.2f}，"
                f"低於門檻 {min_score:.2f}）。建議到「知識庫管理」上傳相關文件或同步資料夾後再問。")

    # ③ 關鍵字檢索（BM25）：補語意抓不到的精確字面（料號、人名、專有名詞、金額）
    docs_tokens = [_tokenize(it["text"]) for it in items]
    kw_scores = _bm25_scores(" ".join(queries), docs_tokens)

    # ④ RRF 融合語意 + 關鍵字所有排名，取候選池（取較大池，避免正解被早早截掉）
    fused = _rrf_fuse([*sem_scores, kw_scores], len(items))
    pool_n = min(len(items), max(30, k * 4))
    pool_idx = sorted(range(len(items)), key=lambda i: fused[i], reverse=True)[:pool_n]
    candidates = [items[i] for i in pool_idx]

    # ⑤ 重排：從候選池挑出真正回答得了問題的前 k 段
    ranked = _rerank(query, candidates, k)

    out = [f"檢索到 {len(ranked)} 段最相關內容（混合檢索：語意＋關鍵字，已重排）："]
    for i, it in enumerate(ranked, 1):
        out.append(f"\n[{i}] 來源：{it['source']}\n{it['text']}")

    # ⑥ 連結感知:順著 [[ ]] 把命中筆記「相連的筆記」也帶出(Obsidian 關聯;一跳、去重、設上限）。
    #    讓散在多篇、靠連結串起來的資料一起浮現;無 [[ ]] 連結的知識庫此段自動為空。
    text_by_note, outlinks, backlinks = _note_graph(items)
    seeds = list(dict.fromkeys(it["source"] for it in ranked))  # 命中的來源(保序去重)
    seen, neighbors = set(seeds), []
    for s in seeds:
        for nb in sorted(outlinks.get(s, set()) | backlinks.get(s, set())):
            if nb not in seen:
                seen.add(nb)
                neighbors.append(nb)
    for nb in neighbors[:6]:  # 上限 6 篇,避免灌爆
        body = re.sub(r"^---\n.*?\n---\n", "", "\n".join(text_by_note[nb]), flags=re.S)  # 去 YAML frontmatter
        body = re.sub(r"^\s*>.*\n?", "", body, flags=re.M).strip()  # 去「> 來源」行
        out.append(f"\n🔗 相關連結筆記（順著 [[ ]] 帶出）來源：{nb}\n{body[:320]}")
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
