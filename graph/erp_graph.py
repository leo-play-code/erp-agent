"""ERP 主流程（LangGraph）—— supervisor 模式。

結構：
    START → supervisor →（指派）→ 某個 Agent → supervisor → ... → FINISH(END)

- supervisor：看完整對話進度，決定「下一步交給哪個 Agent」或「FINISH 結束」。
  因此一個請求可以串接多個 Agent（例：先 pdf 分析、再 inventory 查庫存）。
- 各 Agent 節點：執行後把產出（標記該 Agent 名稱）寫回 messages，再回到 supervisor。
- 記憶體由「這個流程」用一個 checkpointer 統一管理（後端見 base_agent.get_checkpointer()：
  Postgres 持久化或 RAM 退路）；子 Agent 都以 with_memory=False 建立，避免兩層衝突。

★ 整張圖完全由 graph/registry.py 的 AGENTS 字典驅動 ★
  supervisor 選項、提示詞、節點、邊都從 AGENTS 自動生成。加新 Agent 改 registry 即可。
"""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, Field, create_model

from agents.base_agent import get_checkpointer, get_llm
from graph.registry import AGENTS

# 子 Agent：接入流程，記憶交給父層，所以 with_memory=False
_agents = {name: cfg["build"](with_memory=False) for name, cfg in AGENTS.items()}


# Agent 要向使用者提問、等待補充資訊時，在訊息結尾放這個機器標記。
# 節點會偵測它、記下 pending_agent，並把標記從顯示內容中移除（使用者看不到）。
ASK_MARKER = "[[ASK_USER]]"


class ERPState(MessagesState):
    """在內建的 messages 之外，額外帶兩個欄位。

    - route：supervisor 的路由決策。
    - pending_agent：正在「等待使用者補充資訊」的 Agent 名稱（空字串=沒有）。
      下一輪使用者一回覆，入口會用程式直接把工作接回這個 Agent，不經過 supervisor 猜測。
    """

    route: str
    pending_agent: str


# supervisor 的結構化輸出：next 是某個 Agent 名稱，或 FINISH（結束）
_Route = create_model(
    "_Route",
    next=(
        Literal[tuple(AGENTS) + ("FINISH",)],  # 例如 Literal["pdf","inventory","FINISH"]
        Field(description="下一步要指派的 Agent；若需求已全部完成則填 FINISH。"),
    ),
    __base__=BaseModel,
)

_ROUTE_HINT = "\n".join(f"- {name}：{cfg['desc']}" for name, cfg in AGENTS.items())
_SUPERVISOR_PROMPT = SystemMessage(
    content=(
        "你是 ERP 助理的調度者（supervisor）。看懂使用者的需求，並協調下列 Agent "
        "一步步完成它：\n"
        f"{_ROUTE_HINT}\n\n"
        "規則：\n"
        "0. 區分『查資料』與『問制度』：問**具體數字/某人某筆紀錄**（某員工特休剩幾天、"
        "某月營收）才派 `sql`；問**規定/政策/制度**（新進員工依規定該有幾天特休、請假規則、"
        "加班辦法 這類『該怎麼算/有什麼規定』）優先派給 `rag` 去查公司文件，不要丟給 `sql`"
        "（資料庫存的是實際紀錄、不是規章，丟給 sql 只會查不到）。\n"
        "1. 每次只指派一個 Agent，挑最適合處理使用者「當前需求」的那一個。\n"
        "2. 已完成的步驟，其輸出會以該 Agent 的名稱標記在訊息中，據此判斷進度。\n"
        "3. 當某個 Agent『向使用者提問或請求補充資訊』（例如請使用者選擇簡報風格代號）時：\n"
        "   - 若最後一則訊息就是『該 Agent 的提問』（使用者尚未回覆）→ 回答 FINISH，"
        "把控制權交還給使用者去回答，不要再指派任何 Agent。\n"
        "   - 若最後一則訊息是『使用者提供了該資訊』→ 把工作指派回『原本提問的那個 Agent』"
        "讓它接著完成，不要改派別的 Agent。\n"
        "   （提示：每則 Agent 產出都標有其名稱；當使用者的回覆很簡短，像是一個代號、"
        "是/否、或從選項中挑一個時，幾乎都是在回答『最近一個向他提問的 Agent』，請指派回那個 Agent。）\n"
        "4. 其餘情況：只有在使用者的需求『確實已產出最終結果』（已給出明確答案，或已產生"
        "可下載的檔案連結）時，才回答 FINISH。\n"
        "5. 不要重複指派『已經產出最終結果』的 Agent；但第 3 點不受此限。"
    )
)


