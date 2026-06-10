"""FastAPI 後端：把 ERP 的 agents 與 supervisor 流程包成 HTTP API 給前端呼叫。

啟動（在 erp-agent 根目錄執行，才能讀到 .env 並 import 到 agents/graph）：
    venv/bin/uvicorn api.server:app --reload --port 8000

端點：
    GET  /api/agents       列出 registry 登記的 Agent（給單一 agent 頁的選單）
    POST /api/agent        執行單一 Agent（單一 agent 頁）
    POST /api/chat         執行 supervisor 流程，回傳多 Agent 協作的完整對話（對話頁）
    POST /api/chat/stream  同上，但邊跑邊串流：每派一個 Agent、每段產出即時回傳（對話頁）
"""

import asyncio
import functools
import json
import os
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from api.auth import (
    AUTH_ENABLED,
    GOOGLE_CLIENT_ID,
    current_tenant,
    current_tenant_var,
    current_user,
    issue_app_jwt,
    user_id_of,
    verify_google_id_token,
)
from graph.erp_graph import ASK_MARKER, erp_graph
from graph.registry import AGENTS
from tools.excel_import import import_excel
from tools.ppt_tools import template_cards
from tools.rag_tools import ingest_file, kb_summary, sync_folder

app = FastAPI(title="ERP Agent API")

# 本機開發：允許前端（localhost:3000）跨來源呼叫
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 應用層併發背壓（白皮書 §25 P1-4）：限制「同時在途的 LLM 驅動請求」數量，超量直接回
# 429「稍後再試」，避免暴量時無限開工把容器記憶體打到 OOM、或一起變慢拖垮整機。
# 只擋貴的 LLM 端點（/api/chat、/api/chat/stream、/api/agent）；查狀態/下載等便宜端點不擋。
# ppt-agent 那層另有 PPT_MAX_CONCURRENCY 擋它自己的 CPU 密集渲染，兩層各司其職。
_API_MAX_CONCURRENCY = int(os.getenv("API_MAX_CONCURRENCY", "8"))
_inflight = asyncio.Semaphore(_API_MAX_CONCURRENCY)


async def _concurrency_slot():
    """取一個在途名額；滿了就回 429。用 FastAPI 依賴注入，名額在請求（含串流）結束才釋放。"""
    if _inflight.locked():  # 名額用罄（可用數 == 0）
        raise HTTPException(status_code=429, detail="伺服器忙碌中，請稍後再試")
    await _inflight.acquire()  # 此時必有名額、不會阻塞
    try:
        yield
    finally:
        _inflight.release()


# ── 登入 / 註冊（Google） ────────────────────────────────────────────────
@app.get("/api/auth/config")
def auth_config():
    """前端問：要不要登入 + 用哪個 Google Client ID（公開值，故由後端供給，前端免重 build）。
    沒設 GOOGLE_CLIENT_ID 就是單人模式，前端跳過登入頁。"""
    return {"auth_enabled": AUTH_ENABLED, "google_client_id": GOOGLE_CLIENT_ID}


@app.post("/api/auth/google")
def auth_google(credential: str = Form(...)):
    """前端送 Google ID token（credential）→ 驗證後回自家 JWT 與使用者資料（首次即註冊）。"""
    user = verify_google_id_token(credential)
    return {"token": issue_app_jwt(user), "user": {"email": user["email"], "name": user["name"]}}


# 產生的檔案（例如 ppt agent 產出的簡報）放這裡，透過 /files/<檔名> 提供下載
_GENERATED = Path(__file__).resolve().parent.parent / "generated"
_GENERATED.mkdir(exist_ok=True)


# 產物交付兩種模式（與 ppt-agent/adapters/storage.py 對稱）：
# - 設了 S3_ENDPOINT_URL+S3_BUCKET → /files 從物件儲存（MinIO/S3）串流。ppt-agent 上傳、
#   erp-api 下載，兩者改共用 bucket、不再共用磁碟 → 可跨節點（白皮書 §25 P0-2）。
# - 沒設 → 維持讀本地 generated/（單機/同節點，共享 PVC）。
def _s3_enabled() -> bool:
    return bool(os.getenv("S3_ENDPOINT_URL") and os.getenv("S3_BUCKET"))


