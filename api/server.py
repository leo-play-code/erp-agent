"""FastAPI 後端：把 ERP 的 agents 與 supervisor 流程包成 HTTP API 給前端呼叫。

啟動（在 erp-agent 根目錄執行，才能讀到 .env 並 import 到 agents/graph）：
    venv/bin/uvicorn api.server:app --reload --port 8000

端點：
    GET  /api/agents       列出 registry 登記的 Agent（給單一 agent 頁的選單）
    POST /api/agent        執行單一 Agent（單一 agent 頁）
    POST /api/chat         執行 supervisor 流程，回傳多 Agent 協作的完整對話（對話頁）
    POST /api/chat/stream  同上，但邊跑邊串流：每派一個 Agent、每段產出即時回傳（對話頁）
"""

import json
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from graph.erp_graph import ASK_MARKER, erp_graph
from graph.registry import AGENTS
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

# 產生的檔案（例如 ppt agent 產出的簡報）放這裡，透過 /files/<檔名> 提供下載
_GENERATED = Path(__file__).resolve().parent.parent / "generated"
_GENERATED.mkdir(exist_ok=True)

# 上傳到知識庫（RAG）的原始檔放這裡永久保存，透過 /api/rag/file/<檔名> 提供下載／追溯
_UPLOADS = Path(__file__).resolve().parent.parent / "uploads"
_UPLOADS.mkdir(exist_ok=True)


@app.get("/files/{name}")
def get_file(name: str):
    """提供 generated/ 內的檔案。

    .pptx 等檔案一律帶 Content-Disposition: attachment **強制下載** —— 因為前端在
    另一個 port，瀏覽器會忽略 <a download> 的跨來源下載，必須靠這個標頭才會真的下載
    （否則點了只會在分頁開啟）。.html（如預覽頁）則用 inline 直接在瀏覽器開。
    """
    safe = Path(name).name  # 擋目錄穿越
    path = _GENERATED / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="檔案不存在")
    if safe.lower().endswith((".html", ".htm")):
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
):
    """執行 supervisor 流程，回傳整段多 Agent 協作對話（依 session_id 保留記憶）。"""
    config = {"configurable": {"thread_id": session_id}}
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
):
    """串流版 supervisor 流程：邊跑邊回傳，讓前端即時顯示「派了哪個 Agent、產出什麼」。

    回傳 NDJSON（每行一個 JSON）：
        {"type":"status","agent":"inventory"}   supervisor 決定指派某個 Agent（換它工作中）
        {"type":"message","agent":"inventory","content":"..."}  該 Agent 的產出
        {"type":"done"}                          流程結束
        {"type":"error","detail":"..."}          發生錯誤
    """
    text = _compose(message, file)  # 需在請求生命週期內讀取上傳檔，故先組好
    config = {"configurable": {"thread_id": session_id}}
    # 編輯/重跑分支會帶 history：用新的 session_id + 把先前對話當種子，避免與舊記憶衝突。
    # 一般接續對話不帶 history，靠 session_id 的既有記憶即可。
    seed = _seed_from_history(history) + [HumanMessage(content=text)]

    def events():
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
def rag_stats():
    """回傳知識庫現況的結構化資料（總段數、來源數、各來源段數）給後台顯示。"""
    return kb_summary()


@app.post("/api/rag/sync")
async def rag_sync(folder_path: str = Form(...)):
    """設定／同步要訓練的資料夾：把該資料夾內所有文件增量建索引。"""
    # 先擋掉「資料夾不存在」——否則 sync_folder 會回友善字串(HTTP 200)，
    # 前端會誤判成成功。回 400 讓前端正確顯示為錯誤。
    if not Path(folder_path).expanduser().is_dir():
        raise HTTPException(status_code=400, detail=f"找不到資料夾「{folder_path}」，請確認路徑正確且存在於後端機器上。")
    return {"text": sync_folder.invoke({"folder_path": folder_path})}


@app.post("/api/rag/upload")
async def rag_upload(file: UploadFile = File(...)):
    """上傳一個檔案加入知識庫（建索引）。以原檔名作為來源標籤。

    原檔永久保存在 uploads/（同名覆蓋），既當索引「來源」標籤，也供日後重嵌／下載／追溯。
    """
    safe = Path(file.filename or "upload").name  # 擋目錄穿越
    path = _UPLOADS / safe
    with open(path, "wb") as f:
        f.write(file.file.read())
    return {"text": ingest_file.invoke({"file_path": str(path)})}


@app.get("/api/rag/file/{name}")
def get_rag_file(name: str):
    """下載知識庫某個來源的原始檔（從 uploads/ 提供）。"""
    safe = Path(name).name  # 擋目錄穿越
    path = _UPLOADS / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="原始檔不存在（可能是貼上內容或資料夾同步來源）。")
    return FileResponse(str(path), filename=safe)