def _done_agents(state: ERPState):
    """本回合（最後一則使用者訊息之後）已產出過答案的 Agent 名稱集合。"""
    done = set()
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage):  # 回溯到本回合起點即停
            break
        name = getattr(m, "name", None)
        if name:
            done.add(name)
    return done


def supervisor_node(state: ERPState):
    """看完整對話進度，決定下一步交給哪個 Agent，或 FINISH 結束。

    外加「硬性防重派」：supervisor 的提示詞要求它別重派已產出答案的 Agent，但 LLM 在
    答案不理想時常會忍不住一直重試同一個，造成同樣的回答被輸出好幾次。這裡用程式擋住——
    若它選的 Agent 在本回合已經產出過答案，直接改成 FINISH，把控制權交還使用者。
    （ASK 等待補充資訊的重跑走 _entry_router、不經 supervisor，故不受影響。）"""
    llm = get_llm("fast").with_structured_output(_Route)  # 調度用便宜/快模型（P1-7）
    decision = llm.invoke([_SUPERVISOR_PROMPT] + state["messages"])
    route = decision.next
    if route != "FINISH" and route in _done_agents(state):
        route = "FINISH"
    return {"route": route}


def _make_node(name, agent):
    """把一個子 Agent 包成流程節點：執行後回傳最後一則訊息，並標記是哪個 Agent。

    若該訊息含 ASK_MARKER（表示 Agent 在向使用者提問），則：移除標記、把 pending_agent
    設為自己；否則 pending_agent 清空（已產出結果、不在等待）。
    """

    def node(state: ERPState):
        result = agent.invoke({"messages": state["messages"]})
        last = result["messages"][-1]
        content = last.content or ""
        pending = ""
        if ASK_MARKER in content:
            content = content.replace(ASK_MARKER, "").strip()
            pending = name
        msg = last.model_copy(update={"name": name, "content": content})
        return {"messages": [msg], "pending_agent": pending}

    return node


def _entry_router(state: ERPState):
    """入口路由：上一輪有 Agent 在等使用者回覆，就直接接回它（程式決定，不靠 LLM）。"""
    pending = state.get("pending_agent") or ""
    return pending if pending in AGENTS else "supervisor"


def _after_agent(state: ERPState):
    """Agent 跑完：若它在等使用者回覆就結束（交還使用者），否則回到 supervisor。"""
    return "wait_user" if state.get("pending_agent") else "supervisor"


def _build_graph():
    builder = StateGraph(ERPState)
    builder.add_node("supervisor", supervisor_node)
    for name, agent in _agents.items():
        builder.add_node(name, _make_node(name, agent))

    # 入口：若上一輪有 Agent 在等使用者回覆，程式直接接回它；否則交給 supervisor
    builder.add_conditional_edges(
        START,
        _entry_router,
        {**{name: name for name in AGENTS}, "supervisor": "supervisor"},
    )
    # supervisor 依決策路由到某個 Agent，或結束
    builder.add_conditional_edges(
        "supervisor",
        lambda state: state["route"],
        {**{name: name for name in AGENTS}, "FINISH": END},
    )
    # 每個 Agent 跑完：在等使用者回覆就結束（交還使用者），否則回到 supervisor
    for name in AGENTS:
        builder.add_conditional_edges(
            name, _after_agent, {"wait_user": END, "supervisor": "supervisor"}
        )

    # 整個流程的記憶體統一在這裡管理（Postgres 或 RAM，由 get_checkpointer() 決定）
    return builder.compile(checkpointer=get_checkpointer())


erp_graph = _build_graph()


if __name__ == "__main__":
    config = {"configurable": {"thread_id": "demo"}}
    # 串接測試：需要先 pdf 分析、再 inventory 查庫存
    question = (
        "請分析 samples/po.pdf 這份採購單的重點，"
        "並查詢裡面提到的品項目前庫存各有多少。"
    )
    result = erp_graph.invoke({"messages": [("user", question)]}, config)
    print(f"\nQ: {question}\n")
    for m in result["messages"]:
        who = m.name or m.type
        print(f"[{who}] {m.content}\n")