@functools.lru_cache(maxsize=1)
def _s3_client():
    """S3 client（boto3，相容 MinIO 與 AWS S3）。只在 S3 模式才會被呼叫。"""
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
    )

# 上傳到知識庫（RAG）的原始檔放這裡永久保存，透過 /api/rag/file/<檔名> 提供下載／追溯
_UPLOADS = Path(__file__).resolve().parent.parent / "uploads"
_UPLOADS.mkdir(exist_ok=True)

# 知識庫 vault（Obsidian）：wiki/ 正式知識（RAG 只索引這層）、raw/ 原始證據、.drafts/ 待審草稿。
# 路徑可用環境變數 ERP_VAULT 覆蓋（預設指向 Windows 桌面的 vault，WSL 經 /mnt/c 讀取）。
_VAULT = Path(os.getenv("ERP_VAULT", "/mnt/c/Users/Administrator/Desktop/erp-kb"))


def _vault_md(folder: Path, name: str) -> Path:
    """把使用者給的檔名轉成 vault 內安全的 .md 路徑（擋目錄穿越、限定 .md）。"""
    safe = Path(name).name
    if not safe.endswith(".md"):
        raise HTTPException(status_code=400, detail="檔名須為 .md")
    return folder / safe


@app.get("/files/{name}")
def get_file(name: str):
    """提供產物下載（物件儲存或本地 generated/，由 S3 env 決定，見上方註解）。

    .pptx 等檔案一律帶 Content-Disposition: attachment **強制下載** —— 因為前端在
    另一個 port，瀏覽器會忽略 <a download> 的跨來源下載，必須靠這個標頭才會真的下載
    （否則點了只會在分頁開啟）。.html（如預覽頁）則用 inline 直接在瀏覽器開。
    """
    safe = Path(name).name  # 擋目錄穿越
    is_html = safe.lower().endswith((".html", ".htm"))

    if _s3_enabled():
        from botocore.exceptions import ClientError

        try:
            obj = _s3_client().get_object(Bucket=os.getenv("S3_BUCKET"), Key=safe)
        except ClientError:
            raise HTTPException(status_code=404, detail="檔案不存在")
        headers = None if is_html else {"Content-Disposition": f'attachment; filename="{safe}"'}
        media = obj.get("ContentType") or "application/octet-stream"
        return StreamingResponse(obj["Body"].iter_chunks(), media_type=media, headers=headers)

    # 共享磁碟模式（本機/同節點）
    path = _GENERATED / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="檔案不存在")
    if is_html:
        return FileResponse(str(path))  # 預覽頁：inline 開啟
    return FileResponse(str(path), filename=safe)  # 其餘：強制下載


def _save_upload(file: UploadFile | None) -> str | None:
    """把上傳的檔案存到暫存路徑，回傳路徑；沒檔案則回 None。"""
    if file is None:
        return None
    suffix = os.path.splitext(file.filename or "")[1] or ".pdf"
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(file.file.read())
    return path


def _compose(message: str, file: UploadFile | None) -> str:
    """把使用者訊息與（可選的）上傳檔路徑組成要給 Agent 的文字。"""
    path = _save_upload(file)
    if path:
        return f"{message}\n（已上傳檔案路徑：{path}）"
    return message


def _seed_from_history(history_json: str | None):
    """把前端傳來的對話歷史（編輯/重跑分支用）還原成 LangChain 訊息，作為流程種子。

    history_json 是 [{"role":"human"|"ai","content":..,"agent":..}, ...]。
    不重跑舊回合的 LLM，只把它們當作既有脈絡提供給 supervisor 判斷。
    """
    if not history_json:
        return []
    try:
        items = json.loads(history_json)
    except (ValueError, TypeError):
        return []
    msgs = []
    for it in items:
        content = it.get("content") or ""
        if it.get("role") == "human":
            msgs.append(HumanMessage(content=content))
        else:
            agent = it.get("agent")
            msgs.append(
                AIMessage(content=content, name=agent) if agent
                else AIMessage(content=content)
            )
    return msgs


