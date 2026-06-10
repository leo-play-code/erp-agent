"""所有 Agent 的共用框架。

設計重點：
- get_llm() 是「唯一」決定要用哪個 LLM 的地方。之後要從 OpenAI 換成本地模型，
  只需要改這一個函數，其他 Agent 完全不用動。
- get_checkpointer() 是「唯一」決定對話記憶存哪裡的地方（RAM 或 Postgres）。
  換記憶後端只改這一個函數，create_agent() 與 graph 都向它要 checkpointer。
- create_agent() 用 LangGraph 的 create_react_agent 建立 Agent，回傳的本身就是
  一個 LangGraph graph，所以日後可以直接接進更大的 LangGraph 流程。
- 透過 checkpointer 提供對話記憶（呼叫時帶 thread_id 即可分辨對話）。
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

load_dotenv()


def get_llm(tier: str = "default"):
    """建立並回傳 LLM 實例。

    *** 換模型只需改這裡 ***
    例如要換成本地的 Ollama 模型：
        from langchain_ollama import ChatOllama
        return ChatOllama(model="llama3.1", temperature=0)
    其餘 Agent 程式碼都不需要更動。

    模型分級（白皮書 §25 P1-7，省成本/擋速率）：用 tier 區分任務難度——
    - "default"：一般任務，用 OPENAI_MODEL。
    - "fast"   ：調度/簡單任務（如 supervisor 路由），用 OPENAI_MODEL_FAST（便宜/快）。
    - "strong" ：難任務（如 analyst 決策分析），用 OPENAI_MODEL_STRONG（最強）。
    fast/strong 的 env 沒設時都「回退到 OPENAI_MODEL」→ 不設就是現況、零行為變更。
    max_retries 內建指數退避，撞 rate limit 時自動重試（次數可用 OPENAI_MAX_RETRIES 調）。
    """
    default_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    model = {
        "fast": os.getenv("OPENAI_MODEL_FAST", default_model),
        "strong": os.getenv("OPENAI_MODEL_STRONG", default_model),
    }.get(tier, default_model)
    return ChatOpenAI(
        model=model,
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "2")),
    )


# PostgresSaver 是「重資源」（連線池 + 建表），全程式共用一個；MemorySaver 是輕量
# 的退路，每次回傳新的一個（沿用原本「每個 Agent 各自隔離」的語意）。
_pg_saver = None
_pg_failed = False


def get_checkpointer():
    """建立並回傳對話記憶後端（LangGraph checkpointer）。

    *** 換記憶後端只需改這裡 ***
    - 設了 CHECKPOINT_DATABASE_URL（或退而用 DATABASE_URL）且連得上 Postgres：
      用 PostgresSaver 持久化到資料庫。記憶不在 RAM，erp-agent 才能開多 replica
      （任何 replica 都接得到同一條對話），程式重啟記憶也還在。
    - 連不上 / 沒設：優雅退回 MemorySaver（RAM、程式關掉即消失）。服務沒起來時
      erp 仍能 import、驗證仍過，只是記憶不持久、不能橫向擴。

    checkpoint 資料表（checkpoints / checkpoint_writes 等）建在 URL 指向的資料庫，
    用的是「可寫」連線，和 sql_tools 對 ERP 的唯讀連線完全獨立、表名不衝突。
    """
    global _pg_saver, _pg_failed

    url = os.getenv("CHECKPOINT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if url and not _pg_failed:
        if _pg_saver is not None:
            return _pg_saver
        try:
            import psycopg
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg_pool import ConnectionPool

            # 先用短逾時探一下連得上嗎：連不上就「快速且安靜」退回 RAM。
            # （直接開 pool 會在背景持續重連並噴一堆連線錯誤 log，dev/驗證很吵。）
            psycopg.connect(url, connect_timeout=3).close()

            pool = ConnectionPool(
                conninfo=url,
                min_size=1,
                max_size=10,
                # autocommit：PostgresSaver 要求；prepare_threshold=0：相容連線池/PgBouncer
                kwargs={"autocommit": True, "prepare_threshold": 0, "connect_timeout": 3},
                open=False,
            )
            pool.open(wait=True, timeout=5)
            saver = PostgresSaver(pool)
            saver.setup()  # 冪等建表，已存在不會重建
            _pg_saver = saver
            return _pg_saver
        except Exception as e:
            # 連不上就標記失敗、之後不再重試，本次起退回 RAM
            _pg_failed = True
            print(f"[checkpointer] Postgres 不可用，退回 MemorySaver：{e}")

    return MemorySaver()


def create_agent(tools, system_prompt, with_memory=True, tier="default"):
    """所有 Agent 的統一建立入口。

    Args:
        tools: 這個 Agent 可以使用的工具清單（list）。
        system_prompt: 系統提示詞，定義 Agent 的角色與行為。
        with_memory: 是否讓這個 Agent 自帶對話記憶。
            - True（預設）：單獨使用時帶記憶，後端由 get_checkpointer() 決定
              （Postgres 或 RAM）；用 thread_id 區隔不同對話。
            - False：要把這個 Agent 當成節點接進更大的 LangGraph 流程時用，
              記憶交由「父層流程」統一管理，避免兩層 checkpointer 互相打架。
        tier: LLM 分級（見 get_llm）。難任務的 Agent 傳 "strong"，預設 "default"。

    Returns:
        一個可直接 invoke、也可接入 LangGraph 的 agent graph。
    """
    return create_react_agent(
        model=get_llm(tier),
        tools=tools,
        prompt=system_prompt,
        checkpointer=get_checkpointer() if with_memory else None,
    )
