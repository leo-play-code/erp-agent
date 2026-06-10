"""從 ppt-agent（獨立部署的可攜式 agent）經 MCP 載入簡報工具。

設計重點：
- erp-agent **不 import ppt 的任何實作**，只透過 MCP 契約（sse / stdio）連到一個跑起來的
  ppt-agent 服務，取得 make_presentation / make_proposal 兩個工具。換版本只改 URL，不汙染。
- MCP 工具是 **async-only**（sync invoke 會丟 NotImplementedError）。本專案的 graph 與 api
  全是同步呼叫（erp_graph.invoke/.stream、node 內 agent.invoke），為避免改動其他 8 個 agent
  與圖的執行模型，這裡把 async MCP 工具**包成同步工具**：在背景事件迴圈執行緒上跑它的
  coroutine，呼叫端維持同步、零感知。
- 載入失敗（服務沒起來 / 相依缺）一律**優雅退回空清單**，讓 erp_graph 仍能 import、
  驗證仍能過；服務起來後即可正常產出。

放在 tools/（而非 graph/）是為了守住單向依賴 graph → agents → tools：ppt_agent 會 import 它。

環境變數（見 .env.example）：
    PPT_AGENT_TRANSPORT   sse | stdio（預設 stdio：本機免另起服務，自動 spawn 子行程）
    PPT_AGENT_URL         transport=sse 時連的位址（預設 http://ppt-agent:8000/sse）
    PPT_AGENT_DIR/PYTHON  transport=stdio 時 ppt-agent 專案路徑與其 venv python
    OUTPUTS_DIR           ppt-agent 寫檔的目錄；需與 api 的 /files 指到同一處
"""

import asyncio
import os
import threading
from pathlib import Path

from langchain_core.tools import StructuredTool

_TOOLS = None                 # 快取：載入過就不再重連
_LOOP = None                  # 背景事件迴圈（橋接 sync→async）
_LOOP_LOCK = threading.Lock()

# ppt-agent 寫檔目錄；stdio 模式由本模組 spawn 子行程，預設指到 erp 的 generated/（/files 服務的同一處）。
_DEFAULT_OUTPUTS = str(Path(__file__).resolve().parent.parent / "generated")
# ppt-agent 是 sibling 的獨立服務（預設 ../agents/ppt-agent，相對於 erp-agent）。
# 注意：這個路徑只給 stdio 退路（本機 spawn）與 start.sh 用；sse 模式只認 PPT_AGENT_URL，不碰路徑。
_ERP_ROOT = Path(__file__).resolve().parent.parent
_PPT_DIR = os.getenv("PPT_AGENT_DIR", str(_ERP_ROOT.parent / "agents" / "ppt-agent"))


def _bg_loop():
    """專屬背景執行緒上的事件迴圈：MCP 的 coroutine 都丟到這裡跑，與主行程/uvicorn 迴圈隔離，
    所以不論呼叫端在不在 running loop 裡，都不會撞到『event loop already running』。"""
    global _LOOP
    loop = asyncio.new_event_loop()
    _LOOP = loop
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _run(coro):
    """同步等待一個 coroutine 在背景迴圈上的結果。"""
    global _LOOP
    if _LOOP is None:
        with _LOOP_LOCK:
            if _LOOP is None:
                t = threading.Thread(target=_bg_loop, daemon=True)
                t.start()
                while _LOOP is None:  # 等迴圈備妥（瞬間）
                    pass
    return asyncio.run_coroutine_threadsafe(coro, _LOOP).result()


def _server_conf():
    """依環境組出 MCP server 連線設定（sse 連既有服務；stdio 本機 spawn 子行程）。"""
    transport = os.getenv("PPT_AGENT_TRANSPORT", "stdio").lower()
    if transport == "sse":
        return {"url": os.getenv("PPT_AGENT_URL", "http://ppt-agent:8000/sse"),
                "transport": "sse"}
    py = os.getenv("PPT_AGENT_PYTHON", str(Path(_PPT_DIR) / ".venv" / "bin" / "python"))
    env = {**os.environ,
           "MCP_TRANSPORT": "stdio",
           "OUTPUTS_DIR": os.getenv("OUTPUTS_DIR", _DEFAULT_OUTPUTS),
           "PUBLIC_FILES_PREFIX": os.getenv("PUBLIC_FILES_PREFIX", "/files")}
    return {"command": py, "args": ["-m", "portable_agent.adapters.mcp_server"],
            "transport": "stdio", "cwd": _PPT_DIR, "env": env}


def _as_text(result):
    """把 MCP 工具回傳（可能是 content blocks 清單）攤平成給 LLM 讀的字串。"""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in result]
        return "\n".join(p for p in parts if p)
    return str(result)


def _sync_wrap(async_tool):
    """把一個 async MCP 工具包成同步 StructuredTool（保留名稱/說明/參數結構）。"""
    def func(**kwargs):
        return _as_text(_run(async_tool.ainvoke(kwargs)))

    return StructuredTool(
        name=async_tool.name,
        description=async_tool.description,
        args_schema=async_tool.args_schema,
        func=func,
    )


def load_ppt_tools():
    """載入並快取 ppt-agent 的 MCP 工具（已同步化）。失敗回空清單（不讓整個 app 起不來）。"""
    global _TOOLS
    if _TOOLS is not None:
        return _TOOLS
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        client = MultiServerMCPClient({"ppt": _server_conf()})
        async_tools = _run(client.get_tools())
        _TOOLS = [_sync_wrap(t) for t in async_tools]
    except Exception as e:  # 服務沒起來 / 相依缺：別讓 import 與驗證掛掉
        print(f"[ppt_mcp] 載入 ppt-agent MCP 工具失敗，ppt 暫時無工具可用：{type(e).__name__}: {e}")
        _TOOLS = []
    return _TOOLS