# 走 python-pptx ppt-agent（預設）時，template 是固定四款，對應引擎 palette；
# 回滾到 Presenton（USE_PRESENTON_PPT=true）時改回向 Presenton 動態查詢。
_USE_PRESENTON_PPT = os.getenv("USE_PRESENTON_PPT", "false").lower() == "true"
_MCP_TEMPLATES = [
    {"key": "general", "zh": "通用"},
    {"key": "modern", "zh": "現代"},
    {"key": "standard", "zh": "標準"},
    {"key": "swift", "zh": "簡潔"},
]


@app.get("/api/ppt/templates")
def list_ppt_templates():
    """給單一 agent 頁的簡報 template 選擇器用：回傳目前可用的 template。"""
    return template_cards() if _USE_PRESENTON_PPT else _MCP_TEMPLATES


# ppt-workflow 的選項（給單一 agent 頁做成按鈕，對應 make_deck 的參數；每組第一個是預設）。
# 值對應 ppt-workflow interview 的合法選項；放這裡是 erp↔ppt-workflow 的 UI 契約。
_PPT_OPTIONS = {
    "audience": [
        {"key": "client", "zh": "對客戶提案"},
        {"key": "sales", "zh": "通用銷售"},
        {"key": "investor", "zh": "投資人/募資"},
        {"key": "internal", "zh": "內部討論"},
    ],
    "style": [
        {"key": "navy_amber", "zh": "穩重專業"},
        {"key": "teal_mint", "zh": "清新科技"},
        {"key": "charcoal", "zh": "極簡高級"},
        {"key": "terracotta", "zh": "溫暖人本"},
    ],
    "pages": [
        {"key": "short", "zh": "精簡 8–10"},
        {"key": "standard", "zh": "標準 12–15"},
        {"key": "full", "zh": "完整 18+"},
    ],
    "tone": [
        {"key": "data", "zh": "數據導向"},
        {"key": "story", "zh": "故事帶入"},
        {"key": "punchy", "zh": "簡潔有力"},
    ],
}
_PPT_OPTION_LABELS = {"audience": "對象", "style": "風格", "pages": "篇幅", "tone": "語氣"}


@app.get("/api/ppt/options")
def ppt_options():
    """ppt-workflow 的可選參數（對象/風格/篇幅/語氣），給單一 agent 頁做成按鈕。"""
    return {"groups": _PPT_OPTIONS, "labels": _PPT_OPTION_LABELS}


@app.get("/api/agents")
def list_agents():
    """給單一 agent 頁的選單用。"""
    return [
        {
            "name": name,
            "desc": cfg["desc"],
            "accepts_file": cfg.get("accepts_file", False),
            "needs_text": cfg.get("needs_text", True),
        }
        for name, cfg in AGENTS.items()
    ]


@app.post("/api/agent")
async def run_agent(
    name: str = Form(...),
    message: str = Form(...),
    file: UploadFile | None = File(None),
    _slot: None = Depends(_concurrency_slot),
    tenant: str = Depends(current_tenant),
):
    """執行單一指定的 Agent。"""
    if name not in AGENTS:
        raise HTTPException(status_code=404, detail=f"未知的 Agent：{name}")
    agent = AGENTS[name]["build"](with_memory=False)
    result = agent.invoke({"messages": [("user", _compose(message, file))]})
    reply = (result["messages"][-1].content or "").replace(ASK_MARKER, "").strip()
    return {"reply": reply}


@app.post("/api/chat")
async def chat(
    message: str = Form(...),
    session_id: str = Form(...),
    file: UploadFile | None = File(None),
    _slot: None = Depends(_concurrency_slot),
    tenant: str = Depends(current_tenant),
    user: dict | None = Depends(current_user),
):
    """執行 supervisor 流程，回傳整段多 Agent 協作對話（依 session_id 保留記憶）。"""
    # 對話是「個人層」：thread_id 含公司(org)＋個人(user)＋session，員工各自的對話互不干擾。
    config = {"configurable": {"thread_id": f"{tenant}:{user_id_of(user)}:{session_id}"}}
    result = erp_graph.invoke(
        {"messages": [("user", _compose(message, file))]}, config
    )
    messages = [
        {"agent": m.name, "role": m.type, "content": m.content}
        for m in result["messages"]
    ]
    return {"messages": messages}


@app.post("/api/chat/stream")
async def chat_stream(
    message: str = Form(...),
    session_id: str = Form(...),
    file: UploadFile | None = File(None),
    history: str | None = Form(None),
    _slot: None = Depends(_concurrency_slot),
    tenant: str = Depends(current_tenant),
    user: dict | None = Depends(current_user),
):
    """串流版 supervisor 流程：邊跑邊回傳，讓前端即時顯示「派了哪個 Agent、產出什麼」。

    回傳 NDJSON（每行一個 JSON）：
        {"type":"status","agent":"inventory"}   supervisor 決定指派某個 Agent（換它工作中）
        {"type":"message","agent":"inventory","content":"..."}  該 Agent 的產出
        {"type":"done"}                          流程結束
        {"type":"error","detail":"..."}          發生錯誤
    """
    text = _compose(message, file)  # 需在請求生命週期內讀取上傳檔，故先組好
    config = {"configurable": {"thread_id": f"{tenant}:{user_id_of(user)}:{session_id}"}}
    # 編輯/重跑分支會帶 history：用新的 session_id + 把先前對話當種子，避免與舊記憶衝突。
    # 一般接續對話不帶 history，靠 session_id 的既有記憶即可。
    seed = _seed_from_history(history) + [HumanMessage(content=text)]

    def events():
        # 串流的 generator 是延後在 threadpool 執行，contextvar 可能跟不過來，
        # 故在這裡用閉包捕到的 tenant 顯式設好，確保 RAG 等工具讀到正確租戶。
        current_tenant_var.set(tenant)
        try:
            for update in erp_graph.stream(
                {"messages": seed}, config, stream_mode="updates"
            ):
                for node, data in update.items():
                    if node == "supervisor":
                        route = (data or {}).get("route")
                        if route and route != "FINISH":
                            yield json.dumps(
                                {"type": "status", "agent": route},
                                ensure_ascii=False,
                            ) + "\n"
                    else:
                        for m in (data or {}).get("messages", []):
                            yield json.dumps(
                                {"type": "message", "agent": node, "content": m.content},
                                ensure_ascii=False,
                            ) + "\n"
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
        except Exception as e:  # 串流中途出錯也要讓前端知道，不要靜默斷掉
            yield json.dumps(
                {"type": "error", "detail": str(e)}, ensure_ascii=False
            ) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


# ── 後台：知識庫管理（RAG 訓練）─────────────────────────────────────────
# 前端的 RAG agent 只做問答；「建索引／訓練」集中在這裡，直接呼叫 rag_tools 的工具
# （不經 LLM，只花 embedding 費用）。供前端 /admin 頁使用。


@app.get("/api/rag/stats")
def rag_stats(tenant: str = Depends(current_tenant)):
    """回傳知識庫現況的結構化資料（總段數、來源數、各來源段數）給後台顯示。"""
    current_tenant_var.set(tenant)  # sync 端點走 threadpool，顯式設好供 rag_tools 讀
    return kb_summary()


@app.post("/api/rag/sync")
async def rag_sync(folder_path: str = Form(...), tenant: str = Depends(current_tenant)):
    """設定／同步要訓練的資料夾：把該資料夾內所有文件增量建索引。"""
    current_tenant_var.set(tenant)
    # 先擋掉「資料夾不存在」——否則 sync_folder 會回友善字串(HTTP 200)，
    # 前端會誤判成成功。回 400 讓前端正確顯示為錯誤。
    if not Path(folder_path).expanduser().is_dir():
        raise HTTPException(status_code=400, detail=f"找不到資料夾「{folder_path}」，請確認路徑正確且存在於後端機器上。")
    return {"text": sync_folder.invoke({"folder_path": folder_path})}


# RAG 原始檔在物件儲存的前綴（每租戶一個子前綴，跨 replica/節點共用，見 rag_tools）。
_S3_UPLOAD_PREFIX = "uploads/"


@app.post("/api/rag/upload")
async def rag_upload(file: UploadFile = File(...), tenant: str = Depends(current_tenant)):
    """上傳一個檔案加入知識庫（建索引）。以原檔名作為來源標籤。

    原檔保存供日後重嵌／下載／追溯：S3 模式存物件儲存（跨 replica 共用），否則存本地 uploads/。
    """
    current_tenant_var.set(tenant)  # 供 rag_tools 索引到正確租戶
    safe = Path(file.filename or "upload").name  # 擋目錄穿越
    data = file.file.read()
    path = _UPLOADS / safe  # 先寫本地：ingest 要讀實體檔做嵌入
    with open(path, "wb") as f:
        f.write(data)
    result = ingest_file.invoke({"file_path": str(path)})
    if _s3_enabled():  # 再上傳物件儲存（每租戶子前綴），讓任何 replica 都下載得到
        _s3_client().put_object(
            Bucket=os.getenv("S3_BUCKET"), Key=f"{_S3_UPLOAD_PREFIX}{tenant}/{safe}", Body=data
        )
    return {"text": result}


@app.get("/api/rag/file/{name}")
def get_rag_file(name: str, tenant: str = Depends(current_tenant)):
    """下載知識庫某個來源的原始檔（S3 模式從物件儲存，否則本地 uploads/）。"""
    safe = Path(name).name  # 擋目錄穿越
    if _s3_enabled():
        from botocore.exceptions import ClientError

        try:
            obj = _s3_client().get_object(
                Bucket=os.getenv("S3_BUCKET"), Key=f"{_S3_UPLOAD_PREFIX}{tenant}/{safe}"
            )
        except ClientError:
            raise HTTPException(status_code=404, detail="原始檔不存在（可能是貼上內容或資料夾同步來源）。")
        headers = {"Content-Disposition": f'attachment; filename="{safe}"'}
        return StreamingResponse(obj["Body"].iter_chunks(), media_type="application/octet-stream", headers=headers)
    path = _UPLOADS / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="原始檔不存在（可能是貼上內容或資料夾同步來源）。")
    return FileResponse(str(path), filename=safe)


# ── 後台：知識庫 vault 流程（上傳 → AI 編譯草稿 → 審核 → 發布）──────────────
# 讓使用者完全在前端完成「加資料」：上傳檔進 raw/、LLM 自動拆成原子筆記草稿進 .drafts/，
# 前端審核（可編輯）後發布到 wiki/ 並重新索引。RAG 只索引 wiki/，草稿不會汙染問答。


@app.post("/api/wiki/upload")
async def wiki_upload(file: UploadFile = File(...)):
    """上傳文件到 vault/raw/，用 LLM 自動編譯成原子筆記草稿（進 .drafts/ 待審）。"""
    from compile_wiki import compile_file_to_drafts  # 延遲匯入，避免影響伺服器啟動

    raw = _VAULT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    safe = Path(file.filename or "upload").name  # 擋目錄穿越
    (raw / safe).write_bytes(file.file.read())
    drafts = compile_file_to_drafts(str(raw / safe), str(_VAULT))
    return {"drafts": drafts,
            "text": f"已上傳「{safe}」並產生 {len(drafts)} 篇草稿，請於下方審核後發布。"}


@app.post("/api/wiki/compile-folder")
async def wiki_compile_folder(folder_path: str = Form(...)):
    """指定資料夾，把裡面所有文件都用 LLM 編譯成原子筆記草稿（進 .drafts/ 待審）。

    與 /api/rag/sync（直接索引原始檔、不整理）不同：這條會 AI 整理成筆記、需審核後才發布。
    檔多會花較久（每檔一次 LLM）。
    """
    from compile_wiki import compile_folder_to_drafts  # 延遲匯入

    base = Path(folder_path).expanduser()
    if not base.is_dir():
        raise HTTPException(status_code=400, detail=f"找不到資料夾「{folder_path}」，請確認路徑存在於後端機器上。")
    r = compile_folder_to_drafts(folder_path, str(_VAULT))
    return {**r, "text": f"已掃描 {r['files']} 個檔，產生 {r['drafts']} 篇草稿，請於下方審核後發布。"}


@app.get("/api/wiki/drafts")
def wiki_list_drafts():
    """列出 .drafts/ 內所有草稿（檔名 + 內容），供前端審核。"""
    d = _VAULT / ".drafts"
    if not d.is_dir():
        return []
    return [{"name": p.name, "content": p.read_text("utf-8")} for p in sorted(d.glob("*.md"))]


@app.post("/api/wiki/draft/delete")
async def wiki_draft_delete(name: str = Form(...)):
    """刪除某篇草稿（審核後不要的）。"""
    p = _vault_md(_VAULT / ".drafts", name)
    if p.is_file():
        p.unlink()
    return {"text": f"已刪除草稿「{p.name}」。"}


@app.post("/api/wiki/publish")
async def wiki_publish(name: str = Form(...), content: str = Form(...)):
    """把（可能編輯過的）草稿內容寫入 wiki/、刪掉草稿，並重新索引 wiki/。"""
    src = _vault_md(_VAULT / ".drafts", name)
    wiki = _VAULT / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    dst = _vault_md(wiki, name)
    dst.write_text(content, "utf-8")
    if src.is_file():
        src.unlink()
    msg = sync_folder.invoke({"folder_path": str(wiki)})
    return {"text": f"已發布「{dst.name}」到知識庫並重新索引。{msg}"}


@app.post("/api/wiki/publish-all")
async def wiki_publish_all(payload: str = Form(...)):
    """一次發布多篇草稿（payload 為 [{"name","content"},...] 的 JSON）：全部寫進 wiki/、
    刪掉對應草稿，最後只重新索引一次（比逐篇發布快）。"""
    items = json.loads(payload)
    wiki = _VAULT / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    drafts = _VAULT / ".drafts"
    for it in items:
        dst = _vault_md(wiki, it["name"])
        dst.write_text(it["content"], "utf-8")
        src = _vault_md(drafts, it["name"])
        if src.is_file():
            src.unlink()
    msg = sync_folder.invoke({"folder_path": str(wiki)})
    return {"count": len(items), "text": f"已發布 {len(items)} 篇到知識庫並重新索引。{msg}"}


# ── 後台：數據型 Excel 匯入資料庫（供 sql agent 精確查詢）──────────────────
# 與 RAG（語意問答）分工：規章/說明型文件走 /api/rag/upload；這裡處理「要算數/排序/
# 篩選」的數據型 Excel——每個分頁建成一張表灌進 PostgreSQL，並登記給 sql agent 查詢。

_SQL_IMPORTS = Path(__file__).resolve().parent.parent / "sql_imports"
_SQL_IMPORTS.mkdir(exist_ok=True)


@app.post("/api/sql/import-excel")
async def sql_import_excel(file: UploadFile = File(...)):
    """上傳一個數據型 Excel（.xlsx/.xls），每個分頁匯入成一張資料表供 sql agent 查詢。

    原檔保存在 sql_imports/（同名覆蓋），供日後重匯/追溯。
    """
    safe = Path(file.filename or "upload.xlsx").name  # 擋目錄穿越
    if not safe.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="只接受 Excel 檔（.xlsx / .xls）。")
    path = _SQL_IMPORTS / safe
    with open(path, "wb") as f:
        f.write(file.file.read())
    return {"text": import_excel(str(path), source_name=safe)}
